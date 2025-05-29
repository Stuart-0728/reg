from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from src.models import db, Activity, Registration, User, StudentInfo
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DateTimeField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Optional, NumberRange
from datetime import datetime
import csv
import io

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# 检查是否为管理员的装饰器
def admin_required(func):
    @login_required
    def decorated_view(*args, **kwargs):
        if not current_user.role or current_user.role.name != 'Admin':
            flash('您没有权限访问此页面', 'danger')
            return redirect(url_for('main.index'))
        return func(*args, **kwargs)
    decorated_view.__name__ = func.__name__
    return decorated_view

# 活动表单
class ActivityForm(FlaskForm):
    title = StringField('活动标题', validators=[DataRequired(message='活动标题不能为空')])
    description = TextAreaField('活动描述', validators=[DataRequired(message='活动描述不能为空')])
    location = StringField('活动地点', validators=[DataRequired(message='活动地点不能为空')])
    start_time = DateTimeField('开始时间', format='%Y-%m-%d %H:%M', validators=[DataRequired(message='开始时间不能为空')])
    end_time = DateTimeField('结束时间', format='%Y-%m-%d %H:%M', validators=[DataRequired(message='结束时间不能为空')])
    registration_deadline = DateTimeField('报名截止时间', format='%Y-%m-%d %H:%M', validators=[DataRequired(message='报名截止时间不能为空')])
    max_participants = IntegerField('最大参与人数 (0表示不限制)', validators=[Optional(), NumberRange(min=0, message='参与人数不能为负数')])
    submit = SubmitField('提交')

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    # 获取活动统计信息
    total_activities = Activity.query.count()
    active_activities = Activity.query.filter_by(status='active').count()
    total_registrations = Registration.query.count()
    total_students = User.query.join(User.role).filter_by(name='Student').count()
    
    # 获取最近的活动
    recent_activities = Activity.query.order_by(Activity.created_at.desc()).limit(5).all()
    
    return render_template('admin/dashboard.html', 
                          total_activities=total_activities,
                          active_activities=active_activities,
                          total_registrations=total_registrations,
                          total_students=total_students,
                          recent_activities=recent_activities)

@admin_bp.route('/activities')
@admin_required
def activities():
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status', 'all')
    
    query = Activity.query
    if status != 'all':
        query = query.filter_by(status=status)
    
    activities = query.order_by(Activity.created_at.desc()).paginate(page=page, per_page=10)
    
    return render_template('admin/activities.html', activities=activities, current_status=status)

@admin_bp.route('/activity/new', methods=['GET', 'POST'])
@admin_required
def new_activity():
    form = ActivityForm()
    if form.validate_on_submit():
        activity = Activity(
            title=form.title.data,
            description=form.description.data,
            location=form.location.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            registration_deadline=form.registration_deadline.data,
            max_participants=form.max_participants.data or 0,
            created_by=current_user.id
        )
        db.session.add(activity)
        db.session.commit()
        flash('活动创建成功！', 'success')
        return redirect(url_for('admin.activities'))
    
    return render_template('admin/activity_form.html', form=form, title='创建新活动')

