import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # DON'T CHANGE THIS !!!

from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_migrate import Migrate
from src.models import db, User, Role, StudentInfo, Activity, Registration, Announcement, SystemLog
from src.routes.auth import auth_bp
from src.routes.admin import admin_bp
from src.routes.student import student_bp
from src.routes.main import main_bp
import logging
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'cqnu-association-secret-key')

# —— 数据库配置 ——  
database_url = os.getenv('DATABASE_URL')
if database_url:
    # Render 环境下使用 PostgreSQL
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # 本地或其他环境回退到 MySQL
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"mysql+pymysql://{os.getenv('DB_USERNAME', 'root')}:"
        f"{os.getenv('DB_PASSWORD', 'password')}@"
        f"{os.getenv('DB_HOST', 'localhost')}:"
        f"{os.getenv('DB_PORT', '3306')}/"
        f"{os.getenv('DB_NAME', 'cqnu_association')}"
    )

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 初始化数据库和迁移
db.init_app(app)
migrate = Migrate(app, db)

# 初始化登录管理器
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录以访问此页面'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# 注册蓝图
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(student_bp)
app.register_blueprint(main_bp)

# —— 上下文处理器 ——  
# 将当前时间注入到所有模板，使 base.html 中能使用 {{ now.year }}
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# 记录用户最后登录时间
@app.before_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_login = datetime.now()
        db.session.commit()

# 全局错误处理
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_server_error(e):
    return render_template('500.html'), 500

# CLI 命令：创建管理员账户和初始化角色
@app.cli.command('create-admin')
def create_admin():
    """创建管理员账户"""
    from werkzeug.security import generate_password_hash
    
    # 创建或获取角色
    admin_role = Role.query.filter_by(name='Admin').first()
    if not admin_role:
        admin_role = Role(name='Admin')
        db.session.add(admin_role)
    
    student_role = Role.query.filter_by(name='Student').first()
    if not student_role:
        student_role = Role(name='Student')
        db.session.add(student_role)
    
    # 创建或获取管理员用户
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@cqnu.edu.cn',
            password_hash=generate_password_hash('admin123'),
            role=admin_role
        )
        db.session.add(admin)
    
    db.session.commit()
    print('管理员账户创建成功！')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
