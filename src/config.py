import os
import logging
import secrets
from datetime import timedelta
from dotenv import load_dotenv
import pytz

# 在文件顶部，确保 .env 文件总是在配置被读取前加载
load_dotenv() 

# 基础路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_PATH = os.path.join(BASE_DIR, 'instance')
DB_PATH = os.path.join(INSTANCE_PATH, 'cqnu_association.db')
LOG_PATH = os.path.join(BASE_DIR, 'logs')
UPLOAD_FOLDER = os.environ.get('PERSISTENT_STORAGE_PATH', os.path.join(BASE_DIR, 'static', 'uploads', 'posters'))
ACTIVITY_DOCS_DIR = os.environ.get('ACTIVITY_DOCS_DIR', os.path.join(os.path.dirname(BASE_DIR), 'storage', 'activity_docs'))
SESSION_FILE_DIR = os.path.join(BASE_DIR, 'flask_session')

# 确保目录存在并设置权限
def ensure_directories():
    """确保必要的目录存在并设置正确的权限"""
    global UPLOAD_FOLDER, ACTIVITY_DOCS_DIR
    
    # 确保instance目录存在
    if not os.path.exists(INSTANCE_PATH):
        try:
            os.makedirs(INSTANCE_PATH, mode=0o755)
            print(f"已创建数据库目录: {INSTANCE_PATH}")
        except Exception as e:
            print(f"创建数据库目录失败: {e}")
    
    # 检查instance目录权限
    try:
        instance_perms = os.stat(INSTANCE_PATH).st_mode & 0o777
        if instance_perms != 0o755:
            os.chmod(INSTANCE_PATH, 0o755)
            print(f"已修改数据库目录权限为755: {INSTANCE_PATH}")
    except Exception as e:
        print(f"修改数据库目录权限失败: {e}")
    
    # 检查数据库文件权限
    if os.path.exists(DB_PATH):
        try:
            db_perms = os.stat(DB_PATH).st_mode & 0o777
            if db_perms != 0o644:
                os.chmod(DB_PATH, 0o644)
                print(f"已修改数据库文件权限为644: {DB_PATH}")
        except Exception as e:
            print(f"修改数据库文件权限失败: {e}")
    
    # 确保日志目录存在
    if not os.path.exists(LOG_PATH):
        try:
            os.makedirs(LOG_PATH)
            print(f"已创建日志目录: {LOG_PATH}")
        except Exception as e:
            print(f"创建日志目录失败: {e}")
    
    # 确保上传目录存在
    try:
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)
            print(f"已创建上传目录: {UPLOAD_FOLDER}")
    except Exception as e:
        print(f"创建上传目录失败: {e}")
        # 如果创建失败，尝试使用临时目录
        temp_upload = os.path.join(BASE_DIR, 'temp_uploads')
        try:
            if not os.path.exists(temp_upload):
                os.makedirs(temp_upload)
            print(f"使用临时上传目录: {temp_upload}")
            UPLOAD_FOLDER = temp_upload
        except Exception as e2:
            print(f"创建临时上传目录也失败: {e2}")
    
    # 确保session目录存在
    if not os.path.exists(SESSION_FILE_DIR):
        try:
            os.makedirs(SESSION_FILE_DIR)
            print(f"已创建session目录: {SESSION_FILE_DIR}")
        except Exception as e:
            print(f"创建session目录失败: {e}")

    # 确保活动资料目录存在（独立于代码目录，避免部署覆盖）
    try:
        if not os.path.exists(ACTIVITY_DOCS_DIR):
            os.makedirs(ACTIVITY_DOCS_DIR, exist_ok=True)
            print(f"已创建活动资料目录: {ACTIVITY_DOCS_DIR}")
    except Exception as e:
        print(f"创建活动资料目录失败: {e}")
        fallback_docs = os.path.join(UPLOAD_FOLDER, 'activity_docs')
        try:
            if not os.path.exists(fallback_docs):
                os.makedirs(fallback_docs, exist_ok=True)
            ACTIVITY_DOCS_DIR = fallback_docs
            print(f"使用回退活动资料目录: {ACTIVITY_DOCS_DIR}")
        except Exception as e2:
            print(f"创建回退活动资料目录失败: {e2}")
            
    # 打印当前工作目录和权限信息
    print(f"当前工作目录: {os.getcwd()}")
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"UPLOAD_FOLDER: {UPLOAD_FOLDER}")
    print(f"ACTIVITY_DOCS_DIR: {ACTIVITY_DOCS_DIR}")

