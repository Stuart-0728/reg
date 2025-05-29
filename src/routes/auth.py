from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from src.models import db, User, StudentInfo
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, ValidationError
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp

auth_bp = Blueprint('auth', __name__)

# 注册表单定义省略…

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        # 直接用字符串 “Student” 作为角色
        user = User(
            username       = form.username.data,
            email          = form.email.data,
            password_hash  = generate_password_hash(form.password.data),
            role           = 'Student'
        )
        db.session.add(user)
        db.session.flush()  # 拿到 user.id

        # 如果你有学生信息表
        student_info = StudentInfo(
            user_id    = user.id,
            real_name  = form.real_name.data,
            student_id = form.student_id.data,
            grade      = form.grade.data,
            major      = form.major.data,
            college    = form.college.data,
            phone      = form.phone.data,
            qq         = form.qq.data
        )
        db.session.add(student_info)
        db.session.commit()

        flash('注册成功，请登录！', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', form=form)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # 直接检查字符串
        if current_user.role == 'Admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('student.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            return redirect(url_for('main.index'))
        flash('用户名或密码错误', 'danger')
    return render_template('auth/login.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))
