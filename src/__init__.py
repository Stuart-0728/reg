import os
import logging
from logging.handlers import RotatingFileHandler
import pytz
from flask import Flask, session, g, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timedelta
from src.config import config, Config

# 创建SQLAlchemy实例
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
sess = Session()
limiter = Limiter(key_func=get_remote_address)
cache = Cache()

def create_app(config_name=None):
    """创建Flask应用"""
    if config_name is None:
        config_name = os.environ.get('FLASK_CONFIG', '').strip()
        if not config_name:
            runtime_env = (os.environ.get('FLASK_ENV') or os.environ.get('ENV') or '').strip().lower()
            config_name = 'production' if runtime_env == 'production' else 'default'
    
    app = Flask(__name__, instance_relative_config=True)
    
    # 从config.py导入配置
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    if app.config.get('ENABLE_PROXY_FIX', True):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    
    # 设置时区
    os.environ['TZ'] = app.config.get('TIMEZONE_NAME', 'Asia/Shanghai')
    
    # 配置日志系统
    setup_logging(app)
    app.logger.info(f"应用启动，配置模式: {config_name}")
    
    # 配置数据库连接池
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgresql'):
        app.logger.info("检测到PostgreSQL数据库，正在配置连接池...")
        engine_options = dict(app.config.get('SQLALCHEMY_ENGINE_OPTIONS') or {})
        connect_args = dict(engine_options.get('connect_args') or {})

        engine_options.setdefault('pool_size', 10)
        engine_options.setdefault('max_overflow', 20)
        engine_options.setdefault('pool_timeout', 20)
        engine_options.setdefault('pool_recycle', 3600)
        engine_options.setdefault('pool_use_lifo', True)
        engine_options.setdefault('pool_pre_ping', True)

        connect_args.setdefault('keepalives', 1)
        connect_args.setdefault('keepalives_idle', 30)
        connect_args.setdefault('keepalives_interval', 10)
        connect_args.setdefault('keepalives_count', 5)

        engine_options['connect_args'] = connect_args
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
        app.logger.info("PostgreSQL连接池配置完成")
    
    # 确保SESSION_COOKIE_NAME已设置
    if 'SESSION_COOKIE_NAME' not in app.config:
        app.config['SESSION_COOKIE_NAME'] = 'session'
        app.logger.warning("SESSION_COOKIE_NAME未设置，使用默认值'session'")
    
    # 初始化扩展
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    
    # 使用Flask原生会话而不是Flask-Session，避免云环境文件系统问题
    app.logger.info("使用Flask原生会话系统")
    
    limiter.init_app(app)
    cache.init_app(app)

    limiter_storage = app.config.get('RATELIMIT_STORAGE_URI') or app.config.get('RATELIMIT_STORAGE_URL')
    if limiter_storage:
        app.logger.info(f"Flask-Limiter storage backend: {limiter_storage}")
        if str(limiter_storage).startswith('memory://'):
            app.logger.warning("当前限流后端为内存存储，生产并发场景建议配置REDIS_URL")
    
    # 配置登录管理器
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录以访问此页面'
    login_manager.login_message_category = 'info'
    
    # 初始化模型 - 在应用上下文中进行，确保db已经初始化
    with app.app_context():
        # 初始化数据库模型
        from src.models import User, StudentInfo, Activity, Registration, Tag, Role
        from src.models import PointsHistory, ActivityReview, Announcement, SystemLog
        from src.models import ActivityCheckin, Message, Notification, NotificationRead
        from src.models import AIChatHistory, AIChatSession, AIUserPreferences
        
        # 确保模型与当前app关联
        db.create_all()
        
        # 设置用户加载函数
        @login_manager.user_loader
        def load_user(user_id):
            """加载用户信息，供Flask-Login使用"""
            raw_user_id = str(user_id or '').strip()
            if not raw_user_id:
                return None

            # 新格式: "<uid>:<password_fingerprint>"
            if ':' not in raw_user_id:
                # 旧格式直接失效：强制重新登录并升级到新会话格式
                return None

            uid_part, fingerprint = raw_user_id.split(':', 1)
            if not uid_part.isdigit() or not fingerprint:
                return None

            user = db.session.get(User, int(uid_part))
            if not user:
                return None

            current_fingerprint = str(getattr(user, 'password_hash', '') or '')[-24:]
            if current_fingerprint != fingerprint:
                return None
            return user
    
    # 注册蓝图 - 在模型初始化之后
    register_blueprints(app)
    
    # 添加特定API路由的CSRF豁免 - 必须在蓝图注册之后
    with app.app_context():
        # 使用官方推荐的 exempt 方法豁免指定路由
        csrf.exempt('education.gemini_api')
        app.logger.info('已为education.gemini_api路由添加CSRF豁免')
    
    # 注册时区处理中间件
    @app.before_request
    def before_request():
        """在请求处理前设置时区"""
        if not session.permanent:
            session.permanent = True
        timezone_name = app.config.get('TIMEZONE_NAME', 'Asia/Shanghai')
        # 仅在缺失或变更时写入session，避免每个请求都触发会话写盘
        if session.get('timezone') != timezone_name:
            session['timezone'] = timezone_name
        g.timezone = pytz.timezone(timezone_name)

    @app.after_request
    def add_no_store_headers(response):
        """防止登出后浏览器/CDN缓存回显上一账号页面或接口数据。"""
        try:
            path = (request.path or '').lower()
            content_type = (response.headers.get('Content-Type') or '').lower()

            # 统一安全响应头（不影响业务逻辑）
            response.headers.setdefault('X-Content-Type-Options', 'nosniff')
            response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
            response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
            response.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(self), camera=(self)')

            # 静态资源按类型分层缓存，优先让EdgeOne命中
            if path.startswith('/static/'):
                if any(path.endswith(ext) for ext in ('.css', '.js', '.mjs')):
                    response.headers['Cache-Control'] = 'public, max-age=600, s-maxage=86400, stale-while-revalidate=300'
                elif any(path.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.woff', '.woff2', '.ttf')):
                    response.headers['Cache-Control'] = 'public, max-age=3600, s-maxage=259200, stale-while-revalidate=600'
                response.headers['Vary'] = 'Accept-Encoding'
                return response

            # 动态业务路由一律禁用缓存，避免跨账号缓存污染
            is_dynamic_route = (
                not path.startswith('/static/') and (
                    path.startswith('/auth')
                    or path.startswith('/admin')
                    or path.startswith('/student')
                    or path.startswith('/utils')
                    or path == '/'
                )
            )

            if is_dynamic_route or 'text/html' in content_type:
                response.headers['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0'
                response.headers['CDN-Cache-Control'] = 'no-store'
                response.headers['Surrogate-Control'] = 'no-store'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'

                # 告诉CDN/代理：响应与Cookie相关，不能复用给其他会话
                vary_value = response.headers.get('Vary', '')
                vary_tokens = [v.strip() for v in vary_value.split(',') if v.strip()]
                for token in ['Cookie', 'Authorization']:
                    if token not in vary_tokens:
                        vary_tokens.append(token)
                response.headers['Vary'] = ', '.join(vary_tokens)

            if current_user.is_authenticated and 'text/html' in content_type:
                response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                response.headers['CDN-Cache-Control'] = 'no-store'
                response.headers['Surrogate-Control'] = 'no-store'

            # 公共JSON接口允许短期边缘缓存，提升高并发命中率
            public_edge_paths = {
                '/api/public-notifications',
            }
            if path in public_edge_paths and response.status_code == 200:
                response.headers['Cache-Control'] = 'public, max-age=20, s-maxage=120, stale-while-revalidate=60'
                response.headers['Vary'] = 'Accept-Encoding'
                response.headers.pop('Pragma', None)
                response.headers.pop('Expires', None)
        except Exception:
            pass
        return response
    
    # 注册Shell上下文
    @app.shell_context_processor
    def make_shell_context():
        """为Flask shell提供上下文"""
        # 延迟导入模型，避免循环导入
        from src.models import User, Activity, Registration, Tag
        return dict(
            app=app, db=db, 
            User=User, Activity=Activity, 
            Registration=Registration,
            Tag=Tag
        )
    
    # 错误处理
    register_error_handlers(app)
    
    # 命令行命令
    register_commands(app)
    
    # 确保数据库目录和文件有正确的权限
    with app.app_context():
        if 'sqlite:' in str(app.config['SQLALCHEMY_DATABASE_URI']):
            db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
            db_dir = os.path.dirname(db_path)
            
            # 确保目录存在且有正确权限
            if not os.path.exists(db_dir):
                try:
                    os.makedirs(db_dir, mode=0o755)
                    app.logger.info(f"已创建数据库目录: {db_dir}")
                except Exception as e:
                    app.logger.error(f"创建数据库目录失败: {e}")
            
            # 设置目录权限
            try:
                os.chmod(db_dir, 0o755)
                app.logger.info(f"已设置数据库目录权限: {db_dir}")
            except Exception as e:
                app.logger.error(f"设置数据库目录权限失败: {e}")
            
            # 设置数据库文件权限
            if os.path.exists(db_path):
                try:
                    os.chmod(db_path, 0o644)
                    app.logger.info(f"已设置数据库文件权限: {db_path}")
                except Exception as e:
                    app.logger.error(f"设置数据库文件权限失败: {e}")
    
    # 注册模板函数
    register_template_functions(app)
    
    # 注册全局上下文处理器
    register_context_processors(app)
    
    # 调用确保数据库结构的脚本
    with app.app_context():
        try:
            # 注释掉以下两行，因为它们是为本地SQLite设计的，在连接PostgreSQL时会引发问题
            # from scripts.ensure_db_structure import ensure_db_structure
            # ensure_db_structure()
            # 改为仅执行"序列健康检查"（对PostgreSQL安全）
            try:
                from scripts.ensure_db_structure import ensure_db_structure
                ensure_db_structure(app, db)
                app.logger.info("已执行数据库结构与序列健康检查")
            except Exception as inner_e:
                app.logger.warning(f"执行序列健康检查时出现问题: {inner_e}")
        except ImportError:
            app.logger.warning("未找到确保数据库结构的脚本，跳过初始化")
        except Exception as e:
            app.logger.error(f"初始化数据库结构时出错: {e}")
    
    return app

def setup_logging(app):
    """配置日志系统"""
    # 配置根日志记录器
    log_level_name = app.config.get('LOG_LEVEL', 'INFO')
    if isinstance(log_level_name, str):
        log_level = getattr(logging, log_level_name)
    else:
        log_level = logging.INFO
        app.logger.warning(f"LOG_LEVEL不是字符串，使用默认INFO级别")
    
    # 创建处理器
    log_format = app.config.get('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 检查是否在Serverless环境中
    if os.environ.get('SERVERLESS_PLATFORM_VENDOR'):
        # 在Serverless环境中，使用标准输出流而不是文件
        handler = logging.StreamHandler()
        app.logger.info('检测到Serverless环境，日志将输出到标准输出')
    else:
        # 在传统环境中，使用文件日志
        log_dir = app.config.get('LOG_FOLDER')
        if log_dir is None:
            log_dir = os.path.join(app.root_path, 'logs')
            app.logger.warning(f"未配置LOG_FOLDER，使用默认日志目录: {log_dir}")
            
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, mode=0o755)
            except Exception as e:
                app.logger.warning(f"创建日志目录失败: {e}，将使用标准输出")
                handler = logging.StreamHandler()
            else:
                log_file = os.path.join(log_dir, app.config.get('LOG_FILENAME', 'cqnu_association.log'))
                handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=10)
        else:
            log_file = os.path.join(log_dir, app.config.get('LOG_FILENAME', 'cqnu_association.log'))
            handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=10)
    
    handler.setFormatter(logging.Formatter(log_format))
    handler.setLevel(log_level)
    
    # 添加到根日志记录器
    logging.getLogger().setLevel(log_level)
    logging.getLogger().addHandler(handler)
    
    # 添加到应用日志记录器
    app.logger.addHandler(handler)
    
    # 设置SQLAlchemy日志级别
    if app.config.get('SQLALCHEMY_ECHO'):
        logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
    
    app.logger.info('日志系统初始化完成')

