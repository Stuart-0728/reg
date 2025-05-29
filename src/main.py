import os
from flask import Flask, render_template
from flask_migrate import Migrate
from flask_login import LoginManager
from src.models import db, User
from src import register_blueprints

def create_app():
    app = Flask(__name__)

    # 加载配置
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bad4147d0e436553811dc682a3c25822')
    
    database_url = os.environ.get('DATABASE_URL', 'postgresql://virtual_event_db_user:Yyqhn8GDTloyPZmeIC3R4ZcuRimS15JF@dpg-d0qt6djuibrs73eu5mjg-a.singapore-postgres.render.com/virtual_event_db')
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    elif database_url.startswith('mysql://'):
        database_url = database_url.replace('mysql://', 'mysql+pymysql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 初始化扩展
    db.init_app(app)
    migrate = Migrate(app, db)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # 注册蓝图
    register_blueprints(app)

    # 错误处理
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template('500.html'), 500

    return app

# Gunicorn 用
app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
