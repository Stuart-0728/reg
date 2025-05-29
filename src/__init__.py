# src/__init__.py

from .routes.admin import admin_bp
from .routes.auth import auth_bp
from .routes.main import main_bp
from .routes.student import student_bp
from .routes.utils import utils_bp

def register_blueprints(app):
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(utils_bp, url_prefix='/utils')