@admin_bp.route('/activity/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_activity(id):
    activity = Activity.query.get_or_404(id)
    form = ActivityForm()
    
    if form.validate_on_submit():
        activity.title = form.title.data
        activity.description = form.description.data
        activity.location = form.location.data
        activity.start_time = form.start_time.data
        activity.end_time = form.end_time.data
        activity.registration_deadline = form.registration_deadline.data
        activity.max_participants = form.max_participants.data or 0
        activity.updated_at = datetime.now()
        
        db.session.commit()
        flash('活动更新成功！', 'success')
        return redirect(url_for('admin.activities'))
    
    # 预填表单
    if request.method == 'GET':
        form.title.data = activity.title
        form.description.data = activity.description
        form.location.data = activity.location
        form.start_time.data = activity.start_time
        form.end_time.data = activity.end_time
        form.registration_deadline.data = activity.registration_deadline
        form.max_participants.data = activity.max_participants
    
    return render_template('admin/activity_form.html', form=form, title='编辑活动')

@admin_bp.route('/activity/<int:id>/delete', methods=['POST'])
@admin_required
def delete_activity(id):
    activity = Activity.query.get_or_404(id)
    
    # 检查是否有人已报名
    if activity.registrations.count() > 0:
        activity.status = 'cancelled'  # 如果有人报名，则标记为取消而不是删除
        db.session.commit()
        flash('该活动已有人报名，已将状态更改为已取消', 'warning')
    else:
        db.session.delete(activity)
        db.session.commit()
        flash('活动已成功删除', 'success')
    
    return redirect(url_for('admin.activities'))

@admin_bp.route('/activity/<int:id>/registrations')
@admin_required
def activity_registrations(id):
    activity = Activity.query.get_or_404(id)
    page = request.args.get('page', 1, type=int)
    
    registrations = Registration.query.filter_by(activity_id=id).join(
        User, Registration.user_id == User.id
    ).join(
        StudentInfo, User.id == StudentInfo.user_id
    ).add_columns(
        Registration.id,
        Registration.register_time,
        Registration.status,
        User.username,
        StudentInfo.real_name,
        StudentInfo.student_id,
        StudentInfo.grade,
        StudentInfo.major,
        StudentInfo.college,
        StudentInfo.phone,
        StudentInfo.qq
    ).paginate(page=page, per_page=20)
    
    return render_template('admin/activity_registrations.html', 
                          activity=activity, 
                          registrations=registrations)

@admin_bp.route('/activity/<int:id>/export', methods=['GET'])
@admin_required
def export_registrations(id):
    activity = Activity.query.get_or_404(id)
    
    # 获取所有报名信息
    registrations = Registration.query.filter_by(activity_id=id).join(
        User, Registration.user_id == User.id
    ).join(
        StudentInfo, User.id == StudentInfo.user_id
    ).add_columns(
        Registration.id,
        Registration.register_time,
        Registration.status,
        User.username,
        StudentInfo.real_name,
        StudentInfo.student_id,
        StudentInfo.grade,
        StudentInfo.major,
        StudentInfo.college,
        StudentInfo.phone,
        StudentInfo.qq
    ).all()
    
    # 创建CSV文件
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 写入表头
    writer.writerow(['序号', '姓名', '学号', '年级', '专业', '学院', '手机号', 'QQ号', '报名时间', '状态'])
    
    # 写入数据
    for i, reg in enumerate(registrations, 1):
        writer.writerow([
            i,
            reg.real_name,
            reg.student_id,
            reg.grade,
            reg.major,
            reg.college,
            reg.phone,
            reg.qq,
            reg.register_time.strftime('%Y-%m-%d %H:%M:%S'),
            reg.status
        ])
    
    # 设置响应头
    output.seek(0)
    filename = f"{activity.title}_报名信息_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    
    return output.getvalue(), 200, {
        'Content-Type': 'text/csv; charset=utf-8-sig',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }

@admin_bp.route('/students')
@admin_required
def students():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    
    query = User.query.join(User.role).filter_by(name='Student').join(User.student_info)
    
    if search:
        query = query.filter(
            (StudentInfo.real_name.contains(search)) |
            (StudentInfo.student_id.contains(search)) |
            (StudentInfo.college.contains(search)) |
            (StudentInfo.major.contains(search))
        )
    
    students = query.paginate(page=page, per_page=20)
    
    return render_template('admin/students.html', students=students, search=search)

@admin_bp.route('/statistics')
@admin_required
def statistics():
    # 活动统计
    total_activities = Activity.query.count()
    active_activities = Activity.query.filter_by(status='active').count()
    completed_activities = Activity.query.filter_by(status='completed').count()
    cancelled_activities = Activity.query.filter_by(status='cancelled').count()
    
    # 用户统计
    total_students = User.query.join(User.role).filter_by(name='Student').count()
    
    # 学院分布
    college_stats = db.session.query(
        StudentInfo.college, 
        db.func.count(StudentInfo.id)
    ).group_by(StudentInfo.college).all()
    
    # 年级分布
    grade_stats = db.session.query(
        StudentInfo.grade, 
        db.func.count(StudentInfo.id)
    ).group_by(StudentInfo.grade).all()
    
    # 报名统计
    registration_stats = db.session.query(
        db.func.date(Registration.register_time),
        db.func.count(Registration.id)
    ).group_by(db.func.date(Registration.register_time)).all()
    
    return render_template('admin/statistics.html',
                          total_activities=total_activities,
                          active_activities=active_activities,
                          completed_activities=completed_activities,
                          cancelled_activities=cancelled_activities,
                          total_students=total_students,
                          college_stats=college_stats,
                          grade_stats=grade_stats,
                          registration_stats=registration_stats)
