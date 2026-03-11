from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from src import db
from src.models import User, Role, StudentInfo, Tag, AIUserPreferences, SystemLog
from flask_wtf import FlaskForm
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
from urllib.parse import urlparse, urljoin
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
# 配置日志
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)
_last_unverified_cleanup_at = None


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
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(
        {'uid': int(user_id), 'purpose': 'password-reset'},
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


def _send_html_email(subject, recipient, html_body):
    mail_server = current_app.config.get('MAIL_SERVER') or current_app.config.get('MAIL_HOST')
    mail_port = int(current_app.config.get('MAIL_PORT', 25) or 25)
    mail_username = current_app.config.get('MAIL_USERNAME')
    mail_password = current_app.config.get('MAIL_PASSWORD')
    mail_use_tls = bool(current_app.config.get('MAIL_USE_TLS', False))
    mail_use_ssl = bool(current_app.config.get('MAIL_USE_SSL', False))
    subject_prefix = current_app.config.get('MAIL_SUBJECT_PREFIX', '')
    # 兼容服务器环境变量中文乱码（如 [????]），回退到固定前缀
    if not subject_prefix or ('?' in str(subject_prefix) and '重庆师范大学智能社团+' not in str(subject_prefix)):
        subject_prefix = '[重庆师范大学智能社团+]'

    sender = current_app.config.get('MAIL_DEFAULT_SENDER') or mail_username
    if isinstance(sender, (list, tuple)):
        sender = sender[1] if len(sender) > 1 else sender[0]

    if not (mail_server and sender and recipient):
        raise RuntimeError('邮件配置不完整，请检查 MAIL_SERVER / MAIL_USERNAME / MAIL_DEFAULT_SENDER')

    message = MIMEMultipart('alternative')
    message['Subject'] = Header(f"{subject_prefix}{subject}", 'utf-8').encode()
    message['From'] = sender
    message['To'] = recipient
    message.attach(MIMEText(html_body, 'html', 'utf-8'))

    smtp = None
    try:
        if mail_use_ssl:
            smtp = smtplib.SMTP_SSL(mail_server, mail_port, timeout=20)
        else:
            smtp = smtplib.SMTP(mail_server, mail_port, timeout=20)
            smtp.ehlo()
            if mail_use_tls:
                smtp.starttls()
                smtp.ehlo()

        if mail_username and mail_password:
            smtp.login(mail_username, mail_password)

        smtp.sendmail(sender, [recipient], message.as_string())
    finally:
        if smtp:
            try:
                smtp.quit()
            except Exception:
                pass


def _send_verification_email(user):
    token = _build_email_verify_token(user.id, user.email)
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    html_body = render_template('email/verify_email.html', user=user, verify_url=verify_url)
    _send_html_email('邮箱验证', user.email, html_body)
    return verify_url


def _verify_reset_password_token(token, max_age=7200):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(
            token,
            max_age=max_age,
            salt=f"{current_app.config.get('SECURITY_PASSWORD_SALT', 'cqnu-association-salt')}:password-reset"
        )
    except SignatureExpired:
        return None, '重置链接已过期，请联系管理员重新发起重置。'
    except BadSignature:
        return None, '重置链接无效，请联系管理员重新发起重置。'

    if not isinstance(data, dict) or data.get('purpose') != 'password-reset':
        return None, '重置链接无效，请联系管理员重新发起重置。'

    uid = data.get('uid')
    password_fingerprint = str(data.get('ph') or '')
    try:
        return {'uid': int(uid), 'ph': password_fingerprint}, None
    except Exception:
        return None, '重置链接无效，请联系管理员重新发起重置。'

def _is_safe_next_url(target):
    if not target:
        return False
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

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
            # 支持使用用户名、邮箱、学号、手机号登录
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
                .limit(1)
            )
            user = db.session.execute(stmt).scalars().first()
            
            if user and user.verify_password(password):
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

                # 学生首次登录（尚未选择标签）强制进入标签选择页
                try:
                    if user.role and (user.role.name or '').strip().lower() == 'student':
                        student_info = db.session.execute(
                            db.select(StudentInfo).filter_by(user_id=user.id)
                        ).scalar_one_or_none()
                        if student_info and not getattr(student_info, 'has_selected_tags', False):
                            return redirect(url_for('auth.select_tags'))
                except Exception as e:
                    logger.warning(f"检查标签选择状态失败，继续常规登录跳转: {e}")
                
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
    logout_user()
    session.clear()

    response = redirect(url_for('auth.login', logged_out=1, t=int(time.time())))
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

    flash('您已成功登出！', 'success')
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
            flash('密码修改成功！', 'success')
            return redirect(url_for('auth.profile'))
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
        flash('该重置链接已失效或已被使用，请联系管理员重新发起重置。', 'danger')
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
        
        if not selected_tags:
            flash('请至少选择一个标签', 'warning')
            tags_stmt = db.select(Tag)
            tags = db.session.execute(tags_stmt).scalars().all()
            return render_template('auth/select_tags.html', tags=tags)
        
        # 清除现有标签
        student_info.tags = []
        
        # 添加新标签
        for tag_id in selected_tags:
            tag_stmt = db.select(Tag).filter_by(id=int(tag_id))
            tag = db.session.execute(tag_stmt).scalar_one_or_none()
            if tag:
                student_info.tags.append(tag)
        
        # 标记为已选择标签
        student_info.has_selected_tags = True
        db.session.commit()
        
        flash('标签设置成功！', 'success')
        return redirect(url_for('student.dashboard'))
    
    # GET请求，显示标签选择页面
    tags_stmt = db.select(Tag)
    tags = db.session.execute(tags_stmt).scalars().all()
    
    # 获取已选择的标签
    selected_tag_ids = [tag.id for tag in student_info.tags] if student_info.tags else []
    
    return render_template('auth/select_tags.html', tags=tags, selected_tag_ids=selected_tag_ids)
