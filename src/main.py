import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

# 创建扩展实例（不绑定 app）
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    # 配置密钥（生产环境应使用强随机密钥）
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change_this_secret_key')

    # 根据环境变量设置数据库 URI
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        # 适配 PostgreSQL URI：将旧版 postgres:// 改为 postgresql://
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        # 适配 MySQL URI：为 mysql:// 添加 pymysql 驱动前缀
        elif database_url.startswith('mysql://'):
            database_url = database_url.replace('mysql://', 'mysql+pymysql://', 1)
        app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    else:
        # 本地开发使用 MySQL 示例配置，请替换为真实的用户名、密码、主机和数据库名
        app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://username:password@localhost/dbname'
    
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # 错误处理：渲染自定义的 404 和 500 页面
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('500.html'), 500

    # 其他蓝图或路由注册可以在此添加
    # 例如: app.register_blueprint(auth_bp), app.register_blueprint(main_bp) 等

    return app

# 创建应用实例，以便 Gunicorn 可以导入 app 对象
app = create_app()

if __name__ == '__main__':
    # 开发模式下运行 Flask 自带的服务器
    app.run(debug=True)
