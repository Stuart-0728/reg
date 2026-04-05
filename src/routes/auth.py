from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from src import db, limiter
from src.models import User, Role, StudentInfo, Tag, AIUserPreferences, SystemLog, Society
from flask_wtf import FlaskForm
from flask_wtf.csrf import validate_csrf
from wtforms import StringField, PasswordField, SubmitField, SelectField, ValidationError
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp
from datetime import datetime, timedelta
import time
from sqlalchemy import or_, func
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from urllib.parse import urlparse, urljoin, parse_qs
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
# 配置日志
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)
_last_unverified_cleanup_at = None


def _student_needs_onboarding(user):
    """学生首次登录分流判定：必须完成至少1个标签 + 至少1个社团选择。"""
    try:
        if not user or not getattr(user, 'role', None):
            return False
        if (getattr(user.role, 'name', '') or '').strip().lower() != 'student':
            return False

        student_info = db.session.execute(
            db.select(StudentInfo).filter_by(user_id=user.id)
        ).scalar_one_or_none()
        if not student_info:
            return True

        selected_tags = list(getattr(student_info, 'tags', []) or [])
        joined_societies = list(getattr(student_info, 'joined_societies', []) or [])

        has_tag_flag = bool(getattr(student_info, 'has_selected_tags', False))
        has_tags = len(selected_tags) > 0
        has_society = bool(getattr(student_info, 'society_id', None)) or len(joined_societies) > 0

        # 兼容历史脏数据：即使 has_selected_tags 被误置为 True，也要求真实标签与社团存在
        return (not has_tag_flag) or (not has_tags) or (not has_society)
    except Exception as e:
        logger.warning(f"检查学生 onboarding 状态失败，按需引导标签页: {e}")
        return True


def _cleanup_unverified_accounts(max_age_days=7, min_interval_minutes=60):
    """定期清理未验证邮箱且超过期限的账号。"""
    global _last_unverified_cleanup_at

    now = datetime.utcnow()
    if _last_unverified_cleanup_at and (now - _last_unverified_cleanup_at) < timedelta(minutes=min_interval_minutes):
        return 0

    _last_unverified_cleanup_at = now
    cutoff = now - timedelta(days=max_age_days)

    try:
        # 只清理未激活、从未登录、创建超过7天的学生账号，避免误删被管理员禁用的历史账号
        stmt = (
            db.select(User)
            .join(Role, User.role_id == Role.id, isouter=True)
            .where(
                User.active.is_(False),
                User.last_login.is_(None),
                User.created_at < cutoff,
                or_(Role.id.is_(None), func.lower(Role.name) == 'student')
            )
            .limit(200)
        )
        expired_users = db.session.execute(stmt).scalars().all()
        if not expired_users:
            return 0

        for user in expired_users:
            db.session.execute(db.text("UPDATE system_logs SET user_id = NULL WHERE user_id = :uid"), {'uid': user.id})
            db.session.execute(db.text("UPDATE announcements SET created_by = NULL WHERE created_by = :uid"), {'uid': user.id})
            db.session.delete(user)

        db.session.commit()
        logger.info(f"自动清理未验证账号完成，删除数量: {len(expired_users)}")
        return len(expired_users)
    except Exception as e:
        db.session.rollback()
        logger.error(f"自动清理未验证账号失败: {e}", exc_info=True)
        return 0


def _build_reset_password_token(user_id):
    user_obj = user_id if hasattr(user_id, 'id') else None
    uid = int(user_obj.id if user_obj else user_id)
    password_hash = (getattr(user_obj, 'password_hash', '') or '')
    password_fingerprint = password_hash[-24:]
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(
        {
            'uid': uid,
            'purpose': 'password-reset',
            'ph': password_fingerprint
        },
        salt=f"{current_app.config.get('SECURITY_PASSWORD_SALT', 'cqnu-association-salt')}:password-reset"
    )


