# 工具函数包 
import json
import uuid
from datetime import datetime
from flask import current_app
import logging
import os
import time
import pytz
from functools import wraps
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

def generate_session_id():
    """生成唯一的会话ID"""
    timestamp = int(datetime.now().timestamp() * 1000)
    random_str = uuid.uuid4().hex[:12]
    return f"session_{timestamp}_{random_str}"

def create_ai_chat_session(db, user_id):
    """创建新的AI聊天会话"""
    from src.models import AIChatSession
    
    session_id = generate_session_id()
    session = AIChatSession(
        id=session_id,
        user_id=user_id
    )
    
    try:
        db.session.add(session)
        db.session.commit()
        return session
    except Exception as e:
        current_app.logger.error(f"创建AI聊天会话失败: {str(e)}")
        db.session.rollback()
        return None

def save_chat_message(db, user_id, session_id, role, content):
    """保存聊天消息到数据库"""
    from src.models import AIChatHistory
    
    try:
        message = AIChatHistory(
            user_id=user_id,
            session_id=session_id,
            role=role,
            content=content
        )
        db.session.add(message)
        db.session.commit()
        return message
    except Exception as e:
        current_app.logger.error(f"保存聊天消息失败: {str(e)}")
        db.session.rollback()
        return None

def get_compatible_paginate(db, query, page, per_page, max_per_page=None, error_out=True):
    """
    创建一个与SQLAlchemy版本兼容的分页函数
    
    Args:
        db: SQLAlchemy数据库对象
        query: 查询对象
        page: 页码
        per_page: 每页项目数
        max_per_page: 每页最大项目数
        error_out: 是否在页码无效时引发404错误
        
    Returns:
        分页对象
    """
    try:
        # 尝试使用新版本SQLAlchemy 2.0的分页语法
        if hasattr(db, 'paginate'):
            # SQLAlchemy 2.0
            return db.paginate(
                query, 
                page=page, 
                per_page=per_page,
                max_per_page=max_per_page,
                error_out=error_out
            )
        else:
            # 旧版本SQLAlchemy
            return query.paginate(
                page=page, 
                per_page=per_page, 
                max_per_page=max_per_page,
                error_out=error_out
            )
    except Exception as e:
        logging.error(f"分页错误: {e}")
        # 如果出现异常，尝试使用更基本的分页方法
        try:
            items = query.limit(per_page).offset((page - 1) * per_page).all()
            
            # 创建一个简单的分页对象
            class SimplePagination:
                def __init__(self, items, page, per_page, total):
                    self.items = items
                    self.page = page
                    self.per_page = per_page
                    self.total = total
                    self.pages = (total + per_page - 1) // per_page
                
                @property
                def has_next(self):
                    return self.page < self.pages
                
                @property
                def has_prev(self):
                    return self.page > 1
                
                @property
                def next_num(self):
                    return self.page + 1 if self.has_next else None
                
                @property
                def prev_num(self):
                    return self.page - 1 if self.has_prev else None
                
                def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
                    last = 0
                    for num in range(1, self.pages + 1):
                        if (num <= left_edge or
                            (self.page - left_current - 1 < num < self.page + right_current) or
                            num > self.pages - right_edge):
                            if last + 1 != num:
                                yield None
                            yield num
                            last = num
            
            # 计算总数
            total = query.count()
            
            return SimplePagination(items, page, per_page, total)
        except Exception as nested_e:
            logging.error(f"备用分页方法也失败: {nested_e}")
            # 返回一个最基本的分页对象
            class EmptyPagination:
                def __init__(self):
                    self.items = []
                    self.page = page
                    self.per_page = per_page
                    self.total = 0
                    self.pages = 0
                    self.has_next = False
                    self.has_prev = False
                    self.next_num = None
                    self.prev_num = None
                
                def iter_pages(self, *args, **kwargs):
                    return []
            
            return EmptyPagination()

# 添加通用的数据库事务处理装饰器
def db_transaction(func):
    """
    装饰器：自动处理数据库事务，出错时回滚
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        from src import db
        try:
            result = func(*args, **kwargs)
            db.session.commit()
            return result
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"数据库事务错误: {str(e)}")
            raise
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"未知错误: {str(e)}")
            raise
    return wrapper 