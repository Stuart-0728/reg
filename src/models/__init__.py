from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# ===== 用户模型 =====
class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(64), unique=True, index=True, nullable=False)
    email          = db.Column(db.String(120), unique=True, index=True, nullable=False)
    password_hash  = db.Column(db.String(128), nullable=False)
    role           = db.Column(db.String(20), default='Student', nullable=False)

    student_info   = db.relationship('StudentInfo', backref='user', uselist=False)
    registrations  = db.relationship('Registration', backref='user', lazy='dynamic')

    created_at     = db.Column(db.DateTime, default=datetime.now)
    last_login     = db.Column(db.DateTime)

    def __repr__(self):
        return f'<User {self.username}>'

# ===== 学生信息表 =====
class StudentInfo(db.Model):
    __tablename__ = 'student_info'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    real_name  = db.Column(db.String(64))
    student_id = db.Column(db.String(20), unique=True)
    grade      = db.Column(db.String(20))
    major      = db.Column(db.String(64))
    college    = db.Column(db.String(64))
    phone      = db.Column(db.String(20))
    qq         = db.Column(db.String(20))

    def __repr__(self):
        return f'<StudentInfo {self.real_name}>'

# ===== 角色表 =====
class Role(db.Model):
    __tablename__ = 'roles'
    id    = db.Column(db.Integer, primary_key=True)
    name  = db.Column(db.String(64), unique=True)

    def __repr__(self):
        return f'<Role {self.name}>'

# ===== 活动模型 =====
class Activity(db.Model):
    __tablename__ = 'activities'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<Activity {self.title}>'

# ===== 报名模型 =====
class Registration(db.Model):
    __tablename__ = 'registrations'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activities.id'), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Registration {self.user_id} - {self.activity_id}>'

# ===== 系统日志模型 =====
class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<SystemLog {self.action}>'

# ===== 公告模型 =====
class Announcement(db.Model):
    __tablename__ = 'announcements'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Announcement {self.title}>'

# 导出所有模型
__all__ = ['db', 'User', 'StudentInfo', 'Role', 'Activity', 'Registration', 'SystemLog', 'Announcement']
