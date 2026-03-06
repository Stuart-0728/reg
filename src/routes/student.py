from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, abort, session, Response
from flask_login import login_required, current_user
from src.models import db, Activity, Registration, User, StudentInfo, PointsHistory, ActivityReview, Tag, Message, Notification, NotificationRead, Role
from datetime import datetime, timedelta
import logging
import json
from functools import wraps
from src.routes.utils import log_action, random_string
from sqlalchemy import func, desc, or_, and_, not_
from wtforms import StringField, TextAreaField, IntegerField, SelectField, SubmitField, RadioField, BooleanField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email, Regexp
from flask_wtf import FlaskForm
from src.utils.time_helpers import get_localized_now, ensure_timezone_aware, display_datetime, safe_compare, safe_less_than, safe_greater_than, safe_greater_than_equal, safe_less_than_equal, get_activity_status, is_activity_completed
from src.utils import get_compatible_paginate
from sqlalchemy.orm import joinedload
import pytz
import os
from flask_wtf.csrf import CSRFProtect

logger = logging.getLogger(__name__)

student_bp = Blueprint('student', __name__, url_prefix='/student')

# 创建CSRF保护实例
csrf = CSRFProtect()

# 检查是否为学生的装饰器
def student_required(func):
    @login_required
    def decorated_view(*args, **kwargs):
        try:
            if not current_user.role or current_user.role.name != 'Student':
                flash('您没有权限访问此页面', 'danger')
                return redirect(url_for('main.index'))
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in student_required: {e}")
            flash('发生错误，请稍后再试', 'danger')
            return redirect(url_for('main.index'))
    decorated_view.__name__ = func.__name__
    return decorated_view

@student_bp.route('/dashboard')
@login_required
def dashboard():
    try:
        # 获取当前时间，确保带有时区信息
        now = get_localized_now()
        
        # 获取学生信息
        stmt = db.select(StudentInfo).filter_by(user_id=current_user.id)
        student_info = db.session.execute(stmt).scalar_one_or_none()
        if not student_info:
            return redirect(url_for('auth.register'))
        
        # 获取学生已报名的活动，并预加载活动信息
        reg_stmt = db.select(Registration).filter(
            Registration.user_id == current_user.id,
            Registration.status.in_(['registered', 'attended'])
        ).options(joinedload(Registration.activity))
        registrations = db.session.execute(reg_stmt).scalars().all()

        # 将活动分类为未开始、进行中和已结束
        upcoming_activities = []
        ongoing_activities = []
        past_activities = []
        
        # 记录找到的活动数量
        logger.info(f"获取到学生报名的活动数量: {len(registrations)}")
        
        for reg in registrations:
            activity = reg.activity
            if not activity or activity.status == 'cancelled':
                continue
            
            activity.registration_status = reg.status
            activity.check_in_time = reg.check_in_time

            if safe_greater_than(activity.start_time, now):
                upcoming_activities.append(activity)
                logger.info(f"即将开始的活动: {activity.title}")
            elif safe_less_than(activity.end_time, now):
                past_activities.append(activity)
                logger.info(f"已结束的活动: {activity.title}")
            else:
                ongoing_activities.append(activity)
                logger.info(f"进行中的活动: {activity.title}")
        
        # 排序活动，按开始时间降序排列（最近的活动在前面）
        upcoming_activities.sort(key=lambda x: x.start_time, reverse=True)
        ongoing_activities.sort(key=lambda x: x.end_time)
        past_activities.sort(key=lambda x: x.start_time) # 确保已结束活动也按开始时间升序

        # 合并所有已报名的活动，用于在仪表盘中展示
        registered_activities = sorted(upcoming_activities + ongoing_activities + past_activities, key=lambda x: x.start_time)
        
        logger.info(f"仪表盘活动分类: 即将开始={len(upcoming_activities)}, 进行中={len(ongoing_activities)}, 已结束={len(past_activities)}")
        
        # 获取最近的通知
        notifications = []
        try:
            # 获取公开通知和针对当前用户的通知
            notif_stmt = db.select(Notification).filter(
                or_(
                    Notification.is_public == True,  # 公开通知
                    and_(
                        Notification.is_public == False,  # 私人通知
                        Notification.created_by == current_user.id  # 发给当前用户的
                    )
                )
            ).order_by(Notification.created_at.desc()).limit(5)
            
            db_notifications = db.session.execute(notif_stmt).scalars().all()
            
            # 处理通知类型
            for notif in db_notifications:
                notification_type = 'new'
                # 创建包含所需属性的通知对象
                notifications.append({
                    'id': notif.id,
                    'type': notification_type,
                    'message': notif.title,
                    'created_at': notif.created_at,
                    'link': url_for('student.view_notification', id=notif.id),
                    'is_important': notif.is_important
                })
            
            logger.info(f"获取到 {len(notifications)} 条通知")
        except Exception as e:
            logger.error(f"获取通知时出错: {e}", exc_info=True)
            notifications = []
        
        # 获取学生积分
        points = student_info.points
        
        # 获取推荐活动
        recommended_activities = get_recommended_activities(current_user.id)

        return render_template(
            'student/dashboard.html',
            student=student_info,
            registered_activities=registered_activities,
            notifications=notifications,
            points=points,
            display_datetime=display_datetime,
            now=now,
            safe_less_than=safe_less_than,
            safe_greater_than=safe_greater_than,
            recommended_activities=recommended_activities
        )
    except Exception as e:
        logger.error(f"Error in student dashboard: {e}", exc_info=True)
        flash('加载个人中心出错，请重试', 'danger')
        return redirect(url_for('main.index'))

