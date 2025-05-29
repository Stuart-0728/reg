from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from src.models import db, Activity, Registration, User, StudentInfo
from datetime import datetime

student_bp = Blueprint('student', __name__, url_prefix='/student')

# 检查是否为学生的装饰器
def student_required(func):
    @login_required
    def decorated_view(*args, **kwargs):
        if not current_user.role or current_user.role.name != 'Student':
            flash('您没有权限访问此页面', 'danger')
            return redirect(url_for('main.index'))
        return func(*args, **kwargs)
    decorated_view.__name__ = func.__name__
    return decorated_view

@student_bp.route('/dashboard')
@student_required
def dashboard():
    # 获取学生已报名的活动
    registered_activities = Activity.query.join(
        Registration, Activity.id == Registration.activity_id
    ).filter(
        Registration.user_id == current_user.id,
        Registration.status != 'cancelled'
    ).all()
    
    # 获取即将开始的活动（未报名）
    upcoming_activities = Activity.query.filter(
        Activity.status == 'active',
        Activity.registration_deadline >= datetime.now()
    ).outerjoin(
        Registration, (Activity.id == Registration.activity_id) & (Registration.user_id == current_user.id)
    ).filter(
        Registration.id == None
    ).order_by(
        Activity.registration_deadline
    ).limit(5).all()
    
    return render_template('student/dashboard.html', 
                          registered_activities=registered_activities,
                          upcoming_activities=upcoming_activities)

@student_bp.route('/activities')
@student_required
def activities():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'active')
    
    # 基本查询
    query = Activity.query
    
    # 根据状态筛选
    if status == 'active':
        query = query.filter(
            Activity.status == 'active',
            Activity.registration_deadline >= datetime.now()
        )
    elif status == 'past':
        query = query.filter(
            (Activity.status == 'completed') | 
            (Activity.registration_deadline < datetime.now())
        )
    
    # 获取活动列表
    activities_list = query.order_by(Activity.created_at.desc()).paginate(page=page, per_page=10)
    
    # 获取用户已报名的活动ID列表
    registered_activity_ids = db.session.query(Registration.activity_id).filter(
        Registration.user_id == current_user.id,
        Registration.status != 'cancelled'
    ).all()
    registered_activity_ids = [r[0] for r in registered_activity_ids]
    
    return render_template('student/activities.html', 
                          activities=activities_list, 
                          current_status=status,
                          registered_activity_ids=registered_activity_ids)

@student_bp.route('/activity/<int:id>')
@student_required
def activity_detail(id):
    activity = Activity.query.get_or_404(id)
    
    # 检查用户是否已报名
    registration = Registration.query.filter_by(
        user_id=current_user.id,
        activity_id=activity.id
    ).first()
    
    # 检查是否可以报名
    can_register = (
        activity.status == 'active' and
        activity.registration_deadline >= datetime.now() and
        not registration
    )
    
    # 检查是否已达到人数上限
    if can_register and activity.max_participants > 0:
        current_participants = Registration.query.filter_by(
            activity_id=activity.id,
            status='registered'
        ).count()
        if current_participants >= activity.max_participants:
            can_register = False
    
    return render_template('student/activity_detail.html', 
                          activity=activity,
                          registration=registration,
                          can_register=can_register)

@student_bp.route('/activity/<int:id>/register', methods=['POST'])
@student_required
def register_activity(id):
    activity = Activity.query.get_or_404(id)
    
    # 检查活动是否可报名
    if activity.status != 'active' or activity.registration_deadline < datetime.now():
        flash('该活动已结束报名', 'danger')
        return redirect(url_for('student.activity_detail', id=id))
    
    # 检查是否已报名
    existing_registration = Registration.query.filter_by(
        user_id=current_user.id,
        activity_id=activity.id
    ).first()
    
    if existing_registration:
        flash('您已报名过该活动', 'warning')
        return redirect(url_for('student.activity_detail', id=id))
    
    # 检查是否已达到人数上限
    if activity.max_participants > 0:
        current_participants = Registration.query.filter_by(
            activity_id=activity.id,
            status='registered'
        ).count()
        if current_participants >= activity.max_participants:
            flash('该活动报名人数已达上限', 'danger')
            return redirect(url_for('student.activity_detail', id=id))
    
    # 创建报名记录
    registration = Registration(
        user_id=current_user.id,
        activity_id=activity.id,
        register_time=datetime.now(),
        status='registered'
    )
    
    db.session.add(registration)
    db.session.commit()
    
    flash('报名成功！', 'success')
    return redirect(url_for('student.activity_detail', id=id))

@student_bp.route('/activity/<int:id>/cancel', methods=['POST'])
@student_required
def cancel_registration(id):
    registration = Registration.query.filter_by(
        user_id=current_user.id,
        activity_id=id
    ).first_or_404()
    
    # 检查活动是否已开始
    activity = Activity.query.get(id)
    if activity.start_time <= datetime.now():
        flash('活动已开始，无法取消报名', 'danger')
        return redirect(url_for('student.activity_detail', id=id))
    
    # 取消报名
    registration.status = 'cancelled'
    db.session.commit()
    
    flash('已成功取消报名', 'success')
    return redirect(url_for('student.activity_detail', id=id))

@student_bp.route('/my_activities')
@student_required
def my_activities():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')
    
    # 基本查询 - 获取用户报名的活动
    query = Activity.query.join(
        Registration, Activity.id == Registration.activity_id
    ).filter(
        Registration.user_id == current_user.id
    )
    
    # 根据状态筛选
    if status == 'upcoming':
        query = query.filter(
            Activity.start_time > datetime.now(),
            Registration.status == 'registered'
        )
    elif status == 'past':
        query = query.filter(
            Activity.end_time < datetime.now(),
            Registration.status == 'registered'
        )
    elif status == 'cancelled':
        query = query.filter(
            Registration.status == 'cancelled'
        )
    
    # 获取活动列表
    activities_list = query.order_by(Activity.start_time.desc()).paginate(page=page, per_page=10)
    
    return render_template('student/my_activities.html', 
                          activities=activities_list, 
                          current_status=status)

@student_bp.route('/profile')
@student_required
def profile():
    return render_template('student/profile.html')

@student_bp.route('/profile/edit', methods=['GET', 'POST'])
@student_required
def edit_profile():
    from flask_wtf import FlaskForm
    from wtforms import StringField, SubmitField
    from wtforms.validators import DataRequired, Length, Regexp
    
    class ProfileForm(FlaskForm):
        real_name = StringField('姓名', validators=[DataRequired(message='姓名不能为空')])
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
        submit = SubmitField('保存修改')
    
    form = ProfileForm()
    student_info = current_user.student_info
    
    if form.validate_on_submit():
        student_info.real_name = form.real_name.data
        student_info.grade = form.grade.data
        student_info.major = form.major.data
        student_info.college = form.college.data
        student_info.phone = form.phone.data
        student_info.qq = form.qq.data
        
        db.session.commit()
        flash('个人信息更新成功！', 'success')
        return redirect(url_for('student.profile'))
    
    # 预填表单
    if request.method == 'GET':
        form.real_name.data = student_info.real_name
        form.grade.data = student_info.grade
        form.major.data = student_info.major
        form.college.data = student_info.college
        form.phone.data = student_info.phone
        form.qq.data = student_info.qq
    
    return render_template('student/edit_profile.html', form=form)
