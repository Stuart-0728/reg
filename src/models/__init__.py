from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# 用户角色表
class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    users = db.relationship('User', backref='role', lazy='dynamic')

    def __repr__(self):
        return f'<Role {self.name}>'

# 用户表
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(120), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    role_id = db.Column('role', db.Integer, db.ForeignKey('roles.id'))  # 显式绑定数据库中的 `role` 字段
    student_info = db.relationship('StudentInfo', backref='user', uselist=False)
    registrations = db.relationship('Registration', backref='user', lazy='dynamic')
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_login = db.Column(db.DateTime)

    def __repr__(self):
        return f'<User {self.username}>'


# 学生信息表
class StudentInfo(db.Model):
    __tablename__ = 'student_info'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    real_name = db.Column(db.String(64))
    student_id = db.Column(db.String(20), unique=True)
    grade = db.Column(db.String(20))
    major = db.Column(db.String(64))
    college = db.Column(db.String(64))
    phone = db.Column(db.String(20))
    qq = db.Column(db.String(20))

    def __repr__(self):
        return f'<StudentInfo {self.real_name}>'

# 活动表
class Activity(db.Model):
    __tablename__ = 'activities'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128))
    description = db.Column(db.Text)
    location = db.Column(db.String(128))
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    registration_deadline = db.Column(db.DateTime)
    max_participants = db.Column(db.Integer, default=0)  # 0表示不限制人数
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    status = db.Column(db.String(20), default='active')  # active, cancelled, completed
    registrations = db.relationship('Registration', backref='activity', lazy='dynamic')
    
    def __repr__(self):
        return f'<Activity {self.title}>'

# 活动报名表
class Registration(db.Model):
    __tablename__ = 'registrations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    activity_id = db.Column(db.Integer, db.ForeignKey('activities.id'))
    register_time = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default='registered')  # registered, cancelled, attended
    remark = db.Column(db.Text)
    
    def __repr__(self):
        return f'<Registration {self.id}>'

# 系统公告表
class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128))
    content = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    status = db.Column(db.String(20), default='active')  # active, archived
    
    def __repr__(self):
        return f'<Announcement {self.title}>'

# 系统日志表
class SystemLog(db.Model):
    __tablename__ = 'system_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(64))
    details = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<SystemLog {self.action}>'