@student_bp.route('/activities')
@login_required
def activities():
    """显示学生可参加的活动列表"""
    try:
        # 获取当前北京时间
        now = get_localized_now()
        current_status = request.args.get('status', 'active')
        page = request.args.get('page', 1, type=int)
        
        # 基本查询 - 所有活动
        query = db.select(Activity)

        # 根据状态筛选，使用北京时间进行比较
        if current_status == 'active':
            # 活动状态为'active'且未结束
            query = query.filter(Activity.status == 'active')
            query = query.filter(Activity.end_time > now)
        elif current_status == 'past':
            # 已结束的活动
            query = query.filter(
                or_(
                    Activity.status == 'completed',
                    and_(Activity.status == 'active', Activity.end_time <= now)
                )
            )
            
        # 排序
        query = query.order_by(Activity.start_time)
            
        # 分页
        activities = get_compatible_paginate(db, query, page=page, per_page=10, error_out=False)
        
        # 查询用户已报名的活动ID（只包含已报名和已签到的，不包括已取消的）
        reg_stmt = db.select(Registration.activity_id).filter(
            Registration.user_id == current_user.id,
            Registration.status.in_(['registered', 'attended'])  # 排除已取消的报名
        )
        registered = db.session.execute(reg_stmt).all()
        registered_activity_ids = [r[0] for r in registered]
        
        # 从time_helpers导入时间比较函数
        from src.utils.time_helpers import safe_less_than, safe_greater_than, safe_compare, display_datetime
        
        return render_template(
            'student/activities.html',
            activities=activities,
            registered_activity_ids=registered_activity_ids,
            now=now,
            current_status=current_status,
            safe_less_than=safe_less_than,
            safe_greater_than=safe_greater_than,
            safe_compare=safe_compare,
            display_datetime=display_datetime
        )
    except Exception as e:
        logger.error(f"Error in student activities: {e}")
        flash('加载活动列表时出错，请重试', 'danger')
        return redirect(url_for('student.dashboard'))

@student_bp.route('/activity/<int:id>')
@login_required
def activity_detail(id):
    try:
        activity = db.get_or_404(Activity, id)
        now = get_localized_now()

        registration = db.session.execute(db.select(Registration).filter_by(user_id=current_user.id, activity_id=id)).scalar_one_or_none()
        has_registered = registration is not None and registration.status in ['registered', 'attended']
        has_checked_in = registration.check_in_time is not None if registration else False

        registered_count = db.session.execute(db.select(func.count()).select_from(Registration).filter_by(activity_id=id, status='registered')).scalar() or 0
        checked_in_count = db.session.execute(db.select(func.count()).select_from(Registration).filter_by(activity_id=id, status='attended')).scalar() or 0
        total_registered = registered_count + checked_in_count

        can_register = (
            not has_registered and
            activity.status == 'active' and
            (activity.registration_deadline is None or safe_greater_than(activity.registration_deadline, now)) and
            (activity.max_participants == 0 or total_registered < activity.max_participants)
        )

        can_cancel = has_registered and safe_greater_than(activity.start_time, now)

        can_checkin = (
            has_registered and 
            not has_checked_in and 
            (
                (safe_less_than_equal(activity.start_time, now) and safe_greater_than(activity.end_time, now)) or 
                activity.checkin_enabled
            )
        )

        current_user_review = db.session.execute(db.select(ActivityReview).filter_by(activity_id=id, user_id=current_user.id)).scalar_one_or_none()
        reviews = db.session.execute(db.select(ActivityReview).filter_by(activity_id=id)).scalars().all()
        review_count = len(reviews)

        average_rating = sum(r.rating for r in reviews) / review_count if review_count > 0 else 0
        avg_content_quality = sum(r.content_quality for r in reviews if r.content_quality) / review_count if review_count > 0 else 0
        avg_organization = sum(r.organization for r in reviews if r.organization) / review_count if review_count > 0 else 0
        avg_facility = sum(r.facility for r in reviews if r.facility) / review_count if review_count > 0 else 0

        form = FlaskForm()

        poster_url = None
        if activity.poster_image:
            if 'banner' in activity.poster_image:
                poster_url = url_for('static', filename=f'img/{activity.poster_image}')
            else:
                poster_url = url_for('static', filename=f'uploads/posters/{activity.poster_image}')
        
        # 获取活动当天的天气信息
        weather_data = None
        try:
            from src.utils.weather_api import get_activity_weather
            if activity.start_time:
                weather_data = get_activity_weather(activity.start_time)
                logger.info(f"获取活动天气数据成功: {weather_data.get('description', 'N/A')}")
        except Exception as e:
            logger.warning(f"获取天气数据失败: {e}")
            weather_data = None

        return render_template('student/activity_detail.html',
                              form=form,
                              activity=activity,
                              has_registered=has_registered,
                              has_checked_in=has_checked_in,
                              registration=registration,
                              can_register=can_register,
                              can_cancel=can_cancel,
                              can_checkin=can_checkin,
                              current_user_registration=registration,
                              current_user_review=current_user_review,
                              registration_open=can_register, # Simplified
                              review_count=review_count,
                              reviews=reviews,
                              average_rating=average_rating,
                              avg_content_quality=avg_content_quality,
                              avg_organization=avg_organization,
                              avg_facility=avg_facility,
                              registered_count=total_registered,
                              now=now,
                              display_datetime=display_datetime,
                              safe_less_than=safe_less_than,
                              safe_greater_than=safe_greater_than,
                              safe_greater_than_equal=safe_greater_than_equal,
                              safe_less_than_equal=safe_less_than_equal,
                              poster_url=poster_url,
                              weather_data=weather_data)

    except Exception as e:
        logger.error(f"加载活动详情出错: {str(e)}", exc_info=True)
        flash('加载活动详情出错，请稍后重试', 'danger')
        return redirect(url_for('student.activities'))