def register_blueprints(app):
    """注册所有蓝图"""
    # 导入蓝图
    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.admin import admin_bp
    from .routes.student import student_bp
    from .routes.utils import utils_bp
    from .routes.tag import tag_bp
    from .routes.checkin import checkin_bp
    from .routes.education import education_bp
    
    # 创建API蓝图 - 用于处理/api请求
    from flask import Blueprint
    from .routes.utils import ai_chat, ai_chat_legacy_post
    
    api_bp = Blueprint('api', __name__, url_prefix='/api')
    
    # 将AI聊天路由添加到API蓝图
    api_bp.route('/ai_chat', methods=['GET'])(ai_chat)
    api_bp.route('/ai/chat', methods=['POST'])(ai_chat_legacy_post)
    
    # 注册蓝图
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(student_bp, url_prefix='/student')
    app.register_blueprint(utils_bp, url_prefix='/utils')
    app.register_blueprint(tag_bp, url_prefix='/tag')
    app.register_blueprint(checkin_bp, url_prefix='/checkin')
    app.register_blueprint(education_bp, url_prefix='/education')
    app.register_blueprint(api_bp)  # 注册API蓝图
    
    # 注册错误处理蓝图
    from .routes.errors import errors_bp
    app.register_blueprint(errors_bp)

