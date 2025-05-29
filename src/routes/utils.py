from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from src.models import db, Activity, Registration, User, StudentInfo, SystemLog
from datetime import datetime, timedelta
import json
import os

utils_bp = Blueprint('utils', __name__, url_prefix='/utils')

# 记录系统日志的函数
def log_action(user_id, action, details, ip_address=None):
    log = SystemLog(
        user_id=user_id,
        action=action,
        details=details,
        ip_address=ip_address or request.remote_addr
    )
    db.session.add(log)
    db.session.commit()

# 活动提醒功能
@utils_bp.route('/notifications')
@login_required
def notifications():
    # 获取即将截止的活动提醒（24小时内）
    deadline_soon = []
    if current_user.role.name == 'Student':
        # 学生看到的是已报名但即将开始的活动
        deadline_soon = Activity.query.join(
            Registration, Activity.id == Registration.activity_id
        ).filter(
            Registration.user_id == current_user.id,
            Registration.status == 'registered',
            Activity.start_time > datetime.now(),
            Activity.start_time <= datetime.now() + timedelta(hours=24)
        ).all()
    elif current_user.role.name == 'Admin':
        # 管理员看到的是即将截止报名的活动
        deadline_soon = Activity.query.filter(
            Activity.status == 'active',
            Activity.registration_deadline > datetime.now(),
            Activity.registration_deadline <= datetime.now() + timedelta(hours=24)
        ).all()
    
    return jsonify({
        'deadline_soon': [{
            'id': activity.id,
            'title': activity.title,
            'time': activity.start_time.strftime('%Y-%m-%d %H:%M') if current_user.role.name == 'Student' else activity.registration_deadline.strftime('%Y-%m-%d %H:%M'),
            'type': '活动即将开始' if current_user.role.name == 'Student' else '报名即将截止'
        } for activity in deadline_soon]
    })

# 活动签到功能
@utils_bp.route('/activity/<int:id>/checkin', methods=['GET', 'POST'])
@login_required
def activity_checkin(id):
    activity = Activity.query.get_or_404(id)
    
    # 检查是否为管理员
    if current_user.role.name != 'Admin':
        flash('您没有权限访问此页面', 'danger')
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        student_id = request.form.get('student_id')
        if not student_id:
            flash('请输入学号', 'warning')
            return redirect(url_for('utils.activity_checkin', id=id))
        
        # 查找学生
        student_info = StudentInfo.query.filter_by(student_id=student_id).first()
        if not student_info:
            flash('未找到该学号对应的学生', 'danger')
            return redirect(url_for('utils.activity_checkin', id=id))
        
        # 检查是否报名
        registration = Registration.query.filter_by(
            user_id=student_info.user_id,
            activity_id=id
        ).first()
        
        if not registration:
            flash('该学生未报名此活动', 'danger')
            return redirect(url_for('utils.activity_checkin', id=id))
        
        # 更新签到状态
        registration.status = 'attended'
        db.session.commit()
        
        # 记录日志
        log_action(
            current_user.id,
            'activity_checkin',
            f'为活动 {activity.title} 签到学生 {student_info.real_name}({student_info.student_id})'
        )
        
        flash(f'学生 {student_info.real_name} 签到成功！', 'success')
        return redirect(url_for('utils.activity_checkin', id=id))
    
    # 获取已签到和未签到的学生
    attended = Registration.query.filter_by(
        activity_id=id,
        status='attended'
    ).join(
        User, Registration.user_id == User.id
    ).join(
        StudentInfo, User.id == StudentInfo.user_id
    ).add_columns(
        StudentInfo.real_name,
        StudentInfo.student_id,
        StudentInfo.college
    ).all()
    
    registered = Registration.query.filter_by(
        activity_id=id,
        status='registered'
    ).join(
        User, Registration.user_id == User.id
    ).join(
        StudentInfo, User.id == StudentInfo.user_id
    ).add_columns(
        StudentInfo.real_name,
        StudentInfo.student_id,
        StudentInfo.college
    ).all()
    
    return render_template('utils/activity_checkin.html', 
                          activity=activity,
                          attended=attended,
                          registered=registered)

