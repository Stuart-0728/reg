from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from src import db
from src.models import User, Role, StudentInfo, Tag, AIUserPreferences, SystemLog
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, ValidationError
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp
from datetime import datetime
import logging

# 配置日志
logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)

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
    username = StringField('用户名', validators=[DataRequired(message='用户名不能为空')])
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
            role=student_role
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
        
        flash('注册成功，请登录！', 'success')
        # 登录用户并重定向到标签选择页面
        login_user(user)
        return redirect(url_for('auth.select_tags'))
    
    return render_template('auth/register.html', form=form)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
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
        username = form.username.data
        password = form.password.data
        
        logger.info(f"尝试登录: 用户名={username}")
        
        try:
            # 查询用户
            stmt = db.select(User).filter_by(username=username)
            user = db.session.execute(stmt).scalar_one_or_none()
            
            if user and user.verify_password(password):
                # 检查用户是否激活
                if not user.active:
                    flash('账号已被禁用，请联系管理员。', 'danger')
                    return render_template('auth/login.html', form=form)
                
                # 登录成功
                login_user(user)
                
                # 记录登录成功日志
                logger.info(f"登录成功: 用户名={username}, 用户ID={user.id}")
                
                # 添加系统日志
                log = SystemLog(
                    user_id=user.id,
                    action="用户登录",
                    details=f"用户 {username} 登录成功",
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
                
                # 如果有next参数，则重定向到next页面
                if next_page and next_page != 'None' and next_page != url_for('auth.login'):
                    logger.info(f"重定向到: {next_page}")
                    return redirect(next_page)
                
                # 否则重定向到主页
                return redirect(url_for('main.index'))
            else:
                # 登录失败
                logger.warning(f"登录失败: 用户名={username}, 原因=用户名或密码错误")
                flash('用户名或密码错误，请重试。', 'danger')
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
    flash('您已成功登出！', 'success')
    return redirect(url_for('main.index'))

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