def register_error_handlers(app):
    """注册错误处理函数"""
    from .routes.errors import page_not_found, internal_server_error
    
    app.register_error_handler(404, page_not_found)
    app.register_error_handler(500, internal_server_error)

def register_commands(app):
    """注册Flask命令行命令"""
    @app.cli.command('create-admin')
    def create_admin():
        """创建管理员账户"""
        from src.models import User, Role
        from werkzeug.security import generate_password_hash
        
        # 检查是否已存在管理员角色
        admin_role = db.session.execute(db.select(Role).filter_by(name='Admin')).scalar_one_or_none()
        if admin_role is None:
            admin_role = Role(name='Admin', description='管理员')
            db.session.add(admin_role)
            db.session.commit()
            app.logger.info('已创建管理员角色')
        
        # 创建管理员用户
        admin = db.session.execute(db.select(User).filter_by(username='admin')).scalar_one_or_none()
        if admin is None:
            admin = User(
                username='admin',
                email='admin@example.com',
                password_hash=generate_password_hash('admin123'),
                role_id=admin_role.id
            )
            db.session.add(admin)
            db.session.commit()
            app.logger.info('已创建管理员用户: admin/admin123')
        else:
            app.logger.info('管理员用户已存在')
    
    @app.cli.command('initialize-db')
    def initialize_db():
        """初始化数据库"""
        db.create_all()
        app.logger.info('已初始化数据库表')

