"""
数据库同步脚本
用于在主数据库和备份数据库之间同步数据
"""
import os
import sys
import logging
import json
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text, MetaData, Table, inspect
from sqlalchemy.orm import sessionmaker
import psycopg2
from psycopg2.extras import RealDictCursor

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.dual_db_config import dual_db
from src.utils.time_helpers import get_beijing_time

logger = logging.getLogger(__name__)

class BackupStatus:
    """备份状态管理"""
    def __init__(self):
        self.tasks = {}  # task_id -> status_info

    def create_task(self, task_type="backup"):
        """创建新的备份任务"""
        task_id = str(uuid.uuid4())
        self.tasks[task_id] = {
            'id': task_id,
            'type': task_type,
            'status': 'running',
            'progress': 0,
            'current_table': '',
            'total_tables': 0,
            'completed_tables': 0,
            'total_rows': 0,
            'start_time': get_beijing_time(),
            'end_time': None,
            'error': None,
            'details': [],
            'user_id': None
        }
        return task_id

    def update_task(self, task_id, **kwargs):
        """更新任务状态"""
        if task_id in self.tasks:
            self.tasks[task_id].update(kwargs)
            # 只要有completed_tables或total_tables更新，就重新计算进度
            if 'completed_tables' in kwargs or 'total_tables' in kwargs:
                total = self.tasks[task_id]['total_tables']
                completed = self.tasks[task_id]['completed_tables']
                if total > 0:
                    progress = int((completed / total) * 100)
                    self.tasks[task_id]['progress'] = progress
                    logger.info(f"任务 {task_id} 进度更新: {completed}/{total} = {progress}%")

    def complete_task(self, task_id, success=True, error=None):
        """完成任务"""
        if task_id in self.tasks:
            self.tasks[task_id].update({
                'status': 'completed' if success else 'failed',
                'progress': 100 if success else self.tasks[task_id]['progress'],
                'end_time': get_beijing_time(),
                'error': error
            })

    def get_task(self, task_id):
        """获取任务状态"""
        return self.tasks.get(task_id)

    def cleanup_old_tasks(self, max_age_hours=24):
        """清理旧任务"""
        cutoff = get_beijing_time() - timedelta(hours=max_age_hours)
        to_remove = []
        for task_id, task in self.tasks.items():
            if task['start_time'] < cutoff:
                to_remove.append(task_id)
        for task_id in to_remove:
            del self.tasks[task_id]

# 全局备份状态管理器
backup_status = BackupStatus()

