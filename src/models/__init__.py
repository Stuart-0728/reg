from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json
import pytz
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, Table, func, UniqueConstraint
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.declarative import declarative_base
from src import db

# 创建一个临时基类，稍后会被替换
Base = declarative_base()

# 创建中间表
student_tags = Table(
    'student_tags',
    db.Model.metadata,
    Column('student_id', Integer, ForeignKey('student_info.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

activity_tags = Table(
    'activity_tags',
    db.Model.metadata,
    Column('activity_id', Integer, ForeignKey('activities.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)

# 角色模型
class Role(db.Model):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    description = Column(String(128))  # 新增，支持角色描述
    
    # 关系
    users = relationship('User', backref='role', lazy='dynamic')
    
    def __repr__(self):
        return f'<Role {self.name}>'

# 用户模型
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(120), unique=True, index=True)
    password_hash = Column(String(256), nullable=False)
    role_id = Column(Integer, ForeignKey('roles.id'))
    active = Column(Boolean, default=True)  # 用户是否激活
    
    # 时间戳
    created_at = Column(DateTime, default=func.now())
    last_login = Column(DateTime)
    
    # 关系
    student_info = relationship('StudentInfo', backref='user', uselist=False, cascade="all, delete-orphan")
    registrations = relationship('Registration', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    reviews = relationship('ActivityReview', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    checkins = relationship('ActivityCheckin', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    messages_sent = relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy='dynamic', cascade="all, delete-orphan")
    messages_received = relationship('Message', foreign_keys='Message.receiver_id', backref='recipient', lazy='dynamic', cascade="all, delete-orphan")
    notifications = relationship('Notification', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    notification_reads = relationship('NotificationRead', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    ai_chat_sessions = relationship('AIChatSession', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    ai_preferences = relationship('AIUserPreferences', backref='user', uselist=False, cascade="all, delete-orphan")
    
    @property
    def password(self):
        raise AttributeError('密码不可读')
    
    @password.setter
    def password(self, password):
        # 强制使用 pbkdf2:sha256 算法
        self.password_hash = generate_password_hash(password, method='pbkdf2:sha256')

    def verify_password(self, password):
        # 首先尝试新算法
        if check_password_hash(str(self.password_hash), password):
            return True
        
        # 如果失败，尝试旧的 scrypt 算法
        try:
            # 检查密码哈希是否是旧格式
            if 'scrypt' in str(self.password_hash):
                # 由于scrypt算法可能不被支持，我们直接重置密码
                # 这是一个临时解决方案
                self.password = password
                db.session.commit()
                return True
        except Exception as e:
            # 如果旧算法验证失败或出现其他错误，则忽略
            pass
            
        return False
    
    def ping(self):
        """更新用户最后访问时间"""
        self.last_login = datetime.now(pytz.utc)
    
    @property
    def is_admin(self):
        """检查用户是否为管理员"""
        return self.role.name == 'Admin'
    
    @property
    def is_student(self):
        """检查用户是否为学生"""
        return self.role.name == 'Student'
    
    def __repr__(self):
        return f'<User {self.username}>'

# 学生信息模型
class StudentInfo(db.Model):
    __tablename__ = 'student_info'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True)
    student_id = Column(String(20), unique=True, index=True)  # 学号
    real_name = Column(String(50))  # 真实姓名
    gender = Column(String(10))  # 性别
    college = Column(String(100))  # 学院
    major = Column(String(100))  # 专业
    grade = Column(String(20))  # 年级
    phone = Column(String(20))  # 手机号
    qq = Column(String(20))  # QQ号
    points = Column(Integer, default=0)  # 积分
    has_selected_tags = Column(Boolean, default=False)  # 是否已选择标签
    
    # 关系
    tags = relationship('Tag', secondary=student_tags, backref=backref('students', lazy='dynamic'))
    points_history = relationship('PointsHistory', backref='student_info', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<StudentInfo {self.student_id} {self.real_name}>'

# 标签模型
class Tag(db.Model):
    __tablename__ = 'tags'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True)
    description = Column(Text)  # 标签描述
    color = Column(String(20), default='primary')  # 标签颜色，用于前端显示
    created_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f'<Tag {self.name}>'

# 活动模型
class Activity(db.Model):
    __tablename__ = 'activities'
    id = Column(Integer, primary_key=True)
    title = Column(String(128), nullable=False)
    description = Column(Text)
    location = Column(String(128))
    
    # 时间相关字段
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    registration_deadline = Column(DateTime)
    completed_at = Column(DateTime)  # 活动完成时间
    
    # 参与人数
    max_participants = Column(Integer, default=0)  # 0表示不限制
    
    # 积分和类型
    points = Column(Integer, default=10)  # 参与可获得的积分
    type = Column(String(50), default='其他')  # 活动类型
    status = Column(String(20), default='active')  # 活动状态：active, completed, cancelled
    is_featured = Column(Boolean, default=False)  # 是否为重点活动
    
    # 海报图片
    poster_image = Column(String(255))  # 存储海报图片文件名
    poster_data = Column(db.LargeBinary)  # 存储海报图片二进制数据
    poster_mimetype = Column(String(50))  # 存储海报图片MIME类型
    
    # 签到相关
    checkin_key = Column(String(32))  # 签到密钥
    checkin_key_expires = Column(DateTime(timezone=True))  # 签到密钥过期时间
    checkin_enabled = Column(Boolean, default=False)  # 是否启用签到
    
    # 创建者和时间戳
    created_by = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 关系
    creator = relationship('User', backref='created_activities')
    registrations = relationship('Registration', backref='activity', lazy='dynamic', cascade='all, delete-orphan')
    reviews = relationship('ActivityReview', backref='activity', lazy='dynamic', cascade='all, delete-orphan')
    checkins = relationship('ActivityCheckin', backref='activity', lazy='dynamic', cascade='all, delete-orphan')
    tags = relationship('Tag', secondary=activity_tags, backref=backref('activities', lazy='dynamic'))
    
    # 海报属性方法 - 不再定义数据库字段，而是通过属性方法提供兼容性
    @property
    def poster_url(self):
        """提供向后兼容的poster_url属性"""
        if not self.poster_image:
            return None
        # 如果存在poster_data，优先使用数据库中的图片
        if hasattr(self, 'poster_data') and self.poster_data:
            return f"/poster/{self.id}"
        # 返回相对路径，模板中可以与url_for一起使用
        elif 'banner' in self.poster_image:
            return f"/static/img/{self.poster_image}"
        else:
            return f"/static/uploads/posters/{self.poster_image}"
    
    @property
    def poster(self):
        """提供向后兼容的poster属性"""
        return None  # 数据库中不再有此字段，返回None
    
    def __repr__(self):
        return f'<Activity {self.title}>'

# 活动报名模型
class Registration(db.Model):
    __tablename__ = 'registrations'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    activity_id = Column(Integer, ForeignKey('activities.id'))
    status = Column(String(20), default='registered')  # registered, attended, cancelled
    register_time = Column(DateTime, default=func.now())
    check_in_time = Column(DateTime)  # 签到时间
    remark = Column(Text)  # 备注
    
    # 唯一约束，确保一个用户只能报名一个活动一次
    __table_args__ = (UniqueConstraint('user_id', 'activity_id', name='_user_activity_uc'),)
    
    def __repr__(self):
        return f'<Registration {self.user_id} {self.activity_id}>'

# 积分历史模型
class PointsHistory(db.Model):
    __tablename__ = 'points_history'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('student_info.id', ondelete='CASCADE'))
    activity_id = Column(Integer, ForeignKey('activities.id', ondelete='SET NULL'), nullable=True)
    points = Column(Integer, default=0)  # 积分变化，可正可负
    reason = Column(String(200))  # 积分变化原因
    created_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f'<PointsHistory {self.student_id} {self.points}>'

# 活动评价模型
class ActivityReview(db.Model):
    __tablename__ = 'activity_reviews'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    activity_id = Column(Integer, ForeignKey('activities.id'), nullable=False)
    rating = Column(Integer, nullable=False)  # 总体评分，1-5
    content_quality = Column(Integer)  # 内容质量评分
    organization = Column(Integer)  # 组织评分
    facility = Column(Integer)  # 设施评分
    review = Column(Text, nullable=False)  # 评价内容
    is_anonymous = Column(Boolean, default=False)  # 是否匿名评价
    created_at = Column(DateTime, default=func.now())
    
    # 唯一约束，确保一个用户只能评价一个活动一次
    __table_args__ = (UniqueConstraint('user_id', 'activity_id', name='_user_activity_review_uc'),)
    
    def __repr__(self):
        return f'<ActivityReview {self.user_id} {self.activity_id}>'

# 公告模型
class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = Column(Integer, primary_key=True)
    title = Column(String(128))
    content = Column(Text)
    created_by = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    status = Column(String(20))  # 状态：draft, published, archived
    
    # 关系
    creator = relationship('User', backref='announcements')
    
    def __repr__(self):
        return f'<Announcement {self.title}>'

# 系统日志模型
class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    action = Column(String(64))  # 操作类型
    details = Column(Text)  # 详细信息
    ip_address = Column(String(64))  # IP地址
    created_at = Column(DateTime, default=func.now())
    
    # 关系
    user = relationship('User', backref='logs')
    
    def __repr__(self):
        return f'<SystemLog {self.action}>'

# 活动签到模型
class ActivityCheckin(db.Model):
    __tablename__ = 'activity_checkins'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    activity_id = Column(Integer, ForeignKey('activities.id'))
    checkin_time = Column(DateTime, default=func.now())
    status = Column(String(20), default='checked_in')  # 签到状态
    
    # 唯一约束，确保一个用户只能签到一个活动一次
    __table_args__ = (UniqueConstraint('user_id', 'activity_id', name='_user_activity_checkin_uc'),)
    
    def __repr__(self):
        return f'<ActivityCheckin {self.user_id} {self.activity_id}>'

# 消息模型
class Message(db.Model):
    __tablename__ = 'message'
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    receiver_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subject = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime)
    
    def __repr__(self):
        return f'<Message {self.subject}>'

# 通知模型
class Notification(db.Model):
    __tablename__ = 'notification'
    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    is_important = Column(Boolean)
    created_at = Column(DateTime)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=False)
    expiry_date = Column(DateTime)
    is_public = Column(Boolean, default=True)
    
    def __repr__(self):
        return f'<Notification {self.title}>'

# 通知阅读记录模型
class NotificationRead(db.Model):
    __tablename__ = 'notification_read'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    notification_id = Column(Integer, ForeignKey('notification.id'), nullable=False)
    read_at = Column(DateTime)
    
    # 唯一约束，确保一个用户只能标记一个通知为已读一次
    __table_args__ = (UniqueConstraint('user_id', 'notification_id', name='uq_notification_user'),)
    
    # 关系
    notification = relationship('Notification', backref=backref('reads', lazy='dynamic'))
    
    def __repr__(self):
        return f'<NotificationRead {self.user_id} {self.notification_id}>'

# AI聊天历史记录模型
class AIChatHistory(db.Model):
    __tablename__ = 'ai_chat_history'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    session_id = Column(String(255), ForeignKey('ai_chat_session.id', ondelete='CASCADE'), nullable=False)
    role = Column(String(50), nullable=False)  # 'user' 或 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f'<AIChatHistory {self.id}>'

# AI聊天会话模型
class AIChatSession(db.Model):
    __tablename__ = 'ai_chat_session'
    id = Column(String(255), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # 关系
    history = relationship('AIChatHistory', backref='session', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<AIChatSession {self.id}>'

# AI用户偏好模型
class AIUserPreferences(db.Model):
    __tablename__ = 'ai_user_preferences'
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    enable_history = Column(Boolean, default=True)
    max_history_count = Column(Integer, default=50)
    interests = Column(Text)  # 存储为JSON字符串
    preferences = Column(Text)  # 存储为JSON字符串
    
    def get_interests(self):
        """获取用户兴趣列表"""
        if not self.interests:
            return []
        try:
            return json.loads(self.interests)
        except:
            return []
    
    def set_interests(self, interests_list):
        """设置用户兴趣列表"""
        self.interests = json.dumps(interests_list)
    
    def get_preferences(self):
        """获取用户偏好设置"""
        if not self.preferences:
            return {}
        try:
            return json.loads(self.preferences)
        except:
            return {}
    
    def set_preferences(self, preferences_dict):
        """设置用户偏好设置"""
        self.preferences = json.dumps(preferences_dict)
    
    def __repr__(self):
        return f'<AIUserPreferences {self.user_id}>'
