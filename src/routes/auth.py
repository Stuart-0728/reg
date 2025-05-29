from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from src.models import db, User, Role, StudentInfo
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, ValidationError
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp

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
        Regexp('^1[3-9]\d{9}$', message='请输入有效的手机号码')
    ])
    qq = StringField('QQ号', validators=[
        DataRequired(message='QQ号不能为空'),
        Regexp('^\d{5,12}$', message='请输入有效的QQ号码')
    ])
    submit = SubmitField('注册')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('该用户名已被注册')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('该邮箱已被注册')
            
    def validate_student_id(self, field):
        if StudentInfo.query.filter_by(student_id=field.data).first():
            raise ValidationError('该学号已被注册')

# 登录表单
class LoginForm(FlaskForm):
    username = StringField('用户名', validators=[DataRequired(message='用户名不能为空')])
    password = PasswordField('密码', validators=[DataRequired(message='密码不能为空')])
    submit = SubmitField('登录')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = RegistrationForm()
    if form.validate_on_submit():
        # 获取学生角色
        student_role = Role.query.filter_by(name='Student').first()
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
            qq=form.qq.data
        )
        db.session.add(student_info)
        db.session.commit()
        
        flash('注册成功，请登录！', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('auth/register.html', form=form)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role.name == 'Admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('student.dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            next_page = request.args.get('next')
            
            # 根据角色重定向到不同的页面
            if user.role.name == 'Admin':
                return redirect(next_page or url_for('admin.dashboard'))
            else:
                return redirect(next_page or url_for('student.dashboard'))
        else:
            flash('登录失败，请检查用户名和密码', 'danger')
    
    return render_template('auth/login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('您已成功退出登录', 'info')
    return redirect(url_for('main.index'))

@auth_bp.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html')

@auth_bp.route('/change_password', methods=['GET', 'POST'])
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
        if check_password_hash(current_user.password_hash, form.old_password.data):
            current_user.password_hash = generate_password_hash(form.new_password.data)
            db.session.commit()
            flash('密码修改成功！', 'success')
            return redirect(url_for('auth.profile'))
        else:
            flash('当前密码不正确', 'danger')
    
    return render_template('auth/change_password.html', form=form)