class DatabaseSyncer:
    """数据库同步器"""
    
    def __init__(self):
        self.dual_db = dual_db
        self.sync_log = []
    
    def _table_exists(self, conn, table_name: str) -> bool:
        """跨数据库检查表是否存在，兼容SQLite和PostgreSQL"""
        try:
            inspector = inspect(conn)
            return bool(inspector.has_table(table_name))
        except Exception as e:
            # 避免 PostgreSQL 事务处于 aborted 状态导致后续查询被忽略
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                # 回退方案：根据方言执行原生SQL
                dialect = getattr(conn, 'dialect', None)
                dialect_name = getattr(dialect, 'name', '') if dialect else ''
                if dialect_name == 'sqlite':
                    result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name = :name"), {"name": table_name}).fetchone()
                    return result is not None
                else:
                    result = conn.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :name)"), {"name": table_name}).scalar()
                    return bool(result)
            except Exception as e2:
                logger.warning(f"表存在性检查失败: {table_name}: {e2}")
                return False

    def log_sync_action(self, action, status, details=None):
        """记录同步操作"""
        # 使用北京时间
        beijing_time = get_beijing_time()
        # 强制确保时区信息包含在时间戳中
        if beijing_time.tzinfo is None:
            # 如果没有时区信息，手动添加
            import pytz
            beijing_tz = pytz.timezone('Asia/Shanghai')
            beijing_time = beijing_tz.localize(beijing_time)

        # 使用ISO 8601格式，确保包含时区信息
        timestamp_str = beijing_time.isoformat()
        log_entry = {
            'timestamp': timestamp_str,
            'action': action,
            'status': status,
            'details': details
        }
        self.sync_log.append(log_entry)
        # 记录操作日志
        logger.info(f"同步操作: {action} - {status}")
        if details:
            logger.info(f"详情: {details}")
    
    def start_async_backup(self, user_id=None):
        """启动异步备份，立即返回任务ID"""
        task_id = backup_status.create_task("backup")

        # 保存用户ID到任务中，用于完成时记录日志
        if user_id:
            backup_status.update_task(task_id, user_id=user_id)

        # 在后台线程中执行备份
        backup_thread = threading.Thread(
            target=self._async_backup_worker,
            args=(task_id,),
            daemon=True
        )
        backup_thread.start()

        return task_id

    def _async_backup_worker(self, task_id):
        """异步备份工作线程"""
        try:
            success = self._backup_with_progress(task_id)
            backup_status.complete_task(task_id, success=success)

            # 获取任务信息，包括用户ID
            task = backup_status.get_task(task_id)
            user_id = task['user_id'] if task else None
            total_rows = task['total_rows'] if task else 0

            # 记录完成日志到系统日志（使用正确的log_action函数）
            if success:
                self._log_to_system(
                    action="数据库同步",
                    details=f"异步备份成功完成，共处理 {total_rows} 行数据",
                    user_id=user_id
                )
            else:
                self._log_to_system(
                    action="数据库同步",
                    details="异步备份执行失败",
                    user_id=user_id
                )

        except Exception as e:
            logger.error(f"异步备份失败: {e}")
            backup_status.complete_task(task_id, success=False, error=str(e))

            # 记录异常日志
            task = backup_status.get_task(task_id)
            user_id = task['user_id'] if task else None
            self._log_to_system(
                action="数据库同步",
                details=f"异步备份异常: {str(e)}",
                user_id=user_id
            )

    def get_backup_status(self, task_id):
        """获取备份任务状态"""
        task = backup_status.get_task(task_id)
        if not task:
            logger.warning(f"任务 {task_id} 不存在")
            return None

        # 转换为前端友好的格式
        def format_time_with_timezone(dt):
            """确保时间包含时区信息"""
            if dt is None:
                return None
            # 如果没有时区信息，手动添加北京时区
            if dt.tzinfo is None:
                import pytz
                beijing_tz = pytz.timezone('Asia/Shanghai')
                dt = beijing_tz.localize(dt)
            return dt.isoformat()
        
        status_data = {
            'id': task['id'],
            'status': task['status'],
            'progress': task['progress'],
            'current_table': task['current_table'],
            'completed_tables': task['completed_tables'],
            'total_tables': task['total_tables'],
            'total_rows': task['total_rows'],
            'error': task['error'],
            'start_time': format_time_with_timezone(task['start_time']),
            'end_time': format_time_with_timezone(task['end_time'])
        }

        logger.info(f"返回任务状态: {status_data}")
        return status_data

    def _log_to_system(self, action, details, user_id=None):
        """记录日志到系统日志表（处理应用上下文问题）"""
        if not user_id:
            logger.warning(f"无用户ID，跳过系统日志记录: {action} - {details}")
            return

        # 直接使用数据库操作，避免Flask上下文问题
        self._log_to_database_direct(action, details, user_id)

    def _log_to_database_direct(self, action, details, user_id):
        """直接操作数据库记录日志（避免Flask上下文问题）"""
        try:
            from sqlalchemy import create_engine, text
            from datetime import datetime

            # 使用已有的数据库配置
            if hasattr(self, 'dual_db') and self.dual_db.is_dual_db_enabled():
                database_url = self.dual_db.primary_db_url
            else:
                import os
                database_url = os.getenv('DATABASE_URL')

            if not database_url:
                logger.error("无法获取数据库URL，跳过日志记录")
                return

            # 创建独立的数据库连接
            connect_args = {'connect_timeout': 10} if 'postgresql' in database_url else {}
            engine = create_engine(database_url, connect_args=connect_args)

            with engine.connect() as conn:
                # 检查system_logs表是否存在（跨数据库兼容）
                if not self._table_exists(conn, 'system_logs'):
                    logger.warning("system_logs表不存在，跳过日志记录")
                    return
                
                # 插入系统日志
                insert_sql = text("""
                    INSERT INTO system_logs (action, details, user_id, created_at)
                    VALUES (:action, :details, :user_id, :created_at)
                """)

                conn.execute(insert_sql, {
                    'action': action,
                    'details': details,
                    'user_id': user_id,
                    'created_at': datetime.now()
                })

                conn.commit()
                logger.info(f"系统日志记录成功: {action} - {details}")

        except Exception as e:
            logger.error(f"系统日志记录失败: {e}")
            # 记录到同步日志作为备用
            status = "成功" if "成功" in details else ("失败" if "失败" in details or "异常" in details else "完成")
            self.log_sync_action(action, status, f"{details} (用户ID: {user_id})")

    def backup_to_clawcloud(self):
        """将主数据库备份到ClawCloud - 同步版本（保持向后兼容）"""
        return self._backup_with_progress(None)

    def _backup_with_progress(self, task_id):
        """带进度反馈的备份实现"""
        import time
        start_time = time.time()
        max_duration = 150  # 最大150秒执行时间（2.5分钟，确保在前端3分钟超时前完成）

        if not self.dual_db.is_dual_db_enabled():
            if task_id:
                backup_status.update_task(task_id, error="双数据库未配置")
            self.log_sync_action("备份到ClawCloud", "失败", "双数据库未配置")
            return False

        try:
            if task_id:
                backup_status.update_task(task_id, current_table="连接数据库")
            self.log_sync_action("开始备份", "进行中", "连接数据库")

            # 测试数据库连接
            try:
                from sqlalchemy import create_engine, text
                primary_connect_args = {'connect_timeout': 10} if 'postgresql' in self.dual_db.primary_db_url else {}
                backup_connect_args = {'connect_timeout': 10} if 'postgresql' in self.dual_db.backup_db_url else {}
                primary_engine = create_engine(self.dual_db.primary_db_url, connect_args=primary_connect_args)
                backup_engine = create_engine(self.dual_db.backup_db_url, connect_args=backup_connect_args)

                # 测试连接
                with primary_engine.connect() as conn:
                    conn.execute(text('SELECT 1'))
                with backup_engine.connect() as conn:
                    conn.execute(text('SELECT 1'))

                self.log_sync_action("数据库连接", "成功", "主数据库和备份数据库连接正常")

            except Exception as e:
                self.log_sync_action("数据库连接", "失败", f"连接错误: {str(e)}")
                return False

            # 获取要同步的表（按优先级和大小排序）
            # 优先同步小表，最后同步大表
            tables_to_sync = [
                # 第一阶段：基础小表（快速同步）
                'roles', 'tags',
                # 第二阶段：用户和活动表（中等大小）
                'users', 'activities',
                # 第三阶段：关联表（通常较小）
                'activity_tags', 'user_tags',
                # 第四阶段：会话表（中等大小）
                'ai_chat_session', 'ai_chat_message',
                # 第五阶段：其他依赖表（较小）
                'activity_registrations', 'checkin_records', 'messages', 'notifications',
                # 最后阶段：大表（可能很慢）
                'system_logs'  # 通常是最大的表，放在最后
            ]

            synced_tables = 0
            total_rows = 0

            if task_id:
                backup_status.update_task(task_id, total_tables=len(tables_to_sync))

            with primary_engine.connect() as primary_conn, backup_engine.connect() as backup_conn:
                # 禁用外键约束检查（PostgreSQL）
                try:
                    if 'postgresql' in self.dual_db.backup_db_url:
                        backup_conn.execute(text('SET session_replication_role = replica'))
                        self.log_sync_action("禁用外键约束", "成功", "临时禁用外键约束检查")
                except Exception as e:
                    self.log_sync_action("禁用外键约束", "警告", f"无法禁用外键约束: {str(e)}")

                try:
                    total_tables = len(tables_to_sync)
                    for index, table_name in enumerate(tables_to_sync, 1):
                        # 更新进度
                        if task_id:
                            backup_status.update_task(
                                task_id,
                                current_table=table_name,
                                completed_tables=index-1
                            )
                            logger.info(f"更新备份进度: {table_name} ({index-1}/{total_tables})")

                        # 检查超时
                        if time.time() - start_time > max_duration:
                            self.log_sync_action("同步超时", "警告", f"已运行{max_duration}秒，停止同步")
                            break
                        try:
                            self.log_sync_action(f"同步表 {table_name} ({index}/{total_tables})", "开始")

                            # 检查表是否存在（兼容SQLite/PostgreSQL）
                            primary_exists = self._table_exists(primary_conn, table_name)
                            backup_exists = self._table_exists(backup_conn, table_name)

                            if not primary_exists:
                                self.log_sync_action(f"跳过表 {table_name}", "跳过", "主数据库中不存在")
                                continue

                            if not backup_exists:
                                self.log_sync_action(f"跳过表 {table_name}", "跳过", "备份数据库中不存在")
                                continue

                            # 清空备份表（根据方言选择策略）
                            try:
                                dialect_name = getattr(backup_conn, 'dialect', None).name if hasattr(backup_conn, 'dialect') else ''
                            except Exception:
                                dialect_name = ''

                            if dialect_name == 'sqlite':
                                # SQLite 不支持 TRUNCATE，直接使用 DELETE
                                backup_conn.execute(text(f'DELETE FROM "{table_name}"'))
                            else:
                                # 非SQLite优先尝试TRUNCATE，失败回退DELETE
                                try:
                                    backup_conn.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
                                except Exception as truncate_error:
                                    self.log_sync_action(f"TRUNCATE {table_name} 失败，尝试DELETE", "警告", str(truncate_error))
                                    backup_conn.execute(text(f'DELETE FROM "{table_name}"'))

                            # 获取主表数据
                            result = primary_conn.execute(text(f'SELECT * FROM "{table_name}"'))
                            rows = result.fetchall()

                            if rows:
                                # 获取列名
                                columns = result.keys()
                                column_names = ', '.join([f'"{col}"' for col in columns])

                                # 使用更高效的批量插入 - 简化版本
                                # 直接使用批量插入，避免COPY的复杂性
                                self._batch_insert_fallback(backup_conn, table_name, columns, column_names, rows)

                            synced_tables += 1
                            total_rows += len(rows)
                            self.log_sync_action(f"同步表 {table_name}", "成功", f"{len(rows)} 行数据")

                        except Exception as e:
                            self.log_sync_action(f"同步表 {table_name}", "失败", str(e))
                            # 记录错误但继续处理其他表
                            continue

                    # 重新启用外键约束检查
                    try:
                        if 'postgresql' in self.dual_db.backup_db_url:
                            backup_conn.execute(text('SET session_replication_role = DEFAULT'))
                            self.log_sync_action("恢复外键约束", "成功", "重新启用外键约束检查")
                    except Exception as e:
                        self.log_sync_action("恢复外键约束", "警告", f"无法恢复外键约束: {str(e)}")

                except Exception as e:
                    # 确保恢复外键约束
                    try:
                        if 'postgresql' in self.dual_db.backup_db_url:
                            backup_conn.execute(text('SET session_replication_role = DEFAULT'))
                    except:
                        pass

                    self.log_sync_action("数据库同步", "失败", f"同步过程失败: {str(e)}")
                    synced_tables = 0  # 确保返回失败状态

            # 更新最终进度
            if task_id:
                backup_status.update_task(
                    task_id,
                    completed_tables=len(tables_to_sync),
                    total_rows=total_rows
                )

            if synced_tables > 0:
                self.log_sync_action("备份到ClawCloud", "成功",
                                   f"同步了 {synced_tables} 个表，共 {total_rows} 行数据")
                return True
            else:
                self.log_sync_action("备份到ClawCloud", "失败",
                                   "没有成功同步任何表，请检查数据库连接和权限")
                return False

        except Exception as e:
            self.log_sync_action("备份到ClawCloud", "失败", str(e))
            logger.error(f"备份失败: {e}")
            return False
    
    def restore_from_clawcloud(self):
        """从ClawCloud恢复到主数据库 - 紧急禁用版本"""
        self.log_sync_action("从ClawCloud恢复", "失败", "恢复功能已紧急禁用，防止数据丢失")
        logger.error("恢复功能已紧急禁用：TRUNCATE CASCADE操作过于危险")
        return False

        # 原始代码已注释，防止意外执行
        # 危险代码已注释 - TRUNCATE CASCADE会清空所有数据
        # 原始恢复代码已被注释，因为使用了危险的TRUNCATE CASCADE操作
        """
        if not self.dual_db.is_dual_db_enabled():
            self.log_sync_action("从ClawCloud恢复", "失败", "双数据库未配置")
            return False

        try:
            self.log_sync_action("开始恢复", "进行中", "连接数据库")

            # 测试数据库连接
            try:
                from sqlalchemy import create_engine, text
                primary_connect_args = {'connect_timeout': 10} if 'postgresql' in self.dual_db.primary_db_url else {}
                backup_connect_args = {'connect_timeout': 10} if 'postgresql' in self.dual_db.backup_db_url else {}
                primary_engine = create_engine(self.dual_db.primary_db_url, connect_args=primary_connect_args)
                backup_engine = create_engine(self.dual_db.backup_db_url, connect_args=backup_connect_args)

                # 测试连接
                with primary_engine.connect() as conn:
                    conn.execute(text('SELECT 1'))
                with backup_engine.connect() as conn:
                    conn.execute(text('SELECT 1'))

                self.log_sync_action("数据库连接", "成功", "主数据库和备份数据库连接正常")

            except Exception as e:
                self.log_sync_action("数据库连接", "失败", f"连接错误: {str(e)}")
                return False

            # 获取要恢复的表（正确的依赖顺序）
            tables_to_restore = [
                # 第一阶段：基础表（无外键依赖）
                'roles', 'tags',
                # 第二阶段：用户和活动表
                'users', 'activities',
                # 第三阶段：关联表（有外键依赖）
                'activity_tags', 'user_tags', 'system_logs',
                # 第四阶段：会话和消息表
                'ai_chat_session', 'ai_chat_message',
                # 第五阶段：其他依赖表
                'activity_registrations', 'checkin_records', 'messages', 'notifications'
            ]

            restored_tables = 0
            total_rows = 0

            with backup_engine.connect() as backup_conn, primary_engine.connect() as primary_conn:
                for table_name in tables_to_restore:
                    try:
                        self.log_sync_action(f"恢复表 {table_name}", "开始")

                        # 检查表是否存在（跨数据库兼容）
                        backup_exists = self._table_exists(backup_conn, table_name)
                        primary_exists = self._table_exists(primary_conn, table_name)

                        if not backup_exists:
                            self.log_sync_action(f"跳过表 {table_name}", "跳过", "备份数据库中不存在")
                            continue

                        if not primary_exists:
                            self.log_sync_action(f"跳过表 {table_name}", "跳过", "主数据库中不存在")
                            continue

                        # 清空主表（使用方言感知策略）
                        try:
                            dialect_name = getattr(getattr(primary_conn, 'dialect', None), 'name', '')
                            if dialect_name == 'sqlite':
                                primary_conn.execute(text(f'DELETE FROM "{table_name}"'))
                            else:
                                try:
                                    primary_conn.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
                                except Exception as truncate_error:
                                    self.log_sync_action(f"TRUNCATE {table_name} 失败，尝试DELETE", "警告", str(truncate_error))
                                    primary_conn.execute(text(f'DELETE FROM "{table_name}"'))
                            primary_conn.commit()
                        except Exception as clear_err:
                            self.log_sync_action(f"清空 {table_name}", "失败", str(clear_err))
                            try:
                                primary_conn.rollback()
                            except Exception:
                                pass
                            continue

                        # 获取备份表数据
                        result = backup_conn.execute(text(f'SELECT * FROM "{table_name}"'))
                        rows = result.fetchall()

                        if rows:
                            # 获取列名
                            columns = result.keys()
                            column_names = ', '.join([f'"{col}"' for col in columns])

                            # 使用批量插入优化恢复性能
                            self._batch_insert_fallback(primary_conn, table_name, columns, column_names, rows)

                        primary_conn.commit()
                        restored_tables += 1
                        total_rows += len(rows)
                        self.log_sync_action(f"恢复表 {table_name}", "成功", f"{len(rows)} 行数据")

                    except Exception as e:
                        self.log_sync_action(f"恢复表 {table_name}", "失败", str(e))
                        # 出错后回滚以清除事务错误状态，避免后续命令被忽略
                        try:
                            primary_conn.rollback()
                        except Exception:
                            pass
                        try:
                            backup_conn.rollback()
                        except Exception:
                            pass
                        # 继续处理下一个表，不中断整个过程
                        continue

            if restored_tables > 0:
                self.log_sync_action("从ClawCloud恢复", "成功",
                                   f"恢复了 {restored_tables} 个表，共 {total_rows} 行数据")
                return True
            else:
                self.log_sync_action("从ClawCloud恢复", "失败",
                                   "没有成功恢复任何表，请检查数据库连接和权限")
                return False

        except Exception as e:
            self.log_sync_action("从ClawCloud恢复", "失败", str(e))
            logger.error(f"恢复失败: {e}")
            return False
        """

    def safe_restore_from_clawcloud(self, force_full_restore=False):
        """智能一键恢复 - 改进版本2025-08-26
        
        Args:
            force_full_restore (bool): 强制执行完整恢复，忽略数据库状态检测
        """
        # 放宽双数据库检查 - 只要有备份数据库就可以恢复
        if not self.dual_db.backup_db_url:
            self.log_sync_action("智能恢复", "失败", "备份数据库未配置")
            return False
            
        if not self.dual_db.primary_db_url:
            self.log_sync_action("智能恢复", "失败", "主数据库未配置")
            return False

        try:
            import time
            start_time = time.time()
            max_duration = 300  # 增加到5分钟执行时间

            if force_full_restore:
                self.log_sync_action("开始强制完整恢复", "进行中", "Render数据库重置后完整恢复模式")
            else:
                self.log_sync_action("开始智能恢复", "进行中", "智能检测数据库状态")

            # 测试数据库连接
            from sqlalchemy import create_engine, text
            
            # 根据数据库类型设置连接参数
            primary_connect_args = {'connect_timeout': 15} if 'postgresql' in self.dual_db.primary_db_url else {}
            backup_connect_args = {'connect_timeout': 15} if 'postgresql' in self.dual_db.backup_db_url else {}
            
            primary_engine = create_engine(self.dual_db.primary_db_url, connect_args=primary_connect_args)
            backup_engine = create_engine(self.dual_db.backup_db_url, connect_args=backup_connect_args)

            # 测试连接
            with primary_engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            with backup_engine.connect() as conn:
                conn.execute(text('SELECT 1'))

            self.log_sync_action("数据库连接", "成功", "主数据库和备份数据库连接正常")

            # 智能迁移策略
            restored_tables = 0
            total_rows = 0

            with backup_engine.connect() as backup_conn, primary_engine.connect() as primary_conn:
                if force_full_restore:
                    self.log_sync_action("恢复策略", "强制完整", "执行强制完整恢复，适用于Render数据库重置")
                    success, rows = self._perform_full_migration(backup_conn, primary_conn, start_time, max_duration)
                    restored_tables = success
                    total_rows = rows
                else:
                    # 检测数据库状态
                    is_new_deployment = self._check_if_new_deployment(primary_conn)

                    if is_new_deployment:
                        self.log_sync_action("数据库检测", "新部署", "检测到新部署数据库，使用完整迁移策略")
                        success, rows = self._perform_full_migration(backup_conn, primary_conn, start_time, max_duration)
                        restored_tables = success
                        total_rows = rows
                    else:
                        self.log_sync_action("数据库检测", "有数据", "检测到有业务数据，使用安全同步策略")
                        success, rows = self._perform_incremental_sync(backup_conn, primary_conn, start_time, max_duration)
                        restored_tables = success
                        total_rows = rows

            if restored_tables > 0:
                recovery_type = "强制完整恢复" if force_full_restore else "智能恢复"
                self.log_sync_action(recovery_type, "成功",
                                   f"恢复了 {restored_tables} 个表，共 {total_rows} 行数据")
                return True
            else:
                recovery_type = "强制完整恢复" if force_full_restore else "智能恢复"
                self.log_sync_action(recovery_type, "失败", "没有成功恢复任何表")
                return False

        except Exception as e:
            recovery_type = "强制完整恢复" if force_full_restore else "智能恢复"
            self.log_sync_action(recovery_type, "失败", str(e))
            logger.error(f"{recovery_type}失败: {e}")
            return False

    def _restore_table_safe(self, backup_conn, primary_conn, table_name, start_time, max_duration):
        """安全恢复表（使用UPSERT）"""
        try:
            import time
            if time.time() - start_time > max_duration:
                return False, 0

            self.log_sync_action(f"安全恢复 {table_name}", "开始")

            # 检查表是否存在
            if not backup_conn.execute(check_sql).scalar() or not primary_conn.execute(check_sql).scalar():
                self.log_sync_action(f"跳过 {table_name}", "跳过", "表不存在")
                return False, 0

            # 获取备份数据
            backup_result = backup_conn.execute(text(f'SELECT * FROM "{table_name}"'))
            backup_rows = backup_result.fetchall()

            if not backup_rows:
                self.log_sync_action(f"跳过 {table_name}", "跳过", "备份数据为空")
                return False, 0

            # 使用UPSERT策略
            for row in backup_rows:
                if table_name == 'tags':
                    upsert_sql = text('''
                        INSERT INTO "tags" (id, name, color)
                        VALUES (:id, :name, :color)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            color = EXCLUDED.color
                    ''')
                    primary_conn.execute(upsert_sql, {
                        'id': row[0],
                        'name': row[1],
                        'color': row[2] if len(row) > 2 else None
                    })

            primary_conn.commit()
            self.log_sync_action(f"安全恢复 {table_name}", "成功", f"更新了 {len(backup_rows)} 行数据")
            return True, len(backup_rows)

        except Exception as e:
            self.log_sync_action(f"安全恢复 {table_name}", "失败", str(e))
            return False, 0

    def _restore_table_with_constraints(self, backup_conn, primary_conn, table_name, start_time, max_duration):
        """智能恢复有外键约束的表"""
        try:
            import time
            if time.time() - start_time > max_duration:
                return False, 0

            self.log_sync_action(f"智能恢复 {table_name}", "开始")

            # 检查表是否存在
            if not backup_conn.execute(check_sql).scalar() or not primary_conn.execute(check_sql).scalar():
                self.log_sync_action(f"跳过 {table_name}", "跳过", "表不存在")
                return False, 0

            if table_name == 'roles':
                # 检查是否有用户引用
                user_count = primary_conn.execute(text('SELECT COUNT(*) FROM users')).scalar()

                if user_count > 0:
                    # 有用户存在，使用UPSERT更新角色
                    backup_roles = backup_conn.execute(text('SELECT * FROM "roles"')).fetchall()

                    for role_row in backup_roles:
                        upsert_sql = text('''
                            INSERT INTO "roles" (id, name, description)
                            VALUES (:id, :name, :description)
                            ON CONFLICT (id) DO UPDATE SET
                                name = EXCLUDED.name,
                                description = EXCLUDED.description
                        ''')
                        primary_conn.execute(upsert_sql, {
                            'id': role_row[0],
                            'name': role_row[1],
                            'description': role_row[2] if len(role_row) > 2 else None
                        })

                    primary_conn.commit()
                    self.log_sync_action(f"智能恢复 {table_name}", "成功", f"更新了 {len(backup_roles)} 行角色数据")
                    return True, len(backup_roles)
                else:
                    # 没有用户，可以安全重建
                    primary_conn.execute(text(f'DELETE FROM "{table_name}"'))

                    backup_roles = backup_conn.execute(text('SELECT * FROM "roles"')).fetchall()
                    for role_row in backup_roles:
                        insert_sql = text('INSERT INTO "roles" (id, name, description) VALUES (:id, :name, :description)')
                        primary_conn.execute(insert_sql, {
                            'id': role_row[0],
                            'name': role_row[1],
                            'description': role_row[2] if len(role_row) > 2 else None
                        })

                    primary_conn.commit()
                    self.log_sync_action(f"智能恢复 {table_name}", "成功", f"重建了 {len(backup_roles)} 行角色数据")
                    return True, len(backup_roles)

        except Exception as e:
            self.log_sync_action(f"智能恢复 {table_name}", "失败", str(e))
            return False, 0

    def _restore_table_additive(self, backup_conn, primary_conn, table_name, start_time, max_duration):
        """增量恢复表（只添加不存在的数据）"""
        try:
            import time
            if time.time() - start_time > max_duration:
                return False, 0

            self.log_sync_action(f"增量恢复 {table_name}", "开始")

            # 检查表是否存在
            if not backup_conn.execute(check_sql).scalar() or not primary_conn.execute(check_sql).scalar():
                self.log_sync_action(f"跳过 {table_name}", "跳过", "表不存在")
                return False, 0

            if table_name == 'activities':
                # 获取现有活动ID
                existing_ids = set()
                existing_result = primary_conn.execute(text('SELECT id FROM activities'))
                for row in existing_result:
                    existing_ids.add(row[0])

                # 获取备份活动
                backup_activities = backup_conn.execute(text('SELECT * FROM "activities"')).fetchall()
                new_activities = 0

                for activity_row in backup_activities:
                    activity_id = activity_row[0]
                    if activity_id not in existing_ids:
                        # 只添加不存在的活动
                        columns = ['id', 'title', 'description', 'start_time', 'end_time', 'location', 'max_participants', 'created_by', 'created_at', 'updated_at', 'poster_data']
                        placeholders = ', '.join([f':{col}' for col in columns])
                        insert_sql = text(f'INSERT INTO "activities" ({", ".join(columns)}) VALUES ({placeholders})')

                        params = {}
                        for i, col in enumerate(columns):
                            params[col] = activity_row[i] if i < len(activity_row) else None

                        primary_conn.execute(insert_sql, params)
                        new_activities += 1

                primary_conn.commit()
                self.log_sync_action(f"增量恢复 {table_name}", "成功", f"添加了 {new_activities} 个新活动")
                return True, new_activities

        except Exception as e:
            self.log_sync_action(f"增量恢复 {table_name}", "失败", str(e))
            return False, 0

    def _restore_table_full(self, backup_conn, primary_conn, table_name, start_time, max_duration):
        """完整恢复表（用于核心业务数据）"""
        try:
            import time
            if time.time() - start_time > max_duration:
                return False, 0

            self.log_sync_action(f"完整恢复 {table_name}", "开始")

            # 检查表是否存在（跨数据库兼容）
            backup_exists = self._table_exists(backup_conn, table_name)
            primary_exists = self._table_exists(primary_conn, table_name)
            if not backup_exists or not primary_exists:
                self.log_sync_action(f"跳过 {table_name}", "跳过", "表不存在")
                return False, 0

            # 获取备份数据
            backup_result = backup_conn.execute(text(f'SELECT * FROM "{table_name}"'))
            backup_rows = backup_result.fetchall()

            if not backup_rows:
                self.log_sync_action(f"跳过 {table_name}", "跳过", "备份数据为空")
                return False, 0

            # 获取列信息
            columns = backup_result.keys()

            # 清空现有数据（完整恢复）
            primary_conn.execute(text(f'DELETE FROM "{table_name}"'))

            # 批量插入备份数据
            for row in backup_rows:
                column_names = ', '.join([f'"{col}"' for col in columns])
                placeholders = ', '.join([f':{col}' for col in columns])
                insert_sql = text(f'INSERT INTO "{table_name}" ({column_names}) VALUES ({placeholders})')

                params = {}
                for i, col in enumerate(columns):
                    params[col] = row[i] if i < len(row) else None

                primary_conn.execute(insert_sql, params)

            primary_conn.commit()
            self.log_sync_action(f"完整恢复 {table_name}", "成功", f"恢复了 {len(backup_rows)} 行数据")
            return True, len(backup_rows)

        except Exception as e:
            self.log_sync_action(f"完整恢复 {table_name}", "失败", str(e))
            # 出错后回滚以清除事务错误状态，避免后续命令被忽略
            try:
                primary_conn.rollback()
            except Exception:
                pass
            try:
                backup_conn.rollback()
            except Exception:
                pass
            return False, 0

    def _check_if_new_deployment(self, primary_conn):
        """检测数据库是否需要完整迁移（考虑自动创建的管理员账号）"""
        try:
            from sqlalchemy import text

            # 检查业务数据表是否基本为空（允许有基础的管理员数据）

            # 1. 检查活动数据（最重要的业务指标）
            try:
                if self._table_exists(primary_conn, 'activities'):
                    count_sql = text('SELECT COUNT(*) FROM "activities"')
                    activities_count = primary_conn.execute(count_sql).scalar()

                    if activities_count > 0:
                        self.log_sync_action("业务数据检测", "发现", f"发现 {activities_count} 个活动，判断为有业务数据")
                        return False  # 有活动数据，不是新部署
            except Exception as e:
                self.log_sync_action("检测活动表", "警告", f"检测失败: {str(e)}")

            # 2. 检查用户数量（排除基础管理员）
            try:
                if self._table_exists(primary_conn, 'users'):
                    count_sql = text('SELECT COUNT(*) FROM "users"')
                    users_count = primary_conn.execute(count_sql).scalar()

                    # 如果用户数量 > 2（通常只有1-2个管理员），认为有业务数据
                    if users_count > 2:
                        self.log_sync_action("用户数据检测", "发现", f"发现 {users_count} 个用户，判断为有业务数据")
                        return False
                    else:
                        self.log_sync_action("用户数据检测", "基础", f"只有 {users_count} 个用户，可能是基础管理员")
            except Exception as e:
                self.log_sync_action("检测用户表", "警告", f"检测失败: {str(e)}")

            # 3. 检查其他业务表
            business_tables = ['registrations', 'checkin_records', 'activity_tags']
            has_business_data = False

            for table_name in business_tables:
                try:
                    if self._table_exists(primary_conn, table_name):
                        count_sql = text(f'SELECT COUNT(*) FROM "{table_name}"')
                        count = primary_conn.execute(count_sql).scalar()

                        if count > 0:
                            self.log_sync_action("业务数据检测", "发现", f"{table_name}表有 {count} 条记录")
                            has_business_data = True
                            break
                except Exception as e:
                    continue

            if has_business_data:
                return False

            # 如果没有活动、业务用户很少、没有业务关联数据，认为是新部署
            self.log_sync_action("数据库状态", "判断", "判断为新部署数据库，适合完整迁移")
            return True

        except Exception as e:
            self.log_sync_action("数据库检测", "失败", f"检测失败: {e}")
            return False  # 出错时假设不是新部署，使用安全策略

    def force_full_restore_from_clawcloud(self):
        """强制完整恢复 - 专为Render数据库重置设计"""
        return self.safe_restore_from_clawcloud(force_full_restore=True)

    def _perform_full_migration(self, backup_conn, primary_conn, start_time, max_duration):
        """执行完整迁移（适用于Render数据库重置后的完整恢复）"""
        try:
            import time
            from sqlalchemy import text

            # 完整的表迁移计划 - 按依赖顺序排列
            migration_plan = [
                # 第一阶段：基础配置表（无外键依赖）
                ('roles', 'upsert'),           # 角色：可能已存在Admin等，用UPSERT
                ('tags', 'clear_insert'),      # 标签：清空后插入
                
                # 第二阶段：用户表（智能处理）
                ('users', 'smart'),            # 用户：智能处理，避免管理员冲突
                
                # 第三阶段：业务核心表
                ('activities', 'clear_insert'), # 活动：清空后插入
                
                # 第四阶段：关联表（有外键依赖）
                ('activity_tags', 'clear_insert'),     # 活动标签关联
                ('user_tags', 'clear_insert'),         # 用户标签关联
                ('registrations', 'clear_insert'),     # 活动报名
                ('checkin_records', 'clear_insert'),   # 签到记录
                
                # 第五阶段：系统表
                ('system_logs', 'append'),             # 系统日志：追加模式
                ('ai_chat_session', 'clear_insert'),   # AI聊天会话
                ('ai_chat_message', 'clear_insert'),   # AI聊天消息
                ('ai_user_preferences', 'clear_insert'), # AI用户偏好
                
                # 第六阶段：其他业务表
                ('messages', 'clear_insert'),          # 消息
                ('notifications', 'clear_insert'),     # 通知
                ('notification_read', 'clear_insert'), # 通知已读
                ('student_info', 'clear_insert'),      # 学生信息
                ('student_tags', 'clear_insert'),      # 学生标签
                ('points_history', 'clear_insert'),    # 积分历史
                ('announcements', 'clear_insert'),     # 公告
            ]

            restored_count = 0
            total_rows = 0

            # 临时禁用外键约束检查
            try:
                if 'postgresql' in self.dual_db.primary_db_url:
                    primary_conn.execute(text('SET session_replication_role = replica'))
                    self.log_sync_action("外键约束", "禁用", "临时禁用外键约束检查")
            except Exception as e:
                self.log_sync_action("外键约束", "警告", f"无法禁用外键约束: {str(e)}")
            try:
                for table_name, strategy in migration_plan:
                    if time.time() - start_time > max_duration:
                        self.log_sync_action("迁移超时", "警告", f"已运行{max_duration}秒，停止迁移")
                        break

                    try:
                        # 检查表是否存在（跨数据库兼容）
                        backup_exists = self._table_exists(backup_conn, table_name)
                        primary_exists = self._table_exists(primary_conn, table_name)

                        if not backup_exists:
                            self.log_sync_action(f"跳过 {table_name}", "跳过", "备份数据库中表不存在")
                            continue
                            
                        if not primary_exists:
                            self.log_sync_action(f"跳过 {table_name}", "跳过", "主数据库中表不存在")
                            continue

                        # 获取备份数据
                        backup_result = backup_conn.execute(text(f'SELECT * FROM "{table_name}"'))
                        backup_rows = backup_result.fetchall()

                        if not backup_rows:
                            self.log_sync_action(f"跳过 {table_name}", "跳过", "备份数据为空")
                            continue

                        # 根据策略执行迁移
                        if strategy == 'upsert':
                            success, rows = self._migrate_table_upsert(primary_conn, table_name, backup_rows, backup_result.keys())
                        elif strategy == 'smart':
                            success, rows = self._migrate_users_smart(primary_conn, backup_conn, backup_rows, backup_result.keys())
                        elif strategy == 'clear_insert':
                            success, rows = self._migrate_table_clear_insert(primary_conn, table_name, backup_rows, backup_result.keys())
                        elif strategy == 'append':
                            success, rows = self._migrate_table_append(primary_conn, table_name, backup_rows, backup_result.keys())
                        else:  # insert
                            success, rows = self._migrate_table_insert(primary_conn, table_name, backup_rows, backup_result.keys())

                        if success:
                            restored_count += 1
                            total_rows += rows
                            self.log_sync_action(f"完整迁移 {table_name}", "成功", f"迁移了 {rows} 行数据")
                        else:
                            self.log_sync_action(f"完整迁移 {table_name}", "失败", "迁移失败")

                    except Exception as e:
                        self.log_sync_action(f"完整迁移 {table_name}", "失败", str(e))
                        # 出错后回滚以清除事务错误状态，避免后续命令被忽略
                        try:
                            primary_conn.rollback()
                        except Exception:
                            pass
                        try:
                            backup_conn.rollback()
                        except Exception:
                            pass
                        # 继续处理下一个表，不中断整个过程
                        continue

            finally:
                # 重新启用外键约束检查
                try:
                    if 'postgresql' in self.dual_db.primary_db_url:
                        primary_conn.execute(text('SET session_replication_role = DEFAULT'))
                        self.log_sync_action("外键约束", "恢复", "重新启用外键约束检查")
                except Exception as e:
                    self.log_sync_action("外键约束", "警告", f"无法恢复外键约束: {str(e)}")
                    try:
                        primary_conn.rollback()
                    except Exception:
                        pass

            return restored_count, total_rows

        except Exception as e:
            self.log_sync_action("完整迁移", "失败", str(e))
            return 0, 0

    def _migrate_table_upsert(self, primary_conn, table_name, backup_rows, columns):
        """使用UPSERT策略迁移表"""
        try:
            from sqlalchemy import text

            for row in backup_rows:
                if table_name == 'roles':
                    upsert_sql = text('''
                        INSERT INTO "roles" (id, name, description)
                        VALUES (:id, :name, :description)
                        ON CONFLICT (id) DO UPDATE SET
                            name = EXCLUDED.name,
                            description = EXCLUDED.description
                    ''')
                    primary_conn.execute(upsert_sql, {
                        'id': row[0],
                        'name': row[1],
                        'description': row[2] if len(row) > 2 else None
                    })

            primary_conn.commit()
            return True, len(backup_rows)

        except Exception as e:
            self.log_sync_action(f"UPSERT迁移 {table_name}", "失败", str(e))
            return False, 0

    def _migrate_users_smart(self, primary_conn, backup_conn, backup_rows, columns):
        """智能迁移用户数据，避免管理员冲突"""
        try:
            from sqlalchemy import text

            # 获取现有用户的用户名
            existing_usernames = set()
            existing_result = primary_conn.execute(text('SELECT username FROM users'))
            for row in existing_result:
                existing_usernames.add(row[0])

            migrated_count = 0

            for row in backup_rows:
                username = row[1] if len(row) > 1 else None  # 假设username是第二列

                if username and username not in existing_usernames:
                    # 只迁移不存在的用户
                    column_names = ', '.join([f'"{col}"' for col in columns])
                    placeholders = ', '.join([f':{col}' for col in columns])
                    insert_sql = text(f'INSERT INTO "users" ({column_names}) VALUES ({placeholders})')

                    params = {}
                    for i, col in enumerate(columns):
                        params[col] = row[i] if i < len(row) else None

                    primary_conn.execute(insert_sql, params)
                    migrated_count += 1
                else:
                    self.log_sync_action("跳过用户", "跳过", f"用户 {username} 已存在")

            primary_conn.commit()
            return True, migrated_count

        except Exception as e:
            self.log_sync_action("智能用户迁移", "失败", str(e))
            return False, 0

    def _migrate_table_insert(self, primary_conn, table_name, backup_rows, columns):
        """使用INSERT策略迁移表"""
        try:
            from sqlalchemy import text

            for row in backup_rows:
                column_names = ', '.join([f'"{col}"' for col in columns])
                placeholders = ', '.join([f':{col}' for col in columns])
                insert_sql = text(f'INSERT INTO "{table_name}" ({column_names}) VALUES ({placeholders})')

                params = {}
                for i, col in enumerate(columns):
                    params[col] = row[i] if i < len(row) else None

                primary_conn.execute(insert_sql, params)

            primary_conn.commit()
            return True, len(backup_rows)

        except Exception as e:
            self.log_sync_action(f"INSERT迁移 {table_name}", "失败", str(e))
            return False, 0
    
    def _migrate_table_clear_insert(self, primary_conn, table_name, backup_rows, columns):
        """清空表后插入数据（适用于完整恢复）"""
        try:
            from sqlalchemy import text
            
            # 先清空表
            primary_conn.execute(text(f'DELETE FROM "{table_name}"'))
            
            # 重置自增序列（如果存在）
            try:
                primary_conn.execute(text(f'ALTER SEQUENCE IF EXISTS {table_name}_id_seq RESTART WITH 1'))
            except:
                pass  # 忽略序列不存在的错误
            
            # 批量插入数据
            for row in backup_rows:
                column_names = ', '.join([f'"{col}"' for col in columns])
                placeholders = ', '.join([f':{col}' for col in columns])
                insert_sql = text(f'INSERT INTO "{table_name}" ({column_names}) VALUES ({placeholders})')

                params = {}
                for i, col in enumerate(columns):
                    params[col] = row[i] if i < len(row) else None

                primary_conn.execute(insert_sql, params)
            
            primary_conn.commit()
            return True, len(backup_rows)
            
        except Exception as e:
            primary_conn.rollback()
            self.log_sync_action(f"清空插入迁移 {table_name}", "失败", str(e))
            return False, 0
    
    def _migrate_table_append(self, primary_conn, table_name, backup_rows, columns):
        """追加模式迁移（适用于日志表等）"""
        try:
            from sqlalchemy import text
            
            # 获取主表现有的最大ID（如果有ID列）
            max_id = 0
            try:
                result = primary_conn.execute(text(f'SELECT COALESCE(MAX(id), 0) FROM "{table_name}"'))
                max_id = result.scalar() or 0
            except:
                pass  # 忽略没有ID列的情况
            
            # 插入数据，调整ID避免冲突
            inserted_count = 0
            for row in backup_rows:
                column_names = ', '.join([f'"{col}"' for col in columns])
                placeholders = ', '.join([f':{col}' for col in columns])
                insert_sql = text(f'INSERT INTO "{table_name}" ({column_names}) VALUES ({placeholders})')

                params = {}
                for i, col in enumerate(columns):
                    value = row[i] if i < len(row) else None
                    # 如果是ID列且值可能冲突，则调整
                    if col == 'id' and value and value <= max_id:
                        value = max_id + inserted_count + 1
                    params[col] = value

                try:
                    primary_conn.execute(insert_sql, params)
                    inserted_count += 1
                except Exception as row_error:
                    # 跳过重复或冲突的记录
                    self.log_sync_action(f"跳过 {table_name} 重复记录", "警告", str(row_error))
                    continue
            
            primary_conn.commit()
            return True, inserted_count
            
        except Exception as e:
            primary_conn.rollback()
            self.log_sync_action(f"追加迁移 {table_name}", "失败", str(e))
            return False, 0

    def _perform_incremental_sync(self, backup_conn, primary_conn, start_time, max_duration):
        """执行增量同步（适用于有数据的数据库）"""
        try:
            import time

            # 只同步安全的配置数据
            safe_tables = ['roles', 'tags']

            restored_count = 0
            total_rows = 0

            for table_name in safe_tables:
                if time.time() - start_time > max_duration:
                    break

                success, rows = self._restore_table_safe(backup_conn, primary_conn, table_name, start_time, max_duration)
                if success:
                    restored_count += 1
                    total_rows += rows

            return restored_count, total_rows

        except Exception as e:
            self.log_sync_action("增量同步", "失败", str(e))
            return 0, 0

    def _batch_insert_fallback(self, conn, table_name, columns, column_names, rows):
        """批量插入的优化方法"""
        if not rows:
            return

        # 根据数据量调整批次大小
        if len(rows) > 1000:
            batch_size = 1000  # 大数据集使用更大批次
        else:
            batch_size = len(rows)  # 小数据集一次性插入

        total_batches = (len(rows) + batch_size - 1) // batch_size

        for batch_num, i in enumerate(range(0, len(rows), batch_size), 1):
            batch_rows = rows[i:i + batch_size]

            try:
                # 使用executemany进行批量插入
                placeholders = ', '.join([f':{col}' for col in columns])
                insert_sql = f'INSERT INTO "{table_name}" ({column_names}) VALUES ({placeholders})'

                # 准备批量参数
                batch_params = []
                for row in batch_rows:
                    params = {col: row[j] for j, col in enumerate(columns)}
                    batch_params.append(params)

                # 执行批量插入
                conn.execute(text(insert_sql), batch_params)

                # 只在最后一批或每10批提交一次，减少提交频率
                if batch_num == total_batches or batch_num % 10 == 0:
                    conn.commit()

            except Exception as e:
                # 批量插入失败时，尝试逐行插入
                self.log_sync_action(f"批量插入 {table_name} 失败，尝试逐行插入", "警告", str(e))
                for row in batch_rows:
                    try:
                        params = {col: row[j] for j, col in enumerate(columns)}
                        conn.execute(text(insert_sql), params)
                    except Exception as row_error:
                        self.log_sync_action(f"跳过 {table_name} 中的问题行", "警告", str(row_error))
                        continue
                conn.commit()

    def get_sync_log(self):
        """获取同步日志"""
        return self.sync_log
    
    def save_sync_log(self, filename=None):
        """保存同步日志到文件"""
        if not filename:
            filename = f"sync_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(self.sync_log, f, ensure_ascii=False, indent=2)
            return filename
        except Exception as e:
            logger.error(f"保存同步日志失败: {e}")
            return None

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='数据库同步工具')
    parser.add_argument('action', choices=['backup', 'restore', 'test'], 
                       help='操作类型: backup(备份到ClawCloud), restore(从ClawCloud恢复), test(测试连接)')
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    syncer = DatabaseSyncer()
    
    if args.action == 'test':
        print("测试数据库连接...")
        info = dual_db.get_database_info()
        print(json.dumps(info, indent=2, ensure_ascii=False))
    
    elif args.action == 'backup':
        print("开始备份到ClawCloud...")
        success = syncer.backup_to_clawcloud()
        if success:
            print("备份成功完成!")
        else:
            print("备份失败!")
            sys.exit(1)
    
    elif args.action == 'restore':
        print("开始从ClawCloud恢复...")
        success = syncer.restore_from_clawcloud()
        if success:
            print("恢复成功完成!")
        else:
            print("恢复失败!")
            sys.exit(1)
    
    # 保存同步日志
    log_file = syncer.save_sync_log()
    if log_file:
        print(f"同步日志已保存到: {log_file}")

if __name__ == '__main__':
    main()