def register_template_functions(app):
    """注册模板函数"""
    # 从utils.time_helpers导入时间处理函数
    from src.utils.time_helpers import display_datetime, format_datetime, get_localized_now
    
    @app.template_filter('datetime')
    def _display_datetime(dt, fmt=None):
        """格式化日期时间，展示为友好格式"""
        return display_datetime(dt, fmt)
    
    @app.template_filter('format_date')
    def _format_date(dt):
        """格式化日期"""
        return format_datetime(dt, '%Y-%m-%d')
    
    @app.template_filter('format_time')
    def _format_time(dt):
        """格式化时间"""
        return format_datetime(dt, '%H:%M:%S')
    
    @app.template_filter('format_datetime')
    def _format_datetime(dt, fmt='%Y-%m-%d %H:%M'):
        """格式化日期时间"""
        return format_datetime(dt, fmt)
    
    @app.template_global('now')
    def _now():
        """获取当前时间"""
        # 获取当前中国时区的时间
        return get_localized_now()

def register_context_processors(app):
    """注册上下文处理器"""
    
    @app.context_processor
    def inject_now_and_helpers():
        """向模板注入当前时间和助手函数"""
        from src.utils.time_helpers import get_localized_now
        return {
            'now': get_localized_now,
            'pytz': pytz
        }