# 创建并设置目录权限
ensure_directories()

logger = logging.getLogger(__name__)

class Config:
    """应用配置类"""
    # 基础配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-cqnu-association'
    SECURITY_PASSWORD_SALT = os.environ.get('SECURITY_PASSWORD_SALT') or 'cqnu-association-salt'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)  # 会话持续30天
    
    # 日志配置
    LOG_PATH = LOG_PATH
    LOG_FILE = os.path.join(LOG_PATH, 'cqnu_association.log')
    LOG_LEVEL = logging.INFO
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    LOG_BACKUP_COUNT = int(os.environ.get('LOG_BACKUP_COUNT', 10))
    LOG_MAX_BYTES = int(os.environ.get('LOG_MAX_BYTES', 10 * 1024 * 1024))  # 10MB
    
    # 上传文件配置
    UPLOAD_FOLDER = UPLOAD_FOLDER
    ACTIVITY_DOCS_DIR = ACTIVITY_DOCS_DIR
    ALLOWED_EXTENSIONS = {
        'pdf',
        'doc', 'docx',
        'xls', 'xlsx',
        'ppt', 'pptx',
        'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp',
        'txt', 'zip'
    }
    MAX_CONTENT_LENGTH = 80 * 1024 * 1024  # 80MB，匹配Nginx上传限制
    
    # 数据库配置
    INSTANCE_PATH = INSTANCE_PATH
    DB_PATH = DB_PATH

    # 单数据库配置（已移除历史双库同步方案）
    PRIMARY_DATABASE_URL = os.environ.get('DATABASE_URL') or os.environ.get('RENDER_DATABASE_URL')
    SQLALCHEMY_DATABASE_URI = PRIMARY_DATABASE_URL or f'sqlite:///{DB_PATH}'

    db_type = "主数据库" if PRIMARY_DATABASE_URL else "SQLite"
    logger.info(f"使用{db_type}: {SQLALCHEMY_DATABASE_URI[:50] + '...' if len(SQLALCHEMY_DATABASE_URI) > 50 else SQLALCHEMY_DATABASE_URI}")
    
    # SQLAlchemy配置 - 优化连接池以减少延迟
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 15,  # 增加连接池大小
        'max_overflow': 30,  # 增加最大溢出连接数
        'pool_timeout': 20,  # 减少连接超时时间
        'pool_recycle': 3600,  # 连接回收时间，1小时
        'pool_use_lifo': True,  # 优先复用最近连接，降低空闲连接失活概率
        'pool_pre_ping': True,  # 连接前ping一下确保连接有效
        'echo': False,  # 生产环境关闭SQL回显
    }
    
    # 时区配置
    TIMEZONE_NAME = 'Asia/Shanghai'
    TIMEZONE = pytz.timezone('Asia/Shanghai')
    
    # 天气API配置 - 高德开放平台（主要）
    AMAP_API_KEY = os.environ.get('AMAP_API_KEY', '')
    
    # 天气API配置 - OpenWeather（备用）
    OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', '')
    
    # 如果使用PostgreSQL，设置时区和连接参数 - 优化连接性能
    if 'postgresql:' in str(SQLALCHEMY_DATABASE_URI):
        _statement_timeout_ms = int(os.environ.get('DB_STATEMENT_TIMEOUT_MS', 12000))
        SQLALCHEMY_ENGINE_OPTIONS['connect_args'] = {
            'options': f'-c timezone=UTC -c statement_timeout={_statement_timeout_ms}',  # 限制慢SQL占用
            'connect_timeout': int(os.environ.get('DB_CONNECT_TIMEOUT', 8)),  # 减少连接超时时间
            'keepalives': 1,  # 启用TCP keepalive
            'keepalives_idle': 20,  # 减少空闲时间，更快检测断开连接
            'keepalives_interval': 5,  # 减少keepalive包间隔
            'keepalives_count': 3,  # 减少重试次数，更快故障转移
            'application_name': 'cqnu_association',  # 应用名称，便于数据库监控
        }
    
    # Flask-Session配置 - 使用内存存储以避免云环境文件系统问题
    SESSION_TYPE = 'null'  # 使用Flask原生会话，不使用Flask-Session
    SESSION_PERMANENT = True
    SESSION_USE_SIGNER = True
    SESSION_COOKIE_NAME = 'cqnu_session'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = False  # 在开发环境中设为False，生产环境应为True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_REFRESH_EACH_REQUEST = True

    # Flask-Login Remember Me（关闭浏览器后仍可保留登录状态）
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = True
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = False  # 在开发环境中设为False，生产环境应为True
    REMEMBER_COOKIE_SAMESITE = 'Lax'

    # 反向代理与静态资源缓存
    ENABLE_PROXY_FIX = True
    SEND_FILE_MAX_AGE_DEFAULT = int(os.environ.get('SEND_FILE_MAX_AGE_DEFAULT', 86400))
    
    # Flask-Cache配置
    _redis_url = os.environ.get('REDIS_URL', '').strip()
    if _redis_url:
        CACHE_TYPE = 'RedisCache'
        CACHE_REDIS_URL = _redis_url
    else:
        CACHE_TYPE = 'SimpleCache'
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get('CACHE_TIMEOUT', 300))
    
    # Flask-Limiter配置
    RATELIMIT_STORAGE_URI = _redis_url if _redis_url else "memory://"
    RATELIMIT_STORAGE_URL = RATELIMIT_STORAGE_URI
    RATELIMIT_DEFAULT = "200 per day, 50 per hour"
    RATELIMIT_STRATEGY = 'fixed-window'

    # 讯飞数字人 Web SDK 配置（建议通过环境变量注入）
    DIGITAL_HUMAN_SERVER_URL = os.environ.get(
        'DIGITAL_HUMAN_SERVER_URL',
        'wss://avatar.cn-huadong-1.xf-yun.com/v1/interact'
    ).strip()
    DIGITAL_HUMAN_APP_ID = os.environ.get('DIGITAL_HUMAN_APP_ID', '').strip()
    DIGITAL_HUMAN_API_KEY = os.environ.get('DIGITAL_HUMAN_API_KEY', '').strip()
    DIGITAL_HUMAN_API_SECRET = os.environ.get('DIGITAL_HUMAN_API_SECRET', '').strip()
    DIGITAL_HUMAN_SCENE_ID = os.environ.get('DIGITAL_HUMAN_SCENE_ID', '').strip()
    DIGITAL_HUMAN_AVATAR_ID = os.environ.get('DIGITAL_HUMAN_AVATAR_ID', '111165001').strip()
    DIGITAL_HUMAN_VCN = os.environ.get('DIGITAL_HUMAN_VCN', 'x4_yezi').strip()
    DIGITAL_HUMAN_WIDTH = int(os.environ.get('DIGITAL_HUMAN_WIDTH', '1920'))
    DIGITAL_HUMAN_HEIGHT = int(os.environ.get('DIGITAL_HUMAN_HEIGHT', '1280'))
    DIGITAL_HUMAN_BITRATE = int(os.environ.get('DIGITAL_HUMAN_BITRATE', '1000000'))
    DIGITAL_HUMAN_FPS = int(os.environ.get('DIGITAL_HUMAN_FPS', '25'))
    DIGITAL_HUMAN_PROTOCOL = os.environ.get('DIGITAL_HUMAN_PROTOCOL', 'xrtc').strip().lower()
    DIGITAL_HUMAN_ALPHA = int(os.environ.get('DIGITAL_HUMAN_ALPHA', '1'))
    DIGITAL_HUMAN_AUDIO_FORMAT = int(os.environ.get('DIGITAL_HUMAN_AUDIO_FORMAT', '1'))
    DIGITAL_HUMAN_CONTENT_ANALYSIS = int(os.environ.get('DIGITAL_HUMAN_CONTENT_ANALYSIS', '0'))
    DIGITAL_HUMAN_INTERACTIVE_MODE = int(os.environ.get('DIGITAL_HUMAN_INTERACTIVE_MODE', '2'))
    DIGITAL_HUMAN_TEXT_INTERACTIVE_MODE = int(os.environ.get('DIGITAL_HUMAN_TEXT_INTERACTIVE_MODE', '2'))
    DIGITAL_HUMAN_SCALE = float(os.environ.get('DIGITAL_HUMAN_SCALE', '1'))
    DIGITAL_HUMAN_MOVE_H = int(os.environ.get('DIGITAL_HUMAN_MOVE_H', '0'))
    DIGITAL_HUMAN_MOVE_V = int(os.environ.get('DIGITAL_HUMAN_MOVE_V', '0'))
    DIGITAL_HUMAN_MASK_REGION = os.environ.get('DIGITAL_HUMAN_MASK_REGION', '[0,0,1080,1920]').strip()
    DIGITAL_HUMAN_SDK_ESM_DIR = os.environ.get(
        'DIGITAL_HUMAN_SDK_ESM_DIR',
        os.path.join(BASE_DIR, 'spark digital human', '3.2.1.1016', 'avatar-sdk-web_3.2.1.1016', 'esm')
    )
    
    # 系统设置
    APP_NAME = os.environ.get('APP_NAME', '智能社团+')
    ITEMS_PER_PAGE = int(os.environ.get('ITEMS_PER_PAGE', 10))
    
    # 活动类型
    ACTIVITY_TYPES = ['cultural', 'sports', 'academic', 'volunteer', 'competition', 'other']
    
    # AI API配置
    VOLCANO_API_KEY = os.environ.get('VOLCANO_API_KEY', os.environ.get('ARK_API_KEY', ''))
    VOLCANO_API_URL = os.environ.get('VOLCANO_API_URL', 'https://ark.cn-beijing.volces.com/api/v3/chat/completions')
    # 文本模型统一配置（悬浮窗AI对话、后台AI文案/解析共用）
    AI_TEXT_MODEL = os.environ.get('AI_TEXT_MODEL', 'ep-20260320185026-9cc4w')
    
    # 应用时区配置
    APP_TIMEZONE = os.environ.get('APP_TIMEZONE') or 'Asia/Shanghai'
    logger.info(f"使用时区: {APP_TIMEZONE}")
    
    # 是否允许修改密码（调试用）
    ALLOW_PASSWORD_CHANGE = True
    ENABLE_DEBUG_ENDPOINTS = os.environ.get('ENABLE_DEBUG_ENDPOINTS', 'false').lower() == 'true'
    
    # Flask-WTF配置
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # CSRF令牌有效期（秒）
    
    # AI聊天功能配置
    AI_CHAT_ENABLED = True
    AI_CHAT_CONNECT_TIMEOUT = float(os.environ.get('AI_CHAT_CONNECT_TIMEOUT', 10))
    AI_CHAT_READ_TIMEOUT = float(os.environ.get('AI_CHAT_READ_TIMEOUT', 180))

    # 邮件配置（用于邮箱验证、通知）
    MAIL_PRIMARY_SERVER = os.environ.get('MAIL_PRIMARY_SERVER', 'smtp.mailersend.net')
    MAIL_PRIMARY_PORT = int(os.environ.get('MAIL_PRIMARY_PORT', 587))
    MAIL_PRIMARY_USE_TLS = os.environ.get('MAIL_PRIMARY_USE_TLS', 'true').lower() == 'true'
    MAIL_PRIMARY_USE_SSL = os.environ.get('MAIL_PRIMARY_USE_SSL', 'false').lower() == 'true'
    MAIL_PRIMARY_USERNAME = os.environ.get('MAIL_PRIMARY_USERNAME', '')
    MAIL_PRIMARY_PASSWORD = os.environ.get('MAIL_PRIMARY_PASSWORD', '')
    MAIL_PRIMARY_DEFAULT_SENDER = os.environ.get('MAIL_PRIMARY_DEFAULT_SENDER', MAIL_PRIMARY_USERNAME)

    # 备用通道（沿用现有配置）
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.qq.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
    MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', MAIL_USERNAME)
    MAIL_SUBJECT_PREFIX = os.environ.get('MAIL_SUBJECT_PREFIX', '[智能社团+]')
    
    @classmethod
    def init_app(cls, app):
        """初始化应用配置"""
        # 打印时区信息到日志
        app.logger.info(f"使用数据库: {app.config['SQLALCHEMY_DATABASE_URI']}")
        app.logger.info(f"使用时区: {app.config['TIMEZONE_NAME']}")