def _build_email_verify_token(user_id, email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(
        {'uid': int(user_id), 'email': str(email or ''), 'purpose': 'email-verify'},
        salt=f"{current_app.config.get('SECURITY_PASSWORD_SALT', 'cqnu-association-salt')}:email-verify"
    )


def _verify_email_token(token, max_age=86400):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(
            token,
            max_age=max_age,
            salt=f"{current_app.config.get('SECURITY_PASSWORD_SALT', 'cqnu-association-salt')}:email-verify"
        )
    except SignatureExpired:
        return None, '邮箱验证链接已过期，请重新发送验证邮件。'
    except BadSignature:
        return None, '邮箱验证链接无效，请重新发送验证邮件。'

    if not isinstance(data, dict) or data.get('purpose') != 'email-verify':
        return None, '邮箱验证链接无效，请重新发送验证邮件。'

    try:
        return {'uid': int(data.get('uid')), 'email': str(data.get('email') or '')}, None
    except Exception:
        return None, '邮箱验证链接无效，请重新发送验证邮件。'


def _mail_provider_configs():
    primary = {
        'name': 'primary',
        'server': current_app.config.get('MAIL_PRIMARY_SERVER', 'smtp.mailersend.net') or 'smtp.mailersend.net',
        'port': int(current_app.config.get('MAIL_PRIMARY_PORT', 587) or 587),
        'username': current_app.config.get('MAIL_PRIMARY_USERNAME') or '',
        'password': current_app.config.get('MAIL_PRIMARY_PASSWORD') or '',
        'use_tls': bool(current_app.config.get('MAIL_PRIMARY_USE_TLS', True)),
        'use_ssl': bool(current_app.config.get('MAIL_PRIMARY_USE_SSL', False)),
        'sender': current_app.config.get('MAIL_PRIMARY_DEFAULT_SENDER') or (current_app.config.get('MAIL_PRIMARY_USERNAME') or '')
    }
    fallback = {
        'name': 'fallback',
        'server': current_app.config.get('MAIL_SERVER') or current_app.config.get('MAIL_HOST') or '',
        'port': int(current_app.config.get('MAIL_PORT', 25) or 25),
        'username': current_app.config.get('MAIL_USERNAME') or '',
        'password': current_app.config.get('MAIL_PASSWORD') or '',
        'use_tls': bool(current_app.config.get('MAIL_USE_TLS', False)),
        'use_ssl': bool(current_app.config.get('MAIL_USE_SSL', False)),
        'sender': current_app.config.get('MAIL_DEFAULT_SENDER') or (current_app.config.get('MAIL_USERNAME') or '')
    }

    providers = []
    if primary['server'] and primary['sender'] and primary['username'] and primary['password']:
        providers.append(primary)

    same_provider = (
        primary['server'] == fallback['server']
        and int(primary['port']) == int(fallback['port'])
        and (primary['username'] or '') == (fallback['username'] or '')
    )
    if fallback['server'] and fallback['sender'] and not same_provider:
        providers.append(fallback)

    return providers


def _send_html_email(subject, recipient, html_body):
    subject_prefix = current_app.config.get('MAIL_SUBJECT_PREFIX', '')
    # 兼容服务器环境变量中文乱码（如 [????]），回退到固定前缀
    if not subject_prefix or ('?' in str(subject_prefix) and '智能社团+' not in str(subject_prefix)):
        subject_prefix = '[智能社团+]'

    providers = _mail_provider_configs()
    if not providers:
        raise RuntimeError('邮件配置不完整，请检查 MAIL_PRIMARY_* 或 MAIL_* 配置')

    last_error = None
    for provider in providers:
        sender = provider.get('sender') or provider.get('username')
        if isinstance(sender, (list, tuple)):
            sender = sender[1] if len(sender) > 1 else sender[0]
        if not (provider.get('server') and sender and recipient):
            continue

        message = MIMEMultipart('alternative')
        message['Subject'] = Header(f"{subject_prefix}{subject}", 'utf-8').encode()
        message['From'] = sender
        message['To'] = recipient
        message.attach(MIMEText(html_body, 'html', 'utf-8'))

        smtp = None
        try:
            if provider.get('use_ssl'):
                smtp = smtplib.SMTP_SSL(provider['server'], int(provider['port']), timeout=20)
            else:
                smtp = smtplib.SMTP(provider['server'], int(provider['port']), timeout=20)
                smtp.ehlo()
                if provider.get('use_tls'):
                    smtp.starttls()
                    smtp.ehlo()

            if provider.get('username') and provider.get('password'):
                smtp.login(provider['username'], provider['password'])

            smtp.sendmail(sender, [recipient], message.as_string())
            logger.info(f"邮件发送成功: provider={provider.get('name')}, recipient={recipient}")
            return
        except Exception as e:
            last_error = e
            logger.warning(f"邮件发送失败，准备切换下一个提供商: provider={provider.get('name')}, error={e}")
        finally:
            if smtp:
                try:
                    smtp.quit()
                except Exception:
                    pass

    raise RuntimeError(f"邮件发送失败: {last_error}")


def _send_verification_email(user):
    token = _build_email_verify_token(user.id, user.email)
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    html_body = render_template('email/verify_email.html', user=user, verify_url=verify_url)
    _send_html_email('邮箱验证', user.email, html_body)
    return verify_url


def _send_password_reset_email(user):
    token = _build_reset_password_token(user)
    reset_url = url_for('auth.reset_password_with_token', token=token, _external=True)
    html_body = render_template('email/reset_password.html', user=user, reset_url=reset_url)
    _send_html_email('密码重置', user.email, html_body)
    return reset_url


def _verify_reset_password_token(token, max_age=7200):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(
            token,
            max_age=max_age,
            salt=f"{current_app.config.get('SECURITY_PASSWORD_SALT', 'cqnu-association-salt')}:password-reset"
        )
    except SignatureExpired:
        return None, '重置链接已过期，请重新提交邮箱重置申请。'
    except BadSignature:
        return None, '重置链接无效，请重新提交邮箱重置申请。'

    if not isinstance(data, dict) or data.get('purpose') != 'password-reset':
        return None, '重置链接无效，请重新提交邮箱重置申请。'

    uid = data.get('uid')
    password_fingerprint = str(data.get('ph') or '')
    try:
        return {'uid': int(uid), 'ph': password_fingerprint}, None
    except Exception:
        return None, '重置链接无效，请重新提交邮箱重置申请。'

def _is_safe_next_url(target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


def _resolve_post_login_next(next_page, user):
    """将公共活动详情页回跳转换为学生活动详情页，支持自动报名意图参数。"""
    if not next_page or not user:
        return next_page

    role_name = (getattr(getattr(user, 'role', None), 'name', '') or '').strip().lower()
    if role_name != 'student':
        return next_page

    try:
        parsed = urlparse(urljoin(request.host_url, next_page))
        path_parts = [part for part in parsed.path.split('/') if part]
        if len(path_parts) != 2 or path_parts[0] != 'activity' or not path_parts[1].isdigit():
            return next_page

        activity_id = int(path_parts[1])
        query = parse_qs(parsed.query, keep_blank_values=True)
        auto_register = str((query.get('auto_register') or ['0'])[0]).strip().lower() in ('1', 'true', 'yes')

        student_detail_url = url_for('student.activity_detail', id=activity_id)
        if auto_register:
            return f'{student_detail_url}?auto_register=1'
        return student_detail_url
    except Exception as e:
        logger.warning(f"解析登录回跳地址失败，保留原next参数: {e}")
        return next_page


def _build_logout_response(message='您已成功登出！', category='success', logged_out=1, password_changed=0):
    """统一构造登出响应，确保会话与认证cookie完全清理。"""
    logout_user()
    session.clear()

    if message:
        flash(message, category)

    response = redirect(url_for(
        'auth.login',
        logged_out=logged_out,
        password_changed=password_changed,
        t=int(time.time())
    ))

    # 显式删除认证cookie（双保险）
    response.delete_cookie(current_app.config.get('SESSION_COOKIE_NAME', 'session'), path='/')
    response.delete_cookie('remember_token', path='/')

    # 清理AI聊天相关cookie，避免切换账号后残留历史上下文
    response.delete_cookie('cqnu_ai_chat_session_id', path='/')
    response.delete_cookie('cqnu_ai_chat_messages', path='/')
    response.delete_cookie('cqnu_ai_chat_chat_open', path='/')

    # 防止浏览器/代理缓存登出前页面
    response.headers['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Clear-Site-Data'] = '"cache"'
    return response

# 注册表单
class RegistrationForm(FlaskForm):
    username = StringField('用户名', validators=[
        DataRequired(message='用户名不能为空'),
        Length(min=3, max=20, message='用户名长度必须在3-20个字符之间'),
        Regexp('^[A-Za-z0-9_]*$', message='用户名只能包含字母、数字和下划线')
    ])
    email = StringField('邮箱', validators=[
        DataRequired(message='邮箱不能为空'),
        Email(message='请输入有效的邮箱地址')
    ])
    password = PasswordField('密码', validators=[
        DataRequired(message='密码不能为空'),
        Length(min=6, message='密码长度不能少于6个字符')
    ])
    confirm_password = PasswordField('确认密码', validators=[
        DataRequired(message='确认密码不能为空'),
        EqualTo('password', message='两次输入的密码不一致')
    ])
    real_name = StringField('姓名', validators=[DataRequired(message='姓名不能为空')])
    student_id = StringField('学号', validators=[
        DataRequired(message='学号不能为空'),
        Length(min=5, max=20, message='请输入有效的学号')
    ])
    grade = StringField('年级', validators=[DataRequired(message='年级不能为空')])
    major = StringField('专业', validators=[DataRequired(message='专业不能为空')])
    college = StringField('学院', validators=[DataRequired(message='学院不能为空')])
    phone = StringField('手机号', validators=[
        DataRequired(message='手机号不能为空'),
        Regexp(r'^1[3-9][0-9]{9}$', message='请输入有效的手机号码')
    ])
    qq = StringField('QQ号', validators=[
        DataRequired(message='QQ号不能为空'),
        Regexp(r'^[0-9]{5,12}$', message='请输入有效的QQ号码')
    ])
    submit = SubmitField('注册')

    def validate_username(self, field):
        stmt = db.select(User).filter_by(username=field.data)
        if db.session.execute(stmt).scalar_one_or_none():
            raise ValidationError('该用户名已被注册')

    def validate_email(self, field):
        stmt = db.select(User).filter_by(email=field.data)
        if db.session.execute(stmt).scalar_one_or_none():
            raise ValidationError('该邮箱已被注册')
            
    def validate_student_id(self, field):
        stmt = db.select(StudentInfo).filter_by(student_id=field.data)
        if db.session.execute(stmt).scalar_one_or_none():
            raise ValidationError('该学号已被注册')

    def validate_phone(self, field):
        stmt = db.select(StudentInfo).filter(StudentInfo.phone == field.data)
        if db.session.execute(stmt).scalar_one_or_none():
            raise ValidationError('该手机号已被注册')

# 登录表单
class LoginForm(FlaskForm):
    username = StringField('账号', validators=[DataRequired(message='账号不能为空')])
    password = PasswordField('密码', validators=[DataRequired(message='密码不能为空')])
    submit = SubmitField('登录')

# 管理员设置表单
class SetupAdminForm(FlaskForm):
    username = StringField('管理员用户名', validators=[
        DataRequired(message='用户名不能为空'),
        Length(min=3, max=20, message='用户名长度必须在3-20个字符之间'),
        Regexp('^[A-Za-z0-9_]*$', message='用户名只能包含字母、数字和下划线')
    ])
    email = StringField('管理员邮箱', validators=[
        DataRequired(message='邮箱不能为空'),
        Email(message='请输入有效的邮箱地址')
    ])
    password = PasswordField('密码', validators=[
        DataRequired(message='密码不能为空'),
        Length(min=6, message='密码长度不能少于6个字符')
    ])
    confirm_password = PasswordField('确认密码', validators=[
        DataRequired(message='确认密码不能为空'),
        EqualTo('password', message='两次输入的密码不一致')
    ])
    submit = SubmitField('创建管理员')

    def validate_username(self, field):
        stmt = db.select(User).filter_by(username=field.data)
        if db.session.execute(stmt).scalar_one_or_none():
            raise ValidationError('该用户名已被注册')

    def validate_email(self, field):
        stmt = db.select(User).filter_by(email=field.data)
        if db.session.execute(stmt).scalar_one_or_none():
            raise ValidationError('该邮箱已被注册')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    _cleanup_unverified_accounts(max_age_days=7)

    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        # 获取学生角色
        stmt = db.select(Role).filter_by(name='Student')
        student_role = db.session.execute(stmt).scalar_one_or_none()
        if not student_role:
            student_role = Role(name='Student')
            db.session.add(student_role)
            db.session.commit()
        
        # 创建用户
        user = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            role=student_role,
            active=False
        )
        db.session.add(user)
        db.session.flush()  # 获取用户ID
        
        # 创建学生信息
        student_info = StudentInfo(
            user_id=user.id,
            real_name=form.real_name.data,
            student_id=form.student_id.data,
            grade=form.grade.data,
            major=form.major.data,
            college=form.college.data,
            phone=form.phone.data,
            qq=form.qq.data,
            has_selected_tags=False
        )
        db.session.add(student_info)
        
        # 创建AI用户偏好设置
        ai_preferences = AIUserPreferences(
            user_id=user.id,
            enable_history=True,
            max_history_count=50
        )
        db.session.add(ai_preferences)
        
        db.session.commit()

        try:
            _send_verification_email(user)
        except Exception as e:
            logger.error(f"发送邮箱验证邮件失败: user_id={user.id}, error={e}", exc_info=True)
            flash('注册成功，但验证邮件发送失败，请稍后在登录页重新发送验证邮件。', 'warning')
            return redirect(url_for('auth.login'))

        flash('注册成功！验证邮件已发送，请先完成邮箱验证再登录。', 'success')
        return redirect(url_for('auth.verify_email_pending', user_id=user.id))
    
    return render_template('auth/register.html', form=form)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    _cleanup_unverified_accounts(max_age_days=7)

    # 如果用户已登录，直接重定向到主页
    if current_user.is_authenticated:
        if _student_needs_onboarding(current_user):
            return redirect(url_for('auth.select_tags'))
        return redirect(url_for('main.index'))
        
    form = LoginForm()
    
    # 如果是GET请求，直接显示登录表单
    if request.method == 'GET':
        # 检查是否是AI聊天历史请求导致的重定向
        next_param = request.args.get('next', '')
        if '/utils/ai_chat/history' in next_param:
            # 移除可能导致循环的next参数
            logger.warning(f"检测到AI聊天历史重定向循环: {next_param}")
            return render_template('auth/login.html', form=form, remove_next=True)
        return render_template('auth/login.html', form=form)
    
    # 如果是POST请求，处理表单提交
    if form.validate_on_submit():
        identifier = (form.username.data or '').strip()
        password = form.password.data
        
        logger.info(f"尝试登录: 账号标识={identifier}")
        
        try:
            # 支持使用用户名、邮箱、学号、手机号登录。
            # 安全修复：若登录标识在不同字段上命中多个账号，不再取“第一条”，
            # 而是用密码在候选集中做唯一匹配，避免误登他人账号。
            stmt = (
                db.select(User)
                .outerjoin(StudentInfo, StudentInfo.user_id == User.id)
                .where(
                    or_(
                        User.username == identifier,
                        User.email == identifier,
                        StudentInfo.student_id == identifier,
                        StudentInfo.phone == identifier
                    )
                )
                .order_by(User.id.asc())
            )
            candidates = db.session.execute(stmt).scalars().all()
            matched_users = [u for u in candidates if u and u.verify_password(password)]

            if len(matched_users) > 1:
                logger.warning(
                    f"登录歧义冲突: 标识={identifier}, 候选数={len(candidates)}, 密码匹配数={len(matched_users)}"
                )
                flash('检测到登录标识冲突，请改用邮箱或手机号登录。', 'danger')
                return render_template('auth/login.html', form=form)

            user = matched_users[0] if len(matched_users) == 1 else None

            if user:
                # 检查用户是否激活
                if not user.active:
                    flash('账号尚未通过邮箱验证，请先完成邮箱验证。', 'warning')
                    return redirect(url_for('auth.verify_email_pending', user_id=user.id))

                # 登录成功后按需迁移历史密码哈希算法
                if hasattr(user, 'needs_password_rehash') and user.needs_password_rehash():
                    try:
                        user.password = password
                        db.session.commit()
                        logger.info(f"密码哈希已迁移: 用户ID={user.id}")
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"密码哈希迁移失败: {e}", exc_info=True)
                
                # 登录成功
                login_user(user, remember=True, duration=timedelta(days=30))
                # 显式标记为持久会话：仅在主动登出时清除
                session.permanent = True
                
                # 记录登录成功日志
                logger.info(f"登录成功: 账号标识={identifier}, 用户ID={user.id}")
                
                # 添加系统日志
                log = SystemLog(
                    user_id=user.id,
                    action="用户登录",
                    details=f"账号标识 {identifier} 登录成功",
                    ip_address=request.remote_addr
                )
                db.session.add(log)
                # 安全提交：失败时回滚并不中断登录流程
                try:
                    db.session.commit()
                except Exception as e:
                    logger.error(f"记录系统日志失败，已回滚: {e}", exc_info=True)
                    db.session.rollback()
                
                # 检查next参数是否安全，避免重定向循环
                next_page = request.form.get('next')
                if next_page and '/utils/ai_chat/history' in next_page:
                    logger.warning(f"阻止重定向到AI聊天历史: {next_page}")
                    next_page = url_for('main.index')
                next_page = _resolve_post_login_next(next_page, user)

                # 学生首次登录（尚未选择标签）强制进入标签选择页
                try:
                    if _student_needs_onboarding(user):
                        return redirect(url_for('auth.select_tags'))
                except Exception as e:
                    logger.warning(f"检查标签/社团选择状态失败，继续常规登录跳转: {e}")
                
                # 如果有next参数，则重定向到next页面
                if next_page and next_page != 'None' and next_page != url_for('auth.login') and _is_safe_next_url(next_page):
                    logger.info(f"重定向到: {next_page}")
                    return redirect(next_page)
                
                # 否则重定向到主页
                return redirect(url_for('main.index'))
            else:
                # 登录失败
                logger.warning(f"登录失败: 账号标识={identifier}, 原因=账号或密码错误")
                flash('账号或密码错误，请重试。', 'danger')
        except Exception as e:
            # 处理异常
            logger.error(f"登录过程中发生错误: {str(e)}", exc_info=True)
            flash('登录过程中发生错误，请稍后重试。', 'danger')
    
    # 表单验证失败或登录失败，返回登录页面
    return render_template('auth/login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    """用户登出"""
    return _build_logout_response(message='您已成功登出！', category='success', logged_out=1)


@auth_bp.route('/session-state')
@limiter.exempt
def session_state():
    """返回当前会话登录态，用于前端纠正被CDN缓存污染的头部显示。"""
    def _safe_url(endpoint, fallback=''):
        try:
            return url_for(endpoint)
        except Exception:
            return fallback

    role_name = ''
    display_name = ''
    dashboard_url = _safe_url('main.index', '/')
    is_super = False
    can_enter_student_mode = False
    admin_student_mode = False
    managed_society_id = None
    managed_society_name = ''
    authenticated = bool(current_user.is_authenticated)

    try:
        if authenticated:
            try:
                role_name = (current_user.role.name or '').strip().lower() if current_user.role else ''
            except Exception:
                role_name = ''

            if role_name == 'admin':
                dashboard_url = _safe_url('admin.dashboard', dashboard_url)
                display_name = current_user.username or '管理员'
                is_super = bool(getattr(current_user, 'is_super_admin', False))
                can_enter_student_mode = not is_super
                admin_student_mode = bool(session.get('admin_student_mode')) and can_enter_student_mode
                managed_society_id = getattr(current_user, 'managed_society_id', None)
                if managed_society_id:
                    society = db.session.get(Society, managed_society_id)
                    managed_society_name = society.name if society else ''
            else:
                dashboard_url = _safe_url('student.dashboard', dashboard_url)
                student_info = getattr(current_user, 'student_info', None)
                student_name = getattr(student_info, 'real_name', None) if student_info else None
                display_name = student_name or (current_user.username or '用户')
    except Exception as e:
        logger.error(f"session_state 构建失败，返回降级结果: {e}", exc_info=True)

    response = jsonify({
        'success': True,
        'authenticated': authenticated,
        'role': role_name,
        'is_super_admin': is_super,
        'can_enter_student_mode': can_enter_student_mode,
        'admin_student_mode': admin_student_mode,
        'managed_society_id': managed_society_id,
        'managed_society_name': managed_society_name,
        'display_name': display_name,
        'urls': {
            'login': _safe_url('auth.login'),
            'register': _safe_url('auth.register'),
            'logout': _safe_url('auth.logout'),
            'change_password': _safe_url('auth.change_password'),
            'dashboard': dashboard_url,
            'profile': (_safe_url('student.profile', dashboard_url) if role_name == 'student' else dashboard_url),
            'messages': (_safe_url('admin.messages') if role_name == 'admin' else ''),
            'societies': (_safe_url('admin.manage_societies') if role_name == 'admin' and is_super else ''),
            'select_society': (_safe_url('admin.select_admin_society') if role_name == 'admin' and not is_super else ''),
            'student_dashboard': (_safe_url('student.dashboard') if role_name == 'admin' else ''),
            'enter_student_mode': (_safe_url('student.enter_student_mode') if role_name == 'admin' and can_enter_student_mode else ''),
            'exit_student_mode': (_safe_url('student.exit_student_mode') if role_name == 'admin' and can_enter_student_mode else ''),
        }
    })

    response.headers['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0, s-maxage=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['Surrogate-Control'] = 'no-store'
    response.headers['Vary'] = 'Cookie, Authorization'
    return response

@auth_bp.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html')

@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    class ChangePasswordForm(FlaskForm):
        old_password = PasswordField('当前密码', validators=[DataRequired(message='当前密码不能为空')])
        new_password = PasswordField('新密码', validators=[
            DataRequired(message='新密码不能为空'),
            Length(min=6, message='密码长度不能少于6个字符')
        ])
        confirm_password = PasswordField('确认新密码', validators=[
            DataRequired(message='确认密码不能为空'),
            EqualTo('new_password', message='两次输入的密码不一致')
        ])
        submit = SubmitField('修改密码')
    
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if current_user.verify_password(form.old_password.data):
            current_user.password_hash = generate_password_hash(form.new_password.data)
            db.session.commit()
            # 改密后强制下线，避免旧会话继续有效
            return _build_logout_response(
                message='密码修改成功，请重新登录。',
                category='success',
                logged_out=0,
                password_changed=1
            )
        else:
            flash('当前密码错误！', 'danger')
    
    return render_template('auth/change_password.html', form=form)


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    class ResetPasswordForm(FlaskForm):
        new_password = PasswordField('新密码', validators=[
            DataRequired(message='新密码不能为空'),
            Length(min=6, message='密码长度不能少于6个字符')
        ])
        confirm_password = PasswordField('确认新密码', validators=[
            DataRequired(message='确认密码不能为空'),
            EqualTo('new_password', message='两次输入的密码不一致')
        ])
        submit = SubmitField('确认重置密码')

    token_data, error = _verify_reset_password_token(token)
    if error:
        flash(error, 'danger')
        return redirect(url_for('auth.login'))

    user_id = token_data['uid']
    user = db.session.get(User, user_id)
    if not user or not user.active:
        flash('账号不存在或已被禁用，请联系管理员。', 'danger')
        return redirect(url_for('auth.login'))

    current_fingerprint = (user.password_hash or '')[-24:]
    if token_data.get('ph') != current_fingerprint:
        flash('该重置链接已失效或已被使用，请重新提交邮箱重置申请。', 'danger')
        return redirect(url_for('auth.login'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            user.password_hash = generate_password_hash(form.new_password.data, method='pbkdf2:sha256')
            db.session.commit()
            flash('密码已重置，请使用新密码登录。', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"通过重置链接设置新密码失败: user_id={user.id}, error={e}", exc_info=True)
            flash('重置密码失败，请稍后重试。', 'danger')

    return render_template('auth/reset_password_by_token.html', form=form, user=user)


@auth_bp.route('/request-password-reset', methods=['POST'])
@limiter.limit('8 per hour', methods=['POST'], error_message='请求过于频繁，请稍后再试')
def request_password_reset():
    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新后重试。', 'danger')
        return redirect(url_for('auth.login'))

    identifier = (request.form.get('identifier') or '').strip()
    if not identifier:
        flash('请输入注册邮箱或用户名。', 'warning')
        return redirect(url_for('auth.login'))

    user = db.session.execute(
        db.select(User).outerjoin(StudentInfo, StudentInfo.user_id == User.id).where(
            or_(
                User.email == identifier,
                User.username == identifier,
                StudentInfo.student_id == identifier,
                StudentInfo.phone == identifier
            )
        ).limit(1)
    ).scalars().first()

    # 安全策略：避免账号枚举，对外统一提示
    generic_message = '如果账号存在且已完成邮箱验证，重置链接已发送到该账号邮箱，请查收。'

    if user and user.email and user.active:
        try:
            _send_password_reset_email(user)
            logger.info(f"已发送密码重置邮件: user_id={user.id}, email={user.email}")
        except Exception as e:
            logger.error(f"发送密码重置邮件失败: user_id={user.id}, error={e}", exc_info=True)

    flash(generic_message, 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/setup-admin', methods=['GET', 'POST'])
def setup_admin():
    # 检查是否已存在管理员账户
    admin_role_stmt = db.select(Role).filter_by(name='Admin')
    admin_role = db.session.execute(admin_role_stmt).scalar_one_or_none()
    
    if admin_role:
        admin_exists_stmt = db.select(User).filter_by(role_id=admin_role.id)
        admin_exists = db.session.execute(admin_exists_stmt).scalar_one_or_none()
        if admin_exists:
            flash('管理员账户已存在，无需重复设置。', 'warning')
            return redirect(url_for('auth.login'))
    
    form = SetupAdminForm()
    if form.validate_on_submit():
        # 创建管理员角色（如果不存在）
        if not admin_role:
            admin_role = Role(name='Admin', description='管理员')
            db.session.add(admin_role)
            db.session.commit()
        
        # 创建管理员用户
        admin = User(
            username=form.username.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            role_id=admin_role.id,
            active=True
        )
        db.session.add(admin)
        db.session.commit()
        
        flash('管理员账户创建成功！请登录。', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/admin_signup.html', form=form)


@auth_bp.route('/verify-email-pending')
def verify_email_pending():
    user_id = request.args.get('user_id', type=int)
    user = db.session.get(User, user_id) if user_id else None
    return render_template('auth/verify_email_pending.html', user=user)


@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    token_data, error = _verify_email_token(token)
    if error:
        return render_template('auth/verify_email_failed.html', reason=error), 400

    user = db.session.get(User, token_data['uid'])
    if not user or not user.email:
        return render_template('auth/verify_email_failed.html', reason='用户不存在或邮箱信息缺失。'), 400

    if user.email != token_data['email']:
        return render_template('auth/verify_email_failed.html', reason='验证信息不匹配，请重新发送验证邮件。'), 400

    if user.active:
        return render_template('auth/verify_email_success.html', already_verified=True, user=user)

    try:
        user.active = True
        db.session.commit()
        return render_template('auth/verify_email_success.html', already_verified=False, user=user)
    except Exception as e:
        db.session.rollback()
        logger.error(f"邮箱验证落库失败: user_id={user.id}, error={e}", exc_info=True)
        return render_template('auth/verify_email_failed.html', reason='系统繁忙，验证状态保存失败，请稍后重试。'), 500


@auth_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    user_id = request.form.get('user_id', type=int)
    user = db.session.get(User, user_id) if user_id else None

    identifier = (request.form.get('identifier') or '').strip()
    if not user and not identifier:
        flash('请输入用户名或邮箱后再重发验证邮件。', 'warning')
        return redirect(url_for('auth.login'))

    if not user:
        stmt = db.select(User).where(or_(User.username == identifier, User.email == identifier)).limit(1)
        user = db.session.execute(stmt).scalars().first()
    if not user:
        flash('未找到对应账号，请检查后重试。', 'warning')
        return redirect(url_for('auth.login'))

    if user.active:
        flash('该账号已完成邮箱验证，无需重复发送。', 'info')
        return redirect(url_for('auth.login'))

    try:
        _send_verification_email(user)
        flash('验证邮件已重新发送，请查收邮箱。', 'success')
    except Exception as e:
        logger.error(f"重发邮箱验证邮件失败: user_id={user.id}, error={e}", exc_info=True)
        flash('重发失败，请稍后再试。', 'danger')

    return redirect(url_for('auth.verify_email_pending', user_id=user.id))

@auth_bp.route('/select-tags', methods=['GET', 'POST'])
@login_required
def select_tags():
    # 只有学生用户可以选择标签
    if not current_user.is_student:
        flash('只有学生用户可以选择标签', 'warning')
        return redirect(url_for('main.index'))
    
    # 获取学生信息
    stmt = db.select(StudentInfo).filter_by(user_id=current_user.id)
    student_info = db.session.execute(stmt).scalar_one_or_none()
    
    if not student_info:
        flash('找不到学生信息', 'danger')
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        # 获取选择的标签ID
        selected_tags = request.form.getlist('tags')
        selected_societies = request.form.getlist('societies')
        
        if not selected_tags:
            flash('请至少选择一个标签', 'warning')
            tags_stmt = db.select(Tag)
            tags = db.session.execute(tags_stmt).scalars().all()
            societies = db.session.execute(db.select(Society).filter_by(is_active=True).order_by(Society.name.asc())).scalars().all()
            selected_society_ids = [int(sid) for sid in selected_societies if sid and str(sid).isdigit()]
            return render_template('auth/select_tags.html', tags=tags, societies=societies, selected_society_ids=selected_society_ids)

        if not selected_societies:
            flash('请至少选择一个社团', 'warning')
            tags_stmt = db.select(Tag)
            tags = db.session.execute(tags_stmt).scalars().all()
            societies = db.session.execute(db.select(Society).filter_by(is_active=True).order_by(Society.name.asc())).scalars().all()
            selected_tag_ids = [int(tid) for tid in selected_tags if tid and str(tid).isdigit()]
            return render_template('auth/select_tags.html', tags=tags, selected_tag_ids=selected_tag_ids, societies=societies, selected_society_ids=[])
        
        # 清除现有标签
        student_info.tags = []
        
        # 添加新标签
        for tag_id in selected_tags:
            tag_stmt = db.select(Tag).filter_by(id=int(tag_id))
            tag = db.session.execute(tag_stmt).scalar_one_or_none()
            if tag:
                student_info.tags.append(tag)

        # 学生手动选择加入社团（可多选），该规则优先于自动并入
        society_ids = [int(sid) for sid in selected_societies if sid and str(sid).isdigit()]
        societies = db.session.execute(
            db.select(Society).filter(Society.id.in_(society_ids), Society.is_active == True)
        ).scalars().all() if society_ids else []
        student_info.joined_societies = societies
        if societies:
            student_info.society_id = societies[0].id
        else:
            student_info.society_id = None
        
        # 标记为已选择标签
        student_info.has_selected_tags = True
        db.session.commit()
        
        flash('标签设置成功！', 'success')
        return redirect(url_for('student.dashboard'))
    
    # GET请求，显示标签选择页面
    tags_stmt = db.select(Tag)
    tags = db.session.execute(tags_stmt).scalars().all()
    societies = db.session.execute(db.select(Society).filter_by(is_active=True).order_by(Society.name.asc())).scalars().all()
    
    # 获取已选择的标签
    selected_tag_ids = [tag.id for tag in student_info.tags] if student_info.tags else []
    selected_society_ids = [s.id for s in (student_info.joined_societies or [])]
    if student_info.society_id and student_info.society_id not in selected_society_ids:
        selected_society_ids.append(student_info.society_id)
    
    return render_template('auth/select_tags.html', tags=tags, selected_tag_ids=selected_tag_ids, societies=societies, selected_society_ids=selected_society_ids)


# ==================== 微信小程序登录接口 ====================

@auth_bp.route('/wx-login', methods=['POST'])
@limiter.limit('20 per minute')
def wechat_login():
    """
    微信小程序登录接口
    
    Request:
    {
        "code": "微信授权码"
    }
    
    Response:
    {
        "success": true,
        "user_id": 123,
        "username": "用户名",
        "email": "邮箱",
        "student_id": "学号",
        "session_token": "Bearer token",
        "is_new_user": false
    }
    """
    import requests
    import json
    from itsdangerous import TimedJSONWebSignatureSerializer
    
    try:
        data = request.get_json()
        code = data.get('code') if data else None
        
        if not code:
            return jsonify({'success': False, 'msg': '缺少微信授权码'}), 400
        
        # 调用微信API获取session_key和openid
        wx_app_id = current_app.config.get('WX_MINI_APP_ID', '')
        wx_app_secret = current_app.config.get('WX_MINI_APP_SECRET', '')
        
        if not wx_app_id or not wx_app_secret:
            logger.error("微信小程序配置不完整")
            return jsonify({'success': False, 'msg': '服务配置错误'}), 500
        
        # 请求微信 API
        wx_api_url = 'https://api.weixin.qq.com/sns/jscode2session'
        wx_params = {
            'appid': wx_app_id,
            'secret': wx_app_secret,
            'js_code': code,
            'grant_type': 'authorization_code'
        }
        
        wx_response = requests.get(wx_api_url, params=wx_params, timeout=5)
        wx_data = wx_response.json()
        
        if wx_response.status_code != 200 or 'errcode' in wx_data:
            error_msg = wx_data.get('errmsg', '微信登录失败')
            logger.error(f"微信API错误: {error_msg}")
            return jsonify({'success': False, 'msg': error_msg}), 400
        
        openid = wx_data.get('openid')
        session_key = wx_data.get('session_key')
        
        if not openid:
            return jsonify({'success': False, 'msg': '获取openid失败'}), 400
        
        # 查找或创建用户
        user = db.session.execute(
            db.select(User).filter_by(username=f"wx_{openid}")
        ).scalar_one_or_none()
        
        if not user:
            # 创建新用户
            user = User(
                username=f"wx_{openid}",
                email=f"{openid}@weixin.local",
                password_hash=generate_password_hash(''),  # 微信用户无密码
                active=True,  # 微信登录自动激活
                is_super_admin=False
            )
            
            # 关联学生角色
            student_role = db.session.execute(
                db.select(Role).filter_by(name='Student')
            ).scalar_one_or_none()
            
            if student_role:
                user.role_id = student_role.id
            
            db.session.add(user)
            db.session.commit()
            
            # 创建学生信息记录
            student_info = StudentInfo(
                user_id=user.id,
                has_selected_tags=False
            )
            db.session.add(student_info)
            db.session.commit()
            
            logger.info(f"新建微信用户: openid={openid}, user_id={user.id}")
            is_new_user = True
        else:
            is_new_user = False
            logger.info(f"微信用户登录: openid={openid}, user_id={user.id}")
        
        # 生成会话token（用于小程序API认证）
        serializer = TimedJSONWebSignatureSerializer(
            current_app.config['SECRET_KEY'],
            expires_in=7 * 24 * 3600  # 7天有效期
        )
        session_token = serializer.dumps({'user_id': user.id, 'openid': openid})
        
        # 记录登录日志
        log = SystemLog(
            user_id=user.id,
            action="微信登录",
            details=f"openid={openid}",
            ip_address=request.remote_addr
        )
        db.session.add(log)
        try:
            db.session.commit()
        except Exception as e:
            logger.error(f"记录登录日志失败: {e}")
            db.session.rollback()
        
        return jsonify({
            'success': True,
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'student_id': user.student_info.student_id if user.student_info else None,
            'session_token': session_token,
            'is_new_user': is_new_user
        }), 200
        
    except requests.RequestException as e:
        logger.error(f"调用微信API失败: {e}")
        return jsonify({'success': False, 'msg': '网络连接失败'}), 500
    except Exception as e:
        logger.error(f"微信登录处理异常: {e}", exc_info=True)
        return jsonify({'success': False, 'msg': '登录失败，请重试'}), 500


@auth_bp.route('/session-token-validate', methods=['POST'])
@limiter.limit('60 per minute')
def validate_session_token():
    """
    验证小程序session token有效性
    
    Request Header:
    Authorization: Bearer {session_token}
    
    Response:
    {
        "valid": true,
        "user_id": 123,
        "username": "用户名"
    }
    """
    from itsdangerous import BadSignature, SignatureExpired, TimedJSONWebSignatureSerializer
    
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'valid': False, 'msg': '无效的授权头'}), 401
        
        token = auth_header[7:]  # 移除 'Bearer ' 前缀
        
        serializer = TimedJSONWebSignatureSerializer(
            current_app.config['SECRET_KEY'],
            expires_in=7 * 24 * 3600
        )
        
        try:
            data = serializer.loads(token)
            user_id = data.get('user_id')
            user = db.session.get(User, user_id)
            
            if user and user.active:
                return jsonify({
                    'valid': True,
                    'user_id': user.id,
                    'username': user.username
                }), 200
            else:
                return jsonify({'valid': False, 'msg': '用户不存在或已禁用'}), 401
        
        except SignatureExpired:
            return jsonify({'valid': False, 'msg': 'token已过期'}), 401
        except BadSignature:
            return jsonify({'valid': False, 'msg': '无效的token'}), 401
    
    except Exception as e:
        logger.error(f"验证token异常: {e}")
        return jsonify({'valid': False, 'msg': '验证失败'}), 500

