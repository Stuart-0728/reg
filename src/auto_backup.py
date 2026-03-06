#!/usr/bin/env python3
"""
自动备份任务
每6小时自动执行数据库备份
"""

import os
import sys
import time
import threading
import schedule
from datetime import datetime

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db_sync import DatabaseSyncer
from utils.time_helpers import get_beijing_time
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('logs/auto_backup.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class AutoBackupService:
    def __init__(self):
        self.syncer = DatabaseSyncer()
        self.is_running = False
        
    def perform_backup(self):
        """执行自动备份"""
        try:
            beijing_time = get_beijing_time()
            logger.info(f"开始自动备份 - {beijing_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 执行备份
            success = self.syncer.backup_to_clawcloud()
            
            if success:
                logger.info("自动备份成功完成")
            else:
                logger.error("自动备份失败")
                
        except Exception as e:
            logger.error(f"自动备份异常: {e}")
    
    def start_scheduler(self):
        """启动定时任务"""
        if self.is_running:
            logger.warning("自动备份服务已在运行")
            return
            
        self.is_running = True
        logger.info("启动自动备份服务")
        
        # 设置定时任务：每6小时执行一次
        schedule.every(6).hours.do(self.perform_backup)
        
        # 立即执行一次备份
        logger.info("执行初始备份")
        self.perform_backup()
        
        # 运行调度器
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
            except KeyboardInterrupt:
                logger.info("收到停止信号")
                break
            except Exception as e:
                logger.error(f"调度器异常: {e}")
                time.sleep(60)
    
    def stop_scheduler(self):
        """停止定时任务"""
        self.is_running = False
        logger.info("停止自动备份服务")

def start_auto_backup_thread():
    """在后台线程中启动自动备份"""
    backup_service = AutoBackupService()
    
    def run_backup():
        backup_service.start_scheduler()
    
    backup_thread = threading.Thread(target=run_backup, daemon=True)
    backup_thread.start()
    logger.info("自动备份线程已启动")
    
    return backup_service

if __name__ == "__main__":
    # 直接运行自动备份服务
    backup_service = AutoBackupService()
    try:
        backup_service.start_scheduler()
    except KeyboardInterrupt:
        backup_service.stop_scheduler()
        logger.info("自动备份服务已停止")