@student_bp.route('/activity/<int:id>/register', methods=['POST'])
@student_required
def register_activity(id):
    """报名活动"""
    try:
        activity = db.get_or_404(Activity, id)

        if activity.status != 'active':
            return jsonify({'success': False, 'message': '该活动不在进行中，无法报名'})

        now = get_localized_now()
        if activity.registration_deadline and safe_less_than(activity.registration_deadline, now):
            return jsonify({'success': False, 'message': '该活动已过报名截止时间'})

        if activity.max_participants > 0:
            reg_count = db.session.execute(db.select(func.count()).select_from(Registration).filter_by(activity_id=id, status='registered')).scalar() or 0
            if reg_count >= activity.max_participants:
                return jsonify({'success': False, 'message': '该活动报名人数已满'})

        existing_reg = db.session.execute(db.select(Registration).filter_by(user_id=current_user.id, activity_id=id)).scalar_one_or_none()
        if existing_reg:
            if existing_reg.status == 'registered':
                return jsonify({'success': False, 'message': '您已报名此活动'})
            elif existing_reg.status == 'cancelled':
                existing_reg.status = 'registered'
                existing_reg.register_time = now
                db.session.commit()
                return jsonify({'success': True, 'message': '已成功重新报名活动'})

        new_registration = Registration(
            user_id=current_user.id,
            activity_id=id,
            register_time=now,
            status='registered'
        )
        db.session.add(new_registration)
        db.session.commit()

        return jsonify({'success': True, 'message': '报名成功！'})
    except Exception as e:
        logger.error(f"Error in register activity: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': '报名过程中发生错误，请稍后再试'})

@student_bp.route('/activity/<int:id>/cancel', methods=['POST'])
@student_required
def cancel_registration(id):
    """取消报名"""
    try:
        activity = db.get_or_404(Activity, id)

        now = get_localized_now()
        if not safe_greater_than(activity.start_time, now):
            return jsonify({'success': False, 'message': '活动已开始，无法取消报名'})

        registration = db.session.execute(db.select(Registration).filter_by(
            user_id=current_user.id,
            activity_id=id,
            status='registered'
        )).scalar_one_or_none()

        if not registration:
            return jsonify({'success': False, 'message': '未找到有效的报名记录'})

        registration.status = 'cancelled'
        db.session.commit()

        return jsonify({'success': True, 'message': '已成功取消报名'})
    except Exception as e:
        logger.error(f"Error in cancel registration: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': '取消报名过程中发生错误，请稍后再试'})

@student_bp.route('/my_activities')
@student_required
def my_activities():
    try:
        page = request.args.get('page', 1, type=int)
        status = request.args.get('status', 'all')
        
        # 使用北京时间进行状态判定
        from src.utils.time_helpers import get_localized_now, display_datetime, safe_less_than, safe_greater_than, safe_compare, get_activity_status, is_activity_completed
        now = get_localized_now()
        logger.info(f"my_activities - 当前北京时间: {now}")
        logger.info(f"my_activities - 用户ID: {current_user.id}, 状态筛选: {status}")
        
        # 使用别名避免表连接问题
        from sqlalchemy.orm import aliased
        ActivityAlias = aliased(Activity)
        
        # 基本查询 - 获取用户的所有报名记录
        query = Registration.query.filter_by(user_id=current_user.id)
        
        # 记录查询到的报名记录数量
        count = query.count()
        logger.info(f"my_activities - 找到 {count} 条报名记录")
        
        # 根据状态筛选
        if status == 'active':
            query = query.join(ActivityAlias, ActivityAlias.id == Registration.activity_id)
            query = query.filter(ActivityAlias.status == 'active')
        elif status == 'completed':
            query = query.join(ActivityAlias, ActivityAlias.id == Registration.activity_id)
            query = query.filter(ActivityAlias.status == 'completed')
        elif status == 'cancelled':
            query = query.filter_by(status='cancelled')
        
        # 获取报名记录，并预加载活动信息
        query = query.options(joinedload(Registration.activity))
        
        # 确保在所有情况下都添加连接，并使用正确的表别名进行排序
        if not any(status == s for s in ['active', 'completed']):
            query = query.join(ActivityAlias, ActivityAlias.id == Registration.activity_id)
        
        # 执行查询并分页 - 按距离当前时间最近的活动排序
        try:
            # 使用复杂排序逻辑：
            # 1. 进行中的活动（开始时间 <= 当前时间 < 结束时间）按结束时间升序
            # 2. 即将开始的活动（开始时间 > 当前时间）按开始时间升序
            # 3. 已结束的活动（结束时间 <= 当前时间）按结束时间降序
            from sqlalchemy import case
            
            # 定义活动状态的排序优先级
            status_priority = case(
                # 进行中的活动优先级最高（1）
                (and_(ActivityAlias.start_time <= now, ActivityAlias.end_time > now), 1),
                # 即将开始的活动优先级次之（2）
                (ActivityAlias.start_time > now, 2),
                # 已结束的活动优先级最低（3）
                else_=3
            )
            
            # 简化排序逻辑，避免在CASE中使用DESC
            # 先按状态优先级排序，再按开始时间排序
            order_by_clause = [status_priority, ActivityAlias.start_time.desc()]
            logger.info(f"my_activities - 按照距离当前时间最近的活动排序")
            registrations = query.order_by(*order_by_clause).paginate(page=page, per_page=10)
            logger.info(f"my_activities - 分页后有 {len(registrations.items)} 条记录, 总页数: {registrations.pages}")
        except Exception as e:
            logger.error(f"分页查询出错: {e}")
            # 尝试使用兼容方法，回退到简单的时间排序
            from src.utils import get_compatible_paginate
            registrations = get_compatible_paginate(db, query.order_by(ActivityAlias.start_time.desc()), page=page, per_page=10, error_out=False)
            logger.info(f"使用兼容分页方法后有 {len(registrations.items)} 条记录")
        
        # 记录每个活动的详细信息，方便调试
        for reg in registrations.items:
            activity = reg.activity
            logger.info(f"my_activities - 报名记录: 活动ID={reg.activity_id}, 状态={reg.status}, 活动对象存在={activity is not None}")
            if activity:
                logger.info(f"my_activities - 活动信息: 标题={activity.title}, 状态={activity.status}, 开始时间={activity.start_time}")

        # 获取待评价的活动
        reviewed_activity_ids = db.session.execute(db.select(ActivityReview.activity_id).filter_by(user_id=current_user.id)).scalars().all()
        pending_reviews = [reg.activity_id for reg in registrations.items if reg.activity and reg.activity.status == 'completed' and reg.activity_id not in reviewed_activity_ids]
        
        # 确保模板中能正确处理数据
        return render_template('student/my_activities.html', 
                              registrations=registrations,
                              current_status=status,
                              pending_reviews=pending_reviews,
                              now=now,
                              display_datetime=display_datetime,
                              safe_less_than=safe_less_than,
                              safe_greater_than=safe_greater_than,
                              safe_compare=safe_compare,
                              get_activity_status=get_activity_status,
                              is_activity_completed=is_activity_completed)
    except Exception as e:
        logger.error(f"Error in my_activities: {e}")
        flash('加载我的活动时发生错误', 'danger')
        return redirect(url_for('student.dashboard'))

@student_bp.route('/profile')
@student_required
def profile():
    try:
        # 获取学生信息
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
        if not student_info:
            flash('请先完善个人信息', 'warning')
            return redirect(url_for('student.edit_profile'))
        
        return render_template('student/profile.html', student_info=student_info)
    except Exception as e:
        logger.error(f"Error in profile: {e}")
        flash('加载个人资料时发生错误', 'danger')
        return redirect(url_for('student.dashboard'))

@student_bp.route('/profile/edit', methods=['GET', 'POST'])
@student_required
def edit_profile():
    try:
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
                Regexp(r'^1[3-9][0-9]{9}$', message='请输入有效的手机号码')
            ])
            qq = StringField('QQ号', validators=[
                DataRequired(message='QQ号不能为空'),
                Regexp(r'^[0-9]{5,12}$', message='请输入有效的QQ号码')
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
            
            # 处理标签
            tag_ids = request.form.getlist('tags')
            if tag_ids:
                student_info.tags = []
                for tag_id in tag_ids:
                    tag = db.session.get(Tag, int(tag_id))
                    if tag:
                        student_info.tags.append(tag)
                student_info.has_selected_tags = True
            
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
        
        # 获取所有标签和已选标签ID
        all_tags = db.session.execute(db.select(Tag)).scalars().all()
        selected_tag_ids = [tag.id for tag in student_info.tags] if student_info.tags else []
        
        return render_template('student/edit_profile.html', form=form, all_tags=all_tags, selected_tag_ids=selected_tag_ids)
    except Exception as e:
        logger.error(f"Error in edit profile: {e}")
        flash('编辑个人资料时发生错误', 'danger')
        return redirect(url_for('student.profile'))

@student_bp.route('/delete_account', methods=['POST'])
@student_required
def delete_account():
    try:
        # 验证用户确认
        confirm_username = request.form.get('confirm_username')
        if not confirm_username or confirm_username != current_user.username:
            flash('用户名输入不正确，账号注销失败', 'danger')
            return redirect(url_for('student.profile'))
        
        user_id = current_user.id
        
        # 删除关联的报名记录
        Registration.query.filter_by(user_id=user_id).delete()
        
        # 删除学生信息
        StudentInfo.query.filter_by(user_id=user_id).delete()
        
        # 记录用户信息用于日志
        username = current_user.username
        
        # 登出用户
        from flask_login import logout_user
        logout_user()
        
        # 删除用户
        user = db.session.get(User, user_id)
        db.session.delete(user)
        db.session.commit()
        
        logger.info(f"User self-deleted: {username} (ID: {user_id})")
        flash('您的账号已成功注销，所有个人信息已被删除', 'success')
        return redirect(url_for('main.index'))
    except Exception as e:
        logger.error(f"Error in account deletion: {e}")
        db.session.rollback()
        flash('账号注销过程中发生错误，请稍后再试', 'danger')
        return redirect(url_for('student.profile'))

@student_bp.route('/points')
@login_required
def points():
    try:
        # 导入display_datetime函数
        from src.utils.time_helpers import display_datetime
        
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
        if not student_info:
            flash('请先完善个人信息', 'warning')
            return redirect(url_for('student.edit_profile'))
        
        points_history = PointsHistory.query.filter_by(student_id=student_info.id)\
            .order_by(PointsHistory.created_at.desc()).all()
        
        return render_template('student/points.html', 
                             student_info=student_info,
                             points_history=points_history,
                             display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in student points page: {e}")
        flash('加载积分信息时出错', 'danger')
        return redirect(url_for('student.dashboard'))

def add_points(student_id, points, reason, activity_id=None):
    """添加积分的工具函数"""
    try:
        student = db.session.get(StudentInfo, student_id)
        if student:
            student.points += points
            
            history = PointsHistory(
                student_id=student_id,
                points=points,
                reason=reason,
                activity_id=activity_id
            )
            
            db.session.add(history)
            db.session.commit()
            return True
    except Exception as e:
        logger.error(f"Error adding points: {e}")
        db.session.rollback()
        return False

@student_bp.route('/activity/<int:activity_id>/review', methods=['GET', 'POST'])
@login_required
def review_activity(activity_id):
    try:
        # 检查活动是否存在且已结束
        activity = db.get_or_404(Activity, activity_id)
        if activity.status != 'completed':
            flash('只能评价已结束的活动', 'warning')
            return redirect(url_for('student.activity_detail', id=activity_id))
        
        # 检查是否已参加活动
        registration = Registration.query.filter_by(
            activity_id=activity_id,
            user_id=current_user.id
        ).filter(Registration.status.in_(['checked_in', 'attended'])).first()
        
        if not registration:
            flash('只有参加过活动的学生才能评价', 'warning')
            return redirect(url_for('student.activity_detail', id=activity_id))
        
        # 检查是否已评价过
        existing_review = db.session.execute(db.select(ActivityReview).filter_by(
            activity_id=activity_id,
            user_id=current_user.id
        )).scalar_one_or_none()
        
        if existing_review:
            flash('你已经评价过这个活动了', 'info')
            return redirect(url_for('student.activity_detail', id=activity_id))
        
        return render_template('student/review.html', activity=activity)
    except Exception as e:
        logger.error(f"Error in review activity page: {e}")
        flash('加载评价页面时出错', 'danger')
        return redirect(url_for('student.my_activities'))

@student_bp.route('/activity/<int:activity_id>/submit-review', methods=['POST'])
@login_required
def submit_review(activity_id):
    try:
        # 验证表单数据
        rating = request.form.get('rating', type=int)
        content_quality = request.form.get('content_quality', type=int)
        organization = request.form.get('organization', type=int)
        facility = request.form.get('facility', type=int)
        review_text = request.form.get('review', '').strip()
        is_anonymous = 'anonymous' in request.form
        
        if not all([rating, review_text]) or not (1 <= rating <= 5):
            flash('请填写完整的评价信息', 'warning')
            return redirect(url_for('student.review_activity', activity_id=activity_id))
        
        # 创建评价记录
        review = ActivityReview(
            activity_id=activity_id,
            user_id=current_user.id,
            rating=rating,
            content_quality=content_quality,
            organization=organization,
            facility=facility,
            review=review_text,
            is_anonymous=is_anonymous
        )
        
        db.session.add(review)
        # 添加积分奖励
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
        if student_info:
            add_points(student_info.id, 5, "提交活动评价")
        
        db.session.commit()
        flash('评价提交成功！获得5积分奖励', 'success')
        log_action('submit_review', f'提交活动评价: {activity_id}')
        
        return redirect(url_for('student.activity_detail', id=activity_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting review: {e}")
        flash('提交评价时出错', 'danger')
        return redirect(url_for('student.review_activity', activity_id=activity_id))

@student_bp.route('/points/rank')
@login_required
def points_rank():
    from src.models import StudentInfo
    top_students = StudentInfo.query.order_by(StudentInfo.points.desc()).limit(100).all()
    return render_template('student/points_rank.html', top_students=top_students)

def get_recommended_activities(user_id, limit=6):
    """基于用户的历史参与记录和兴趣推荐活动"""
    try:
        # 获取用户信息
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=user_id)).scalar_one_or_none()
        if not student_info:
            return Activity.query.filter_by(status='active').order_by(Activity.created_at.desc()).limit(limit).all()
        
        # 获取用户历史参与的活动
        participated_activities = Activity.query.join(
            Registration, Activity.id == Registration.activity_id
        ).filter(
            Registration.user_id == user_id
        ).all()
        
        # 如果用户没有参与过任何活动，返回最新活动
        if not participated_activities:
            return Activity.query.filter_by(status='active').order_by(Activity.created_at.desc()).limit(limit).all()
        
        # 获取用户评价过的活动
        reviewed_activities = Activity.query.join(
            ActivityReview, Activity.id == ActivityReview.activity_id
        ).filter(
            ActivityReview.user_id == user_id,
            ActivityReview.rating >= 4  # 只考虑用户评价较高的活动
        ).all()
        
        # 构建推荐查询
        recommended = Activity.query.filter(
            Activity.status == 'active',
            Activity.id.notin_([a.id for a in participated_activities])  # 排除已参加的活动
        )
        
        # 如果有高评分活动，优先推荐类似活动
        if reviewed_activities:
            # 这里可以根据活动标题、描述等进行相似度匹配
            # 这是一个简化的实现，实际中可以使用更复杂的相似度算法
            liked_keywords = set()
            for activity in reviewed_activities:
                liked_keywords.update(activity.title.split())
                if activity.description:
                    liked_keywords.update(activity.description.split())
            
            if liked_keywords:
                recommended = recommended.filter(
                    db.or_(
                        *[Activity.title.ilike(f'%{keyword}%') for keyword in liked_keywords],
                        *[Activity.description.ilike(f'%{keyword}%') for keyword in liked_keywords]
                    )
                )
        
        # 根据活动开始时间排序，优先推荐最近的活动
        # 只推荐未结束的活动
        now = get_localized_now()
        recommended = recommended.filter(Activity.end_time > now).order_by(Activity.start_time.desc())
        
        return recommended.limit(limit).all()
    except Exception as e:
        logger.error(f"Error in getting recommended activities: {e}")
        return []

@student_bp.route('/recommend')
@login_required
def recommend():
    from src.models import Activity, Tag, Registration, StudentInfo
    # 获取当前学生已报名/参加过的活动标签
    stu_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
    joined_activities = Registration.query.filter_by(user_id=current_user.id).with_entities(Registration.activity_id).all()
    joined_ids = [a[0] for a in joined_activities]
    tag_ids = set()
    for act in Activity.query.filter(Activity.id.in_(joined_ids)).all():
        tag_ids.update([t.id for t in act.tags])
    # 推荐同标签的其他活动，排除已报名/参加过的
    now = get_localized_now()
    if tag_ids:
        recommended = Activity.query.join(Activity.tags).filter(
            Tag.id.in_(tag_ids),
            ~Activity.id.in_(joined_ids),
            Activity.status=='active',
            Activity.end_time > now
        ).distinct().all()
    else:
        recommended = Activity.query.filter(
            Activity.status=='active',
            Activity.end_time > now
        ).order_by(Activity.created_at.desc()).limit(10).all()
    return render_template('student/recommendation.html', recommended=recommended)

@student_bp.route('/api/attendance/checkin', methods=['POST'])
@student_required
@csrf.exempt  # 豁免CSRF保护
def checkin():
    try:
        # 从请求数据中获取 key 和 activity_id
        data = request.get_json()
        key = data.get('key') or data.get('checkin_key')
        activity_id = data.get('activity_id')

        logger.info(f"收到签到请求: 原始key={key}, 原始activity_id={activity_id}, 请求数据={data}")

        # 如果 key 看起来像一个 URL，尝试从 URL 中解析 activity_id 和 key
        if key and ('http://' in key or 'https://' in key or '/checkin/scan/' in key):
            try:
                from urllib.parse import urlparse
                parsed_url = urlparse(key)
                path_parts = parsed_url.path.strip('/').split('/')
                
                if len(path_parts) >= 4 and path_parts[0] == 'checkin' and path_parts[1] == 'scan':
                    # 提取 activity_id 和 checkin_key
                    parsed_activity_id = int(path_parts[2])
                    parsed_key = path_parts[3]
                    
                    # 如果原始请求中没有 activity_id，或者解析出的 activity_id 与原始请求不符，则使用解析出的
                    if not activity_id or activity_id != parsed_activity_id:
                        activity_id = parsed_activity_id
                        logger.info(f"从URL中解析出 activity_id: {activity_id}")
                    
                    # 使用解析出的 key
                    key = parsed_key
                    logger.info(f"从URL中解析出签到码: {key}")
            except Exception as e:
                logger.error(f"从URL提取签到码失败: {e}", exc_info=True)
                # 如果解析失败，继续使用原始 key 和 activity_id

        if not key or not activity_id:
            logger.warning(f"签到参数不完整: key={key}, activity_id={activity_id}")
            return jsonify({
                'success': False,
                'message': '签到参数不完整'
            })

        activity = db.session.get(Activity, activity_id)
        if not activity:
            logger.warning(f"签到活动不存在: activity_id={activity_id}")
            return jsonify({
                'success': False,
                'message': '活动不存在'
            })

        if activity.status != 'active':
            return jsonify({
                'success': False,
                'message': '该活动未在进行中，无法签到'
            })

        registration = db.session.execute(db.select(Registration).filter_by(
            user_id=current_user.id,
            activity_id=activity_id,
            status='registered'
        )).scalar_one_or_none()

        if not registration:
            return jsonify({
                'success': False,
                'message': '您尚未报名此活动，无法签到'
            })

        if registration.check_in_time:
            return jsonify({
                'success': False,
                'message': '您已经签到过了'
            })

        now = get_localized_now()
        
        # 记录签到码和活动的签到码，方便调试
        logger.info(f"签到码比对: 提供的签到码={key}, 活动签到码={activity.checkin_key}, 过期时间={activity.checkin_key_expires}")
        
        # 检查签到码是否有效
        if not activity.checkin_key or activity.checkin_key != key:
            logger.warning(f"签到码无效: 提供的={key}, 期望的={activity.checkin_key}")
            return jsonify({
                'success': False,
                'message': '签到码无效'
            })
            
        # 使用安全的时间比较函数来检查过期时间
        if activity.checkin_key_expires and safe_greater_than(now, activity.checkin_key_expires):
            logger.warning(f"签到码已过期: 当前时间={now}, 过期时间={activity.checkin_key_expires}")
            return jsonify({
                'success': False,
                'message': '签到码已过期'
            })

        # 签到成功，更新记录
        registration.check_in_time = now
        registration.status = 'attended'
        db.session.commit()

        # 添加积分
        try:
            points = activity.points if activity.points else 5
            points_reason = f"参加活动: {activity.title}"
            
            student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
            if student_info:
                student_info.points = (student_info.points or 0) + points
                
                points_history = PointsHistory(
                    student_id=student_info.id,
                    points=points,
                    reason=points_reason,
                    activity_id=activity_id,
                    created_at=now
                )
                db.session.add(points_history)
                db.session.commit()
                
                log_action('checkin', f'用户 {current_user.username} 签到活动: {activity.title}, 获得 {points} 积分')
        except Exception as e:
            logger.error(f"记录积分失败: {e}")

        return jsonify({
            'success': True,
            'message': '签到成功！',
            'points': activity.points or 5
        })
    
    except Exception as e:
        logger.error(f"签到过程出错: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': '服务器错误，请重试'
        })

# 注意：get_localized_now函数已在time_helpers中定义，无需重复定义

@student_bp.route('/messages')
@student_required
def messages():
    try:
        page = request.args.get('page', 1, type=int)
        filter_type = request.args.get('filter', 'all')
        
        # 根据过滤类型查询消息
        if filter_type == 'sent':
            query = Message.query.filter_by(sender_id=current_user.id)
        elif filter_type == 'received':
            query = Message.query.filter_by(receiver_id=current_user.id)
        else:  # 'all'
            query = Message.query.filter(or_(
                Message.sender_id == current_user.id,
                Message.receiver_id == current_user.id
            ))
        
        # 不使用复杂的连接，保持简单查询
        messages = query.order_by(Message.created_at.desc()).paginate(page=page, per_page=10)
        
        return render_template('student/messages.html', 
                              messages=messages, 
                              filter_type=filter_type,
                              display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in messages page: {e}")
        flash('加载消息列表时出错', 'danger')
        return redirect(url_for('student.dashboard'))

@student_bp.route('/message/<int:id>')
@student_required
def view_message(id):
    try:
        logger.info(f"学生 {current_user.username} 查看消息ID: {id}")
        message = db.get_or_404(Message, id)
        
        # 验证当前用户是否是消息的发送者或接收者
        if message.sender_id != current_user.id and message.receiver_id != current_user.id:
            logger.warning(f"用户 {current_user.username} 尝试查看无权限的消息 {id}")
            flash('您无权查看此消息', 'danger')
            return redirect(url_for('student.messages'))
        
        # 如果当前用户是接收者且消息未读，则标记为已读
        if message.receiver_id == current_user.id and not message.is_read:
            logger.info(f"标记消息 {id} 为已读")
            message.is_read = True
            db.session.commit()
        
        # 预加载发送者和接收者信息，避免在模板中引发懒加载
        sender = db.session.get(User, message.sender_id) if message.sender_id else None
        receiver = db.session.get(User, message.receiver_id) if message.receiver_id else None
        
        sender_info = None
        receiver_info = None
        
        if sender and hasattr(sender, 'student_info'):
            sender_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=sender.id)).scalar_one_or_none()
        
        if receiver and hasattr(receiver, 'student_info'):
            receiver_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=receiver.id)).scalar_one_or_none()
        
        logger.info(f"成功加载消息: {message.subject}")
        return render_template('student/message_view.html', 
                             message=message,
                             sender=sender,
                             receiver=receiver,
                             sender_info=sender_info,
                             receiver_info=receiver_info,
                             display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in view_message: {e}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        flash('查看消息时出错', 'danger')
        return redirect(url_for('student.messages'))

@student_bp.route('/message/create', methods=['GET', 'POST'])
@student_required
def create_message():
    try:
        # 创建一个空表单对象用于CSRF保护
        class MessageForm(FlaskForm):
            subject = StringField('主题', validators=[DataRequired(message='主题不能为空')])
            content = TextAreaField('内容', validators=[DataRequired(message='内容不能为空')])
            submit = SubmitField('发送消息')
        
        form = MessageForm()
        
        if request.method == 'POST' and form.validate_on_submit():
            subject = form.subject.data
            content = form.content.data
            
            # 创建消息，发送给管理员
            # 查找管理员用户
            admin_role = db.session.query(Role).filter_by(name='Admin').first()
            if not admin_role:
                flash('无法找到管理员，请联系系统管理员', 'danger')
                return redirect(url_for('student.messages'))
            
            admin_user = db.session.execute(db.select(User).filter_by(role_id=admin_role.id)).scalar_one_or_none()
            if not admin_user:
                flash('无法找到管理员，请联系系统管理员', 'danger')
                return redirect(url_for('student.messages'))
            
            # 创建消息
            message = Message(
                sender_id=current_user.id,
                receiver_id=admin_user.id,
                subject=subject,
                content=content,
                created_at=get_localized_now()
            )
            
            db.session.add(message)
            db.session.commit()
            
            log_action('send_message', f'发送消息给管理员: {subject}')
            flash('消息发送成功', 'success')
            return redirect(url_for('student.messages'))
        
        return render_template('student/message_form.html', title='发送消息', form=form)
    except Exception as e:
        logger.error(f"Error in create_message: {e}")
        flash('发送消息时出错', 'danger')
        return redirect(url_for('student.messages'))

@student_bp.route('/message/<int:id>/delete', methods=['POST'])
@student_required
@csrf.exempt  # 豁免CSRF保护
def delete_message(id):
    try:
        message = db.get_or_404(Message, id)
        
        # 验证当前用户是否是消息的发送者或接收者
        if message.sender_id != current_user.id and message.receiver_id != current_user.id:
            flash('您无权删除此消息', 'danger')
            return redirect(url_for('student.messages'))
        
        # 删除消息
        db.session.delete(message)
        db.session.commit()
        
        log_action('delete_message', f'删除消息: {message.subject}')
        flash('消息已删除', 'success')
        return redirect(url_for('student.messages'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_message: {e}")
        flash('删除消息时出错', 'danger')
        return redirect(url_for('student.messages'))

@student_bp.route('/notifications')
@student_required
def notifications():
    try:
        page = request.args.get('page', 1, type=int)
        
        # 获取当前时间，确保带有时区信息
        now = ensure_timezone_aware(datetime.now())
        
        # 获取有效的通知（未过期或无过期日期）
        notifications = Notification.query.filter(
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            )
        ).order_by(Notification.is_important.desc(), Notification.created_at.desc()).paginate(page=page, per_page=10)
        
        # 获取当前用户已读通知的ID列表
        read_notification_ids = db.session.query(NotificationRead.notification_id).filter(
            NotificationRead.user_id == current_user.id
        ).all()
        read_notification_ids = [r[0] for r in read_notification_ids]
        
        return render_template('student/notifications.html', 
                              notifications=notifications,
                              read_notification_ids=read_notification_ids,
                              display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in notifications page: {e}")
        flash('加载通知列表时出错', 'danger')
        return redirect(url_for('student.dashboard'))

@student_bp.route('/notification/<int:id>')
@student_required
def view_notification(id):
    try:
        notification = db.get_or_404(Notification, id)
        
        # 标记为已读
        read_record = db.session.execute(db.select(NotificationRead).filter_by(
            notification_id=id,
            user_id=current_user.id
        )).scalar_one_or_none()
        
        if not read_record:
            read_record = NotificationRead(
                notification_id=id,
                user_id=current_user.id
            )
            db.session.add(read_record)
            db.session.commit()
        
        return render_template('student/notification_view.html', 
                              notification=notification,
                              display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in view_notification: {e}")
        flash('查看通知时出错', 'danger')
        return redirect(url_for('student.notifications'))

@student_bp.route('/notification/<int:id>/mark_read', methods=['POST'])
@student_required
def mark_notification_read(id):
    try:
        notification = db.get_or_404(Notification, id)
        
        # 检查是否已经标记为已读
        read_record = db.session.execute(db.select(NotificationRead).filter_by(
            notification_id=id,
            user_id=current_user.id
        )).scalar_one_or_none()
        
        if not read_record:
            read_record = NotificationRead(
                notification_id=id,
                user_id=current_user.id
            )
            db.session.add(read_record)
            db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error in mark_notification_read: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@student_bp.route('/api/notifications/unread')
@student_required
def get_unread_notifications():
    try:
        # 获取当前时间，确保带有时区信息
        now = ensure_timezone_aware(datetime.now())
        
        # 获取未读的重要通知
        important_notifications = Notification.query.filter(
            Notification.is_important == True,
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            ),
            ~Notification.id.in_(
                db.session.query(NotificationRead.notification_id).filter(
                    NotificationRead.user_id == current_user.id
                )
            )
        ).order_by(Notification.created_at.desc()).all()
        
        # 格式化通知数据
        notifications_data = []
        for notification in important_notifications:
            notifications_data.append({
                'id': notification.id,
                'title': notification.title,
                'content': notification.content,
                'created_at': notification.created_at.strftime('%Y-%m-%d %H:%M')
            })
        
        return jsonify({
            'success': True,
            'notifications': notifications_data
        })
    except Exception as e:
        logger.error(f"Error in get_unread_notifications: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@student_bp.route('/api/messages/unread_count')
@login_required
def unread_message_count():
    try:
        # 检查用户是否有权限访问消息
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'count': 0, 'error': '未登录'})

        # 管理员可能没有消息，返回0
        if hasattr(current_user, 'role') and current_user.role and current_user.role.name == 'Admin':
            return jsonify({'success': True, 'count': 0})

        count = db.session.query(func.count(Message.id)).filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).scalar()
        return jsonify({'success': True, 'count': count or 0})
    except Exception as e:
        logger.error(f"Error getting unread message count: {e}")
        return jsonify({'success': False, 'count': 0, 'error': str(e)}), 500
