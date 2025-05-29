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
    # 把 role 由原先的整数外键改成纯字符串
    role           = db.Column(db.String(20), default='Student', nullable=False)

    # 如果你有学生扩展信息表，就保持这一行
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

# ===== 角色表（可留可删，已不再直接关联） =====
class Role(db.Model):
    __tablename__ = 'roles'
    id    = db.Column(db.Integer, primary_key=True)
    name  = db.Column(db.String(64), unique=True)

    def __repr__(self):
        return f'<Role {self.name}>'

# ===== 其他模型（保持不变） =====
# ... Registration, Activity, SystemLog 等 ...