class DevelopmentConfig(Config):
    """开发环境配置"""
    DEBUG = True
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'false').lower() == 'true'
    
    # 设置SQLite数据库路径
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        f'sqlite:///{DB_PATH}'

class TestingConfig(Config):
    """测试环境配置"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(INSTANCE_PATH, "cqnu_association_test.db")}'
    WTF_CSRF_ENABLED = False  # 测试环境禁用CSRF验证
    
class ProductionConfig(Config):
    """生产环境配置"""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_REFRESH_EACH_REQUEST = False
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = False
    PREFERRED_URL_SCHEME = 'https'
    
    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        if app.config.get('SECRET_KEY') == 'dev-secret-key-cqnu-association':
            raise RuntimeError('生产环境禁止使用默认SECRET_KEY，请在环境变量中设置安全随机值。')

        required_env_keys = ['SECRET_KEY', 'SECURITY_PASSWORD_SALT']
        missing_keys = [key for key in required_env_keys if not os.environ.get(key)]
        if missing_keys:
            raise RuntimeError(f"生产环境缺少必要环境变量: {', '.join(missing_keys)}")

        insecure_defaults = {
            'SECRET_KEY': 'dev-secret-key-cqnu-association',
            'SECURITY_PASSWORD_SALT': 'cqnu-association-salt'
        }
        for key, insecure_value in insecure_defaults.items():
            if app.config.get(key) == insecure_value:
                raise RuntimeError(f"生产环境禁止使用默认{key}，请在环境变量中配置安全值")
        
        # 生产环境下的额外配置
        import logging
        from logging.handlers import SMTPHandler
        
        # 获取邮件配置
        mail_server = os.environ.get('MAIL_SERVER')
        mail_port = int(os.environ.get('MAIL_PORT', 25))
        mail_sender = os.environ.get('MAIL_SENDER')
        mail_admin = os.environ.get('MAIL_ADMIN')
        mail_username = os.environ.get('MAIL_USERNAME')
        mail_password = os.environ.get('MAIL_PASSWORD')
        
        # 只有当必要的配置都存在时才添加邮件处理器
        if mail_server and mail_sender and mail_admin:
            # 配置邮件错误日志
            mail_handler = SMTPHandler(
                mailhost=(mail_server, mail_port),
                fromaddr=mail_sender,
                toaddrs=[mail_admin],
                subject='应用错误',
                credentials=(mail_username, mail_password) if mail_username and mail_password else None,
                secure=()
            )
            mail_handler.setLevel(logging.ERROR)
            app.logger.addHandler(mail_handler)

# 根据环境变量选择配置
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    
    'default': DevelopmentConfig
}