# 数据备份功能
@utils_bp.route('/backup', methods=['GET', 'POST'])
@login_required
def backup():
    # 检查是否为管理员
    if current_user.role.name != 'Admin':
        flash('您没有权限访问此页面', 'danger')
        return redirect(url_for('main.index'))
    
    if request.method == 'POST':
        # 创建备份目录
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # 备份文件名
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        backup_file = os.path.join(backup_dir, f'backup_{timestamp}.json')
        
        # 获取所有数据
        users = User.query.all()
        students = StudentInfo.query.all()
        activities = Activity.query.all()
        registrations = Registration.query.all()
        
        # 构建备份数据
        backup_data = {
            'users': [{
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'role_id': user.role_id,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login': user.last_login.isoformat() if user.last_login else None
            } for user in users],
            'students': [{
                'id': student.id,
                'user_id': student.user_id,
                'real_name': student.real_name,
                'student_id': student.student_id,
                'grade': student.grade,
                'major': student.major,
                'college': student.college,
                'phone': student.phone,
                'qq': student.qq
            } for student in students],
            'activities': [{
                'id': activity.id,
                'title': activity.title,
                'description': activity.description,
                'location': activity.location,
                'start_time': activity.start_time.isoformat() if activity.start_time else None,
                'end_time': activity.end_time.isoformat() if activity.end_time else None,
                'registration_deadline': activity.registration_deadline.isoformat() if activity.registration_deadline else None,
                'max_participants': activity.max_participants,
                'created_by': activity.created_by,
                'created_at': activity.created_at.isoformat() if activity.created_at else None,
                'updated_at': activity.updated_at.isoformat() if activity.updated_at else None,
                'status': activity.status
            } for activity in activities],
            'registrations': [{
                'id': reg.id,
                'user_id': reg.user_id,
                'activity_id': reg.activity_id,
                'register_time': reg.register_time.isoformat() if reg.register_time else None,
                'status': reg.status,
                'remark': reg.remark
            } for reg in registrations]
        }
        
        # 写入备份文件
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2)
        
        # 记录日志
        log_action(
            current_user.id,
            'system_backup',
            f'创建系统数据备份: {os.path.basename(backup_file)}'
        )
        
        flash(f'数据备份成功！文件名: {os.path.basename(backup_file)}', 'success')
        return redirect(url_for('utils.backup'))
    
    # 获取现有备份文件
    backup_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'backups')
    backups = []
    
    if os.path.exists(backup_dir):
        for file in os.listdir(backup_dir):
            if file.startswith('backup_') and file.endswith('.json'):
                file_path = os.path.join(backup_dir, file)
                file_size = os.path.getsize(file_path) / 1024  # KB
                file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                backups.append({
                    'name': file,
                    'size': f'{file_size:.2f} KB',
                    'time': file_time.strftime('%Y-%m-%d %H:%M:%S')
                })
    
    backups.sort(key=lambda x: x['name'], reverse=True)
    
    return render_template('utils/backup.html', backups=backups)

# 系统日志查看
@utils_bp.route('/logs')
@login_required
def system_logs():
    # 检查是否为管理员
    if current_user.role.name != 'Admin':
        flash('您没有权限访问此页面', 'danger')
        return redirect(url_for('main.index'))
    
    page = request.args.get('page', 1, type=int)
    action_filter = request.args.get('action', '')
    
    query = SystemLog.query
    
    if action_filter:
        query = query.filter(SystemLog.action == action_filter)
    
    logs = query.order_by(SystemLog.created_at.desc()).paginate(page=page, per_page=20)
    
    # 获取所有操作类型
    actions = db.session.query(SystemLog.action).distinct().all()
    actions = [a[0] for a in actions]
    
    return render_template('utils/system_logs.html', 
                          logs=logs, 
                          actions=actions,
                          current_action=action_filter)

# 数据统计API（用于图表）
@utils_bp.route('/api/statistics')
@login_required
def api_statistics():
    # 检查是否为管理员
    if current_user.role.name != 'Admin':
        return jsonify({'error': '权限不足'}), 403
    
    stat_type = request.args.get('type', '')
    
    if stat_type == 'registrations_by_date':
        # 按日期统计报名人数
        days = 30
        start_date = datetime.now() - timedelta(days=days)
        
        # 获取每天的报名数据
        registrations = db.session.query(
            db.func.date(Registration.register_time).label('date'),
            db.func.count(Registration.id).label('count')
        ).filter(
            Registration.register_time >= start_date
        ).group_by(
            db.func.date(Registration.register_time)
        ).all()
        
        # 构建完整的日期范围
        date_range = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days, -1, -1)]
        counts = {r.date.strftime('%Y-%m-%d'): r.count for r in registrations}
        
        data = [counts.get(date, 0) for date in date_range]
        
        return jsonify({
            'labels': date_range,
            'data': data
        })
    
    elif stat_type == 'registrations_by_college':
        # 按学院统计报名人数
        colleges = db.session.query(
            StudentInfo.college,
            db.func.count(Registration.id).label('count')
        ).join(
            User, StudentInfo.user_id == User.id
        ).join(
            Registration, User.id == Registration.user_id
        ).group_by(
            StudentInfo.college
        ).all()
        
        return jsonify({
            'labels': [c.college for c in colleges],
            'data': [c.count for c in colleges]
        })
    
    elif stat_type == 'activities_by_status':
        # 按状态统计活动数量
        active = Activity.query.filter_by(status='active').count()
        completed = Activity.query.filter_by(status='completed').count()
        cancelled = Activity.query.filter_by(status='cancelled').count()
        
        return jsonify({
            'labels': ['进行中', '已完成', '已取消'],
            'data': [active, completed, cancelled]
        })
    
    return jsonify({'error': '未知的统计类型'}), 400
