from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, current_app, abort, session, Response
from flask_login import login_required, current_user
from src.models import db, Activity, Registration, User, StudentInfo, PointsHistory, ActivityReview, Tag, Message, Notification, NotificationRead, Role, Society
from datetime import datetime, timedelta
import logging
import json
from functools import wraps
from src.routes.utils import log_action, random_string
from sqlalchemy import func, desc, or_, and_, not_
from sqlalchemy.exc import IntegrityError
from wtforms import StringField, TextAreaField, IntegerField, SelectField, SubmitField, RadioField, BooleanField, HiddenField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email, Regexp
from flask_wtf import FlaskForm
from src.utils.time_helpers import get_localized_now, ensure_timezone_aware, display_datetime, safe_compare, safe_less_than, safe_greater_than, safe_greater_than_equal, safe_less_than_equal, get_activity_status, is_activity_completed
from src.utils import get_compatible_paginate
from sqlalchemy.orm import joinedload, defer
import pytz
import os
from flask_wtf.csrf import CSRFProtect
from src import cache, limiter
from src.utils.input_safety import sanitize_plain_text
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

logger = logging.getLogger(__name__)

student_bp = Blueprint('student', __name__, url_prefix='/student')

# 创建CSRF保护实例
csrf = CSRFProtect()


def _build_email_change_token(user_id, old_email, new_email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(
        {
            'uid': int(user_id),
            'old_email': str(old_email or ''),
            'new_email': str(new_email or ''),
            'purpose': 'email-change'
        },
        salt=f"{current_app.config.get('SECURITY_PASSWORD_SALT', 'cqnu-association-salt')}:email-change"
    )


def _verify_email_change_token(token, max_age=86400):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = serializer.loads(
            token,
            max_age=max_age,
            salt=f"{current_app.config.get('SECURITY_PASSWORD_SALT', 'cqnu-association-salt')}:email-change"
        )
    except SignatureExpired:
        return None, '邮箱更换链接已过期，请重新提交邮箱变更申请。'
    except BadSignature:
        return None, '邮箱更换链接无效，请重新提交邮箱变更申请。'

    if not isinstance(data, dict) or data.get('purpose') != 'email-change':
        return None, '邮箱更换链接无效，请重新提交邮箱变更申请。'

    try:
        return {
            'uid': int(data.get('uid')),
            'old_email': str(data.get('old_email') or ''),
            'new_email': str(data.get('new_email') or '')
        }, None
    except Exception:
        return None, '邮箱更换链接无效，请重新提交邮箱变更申请。'


def _send_email_change_verification_email(user, new_email):
    from src.routes.auth import _send_html_email

    token = _build_email_change_token(user.id, user.email, new_email)
    verify_url = url_for('student.verify_email_change', token=token, _external=True)
    html_body = render_template(
        'email/change_email_verify.html',
        user=user,
        new_email=new_email,
        verify_url=verify_url
    )
    _send_html_email('邮箱变更验证', new_email, html_body)
    return verify_url


@cache.memoize(timeout=30)
def _cached_registered_activity_ids(user_id):
    reg_stmt = db.select(Registration.activity_id).filter(
        Registration.user_id == user_id,
        Registration.status.in_(['registered', 'attended'])
    )
    registered = db.session.execute(reg_stmt).all()
    return [r[0] for r in registered]

def _ensure_activity_start_reminders(user_id):
    """为学生生成活动开始前提醒：提前1天、3小时、1小时。"""
    try:
        now = get_localized_now()
        reminders = [
            ('1天', timedelta(days=1)),
            ('3小时', timedelta(hours=3)),
            ('1小时', timedelta(hours=1))
        ]

        registrations = db.session.execute(
            db.select(Registration).filter(
                Registration.user_id == user_id,
                Registration.status.in_(['registered', 'attended'])
            ).options(joinedload(Registration.activity))
        ).scalars().all()

        created = 0
        for reg in registrations:
            activity = reg.activity
            if not activity or activity.status != 'active' or not activity.start_time:
                continue

            for label, delta in reminders:
                reminder_time = activity.start_time - delta
                if now < reminder_time:
                    continue

                title = f"活动即将开始提醒：{activity.title}"
                content = f"你报名的活动《{activity.title}》将在{label}后开始，请提前安排时间。"

                exists = db.session.execute(
                    db.select(Notification).filter(
                        Notification.title == title,
                        Notification.content == content,
                        Notification.created_by == user_id,
                        Notification.is_public == False
                    )
                ).scalar_one_or_none()

                if exists:
                    continue

                notice = Notification(
                    title=title,
                    content=content,
                    is_important=True,
                    created_at=now,
                    created_by=user_id,
                    expiry_date=activity.start_time + timedelta(days=1),
                    is_public=False
                )
                db.session.add(notice)
                created += 1

        if created > 0:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"生成活动开始提醒失败: {e}")


def _create_registration_success_notification(user_id, activity):
    """在报名成功后给学生发送活动额外提示（若管理员配置了文案）。"""
    if not activity:
        return

    extra_message = sanitize_plain_text(
        getattr(activity, 'registration_success_message', None),
        allow_multiline=True,
        max_length=1000
    )
    if not extra_message:
        return

    notice = Notification(
        title=f"活动报名成功：{activity.title}",
        content=f"你已成功报名《{activity.title}》。\n\n{extra_message}",
        is_important=True,
        created_at=get_localized_now(),
        created_by=user_id,
        is_public=False
    )
    db.session.add(notice)

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


def _current_student_society_id():
    try:
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
        if not student_info:
            return None
        if getattr(student_info, 'society_id', None):
            return student_info.society_id
        joined = getattr(student_info, 'joined_societies', []) or []
        return joined[0].id if joined else None
    except Exception:
        return None


def _current_student_society_ids():
    try:
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
        if not student_info:
            return []
        ids = set()
        if getattr(student_info, 'society_id', None):
            ids.add(student_info.society_id)
        for s in (getattr(student_info, 'joined_societies', []) or []):
            if s and s.id:
                ids.add(s.id)
        return sorted(ids)
    except Exception:
        return []


def _ensure_student_join_society(student_info, society_id):
    if not student_info or not society_id:
        return
    # 学生完成初始标签/社团选择后，手动选择规则优先，不再自动并入管理社团名单
    if getattr(student_info, 'has_selected_tags', False):
        return
    society = db.session.get(Society, society_id)
    if not society:
        return
    joined = list(student_info.joined_societies or [])
    if joined:
        return
    joined_ids = {s.id for s in joined}
    if society_id not in joined_ids:
        student_info.joined_societies.append(society)
    if not getattr(student_info, 'society_id', None):
        student_info.society_id = society_id

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

        has_tags = bool(getattr(student_info, 'tags', []) or [])
        has_society = bool(getattr(student_info, 'society_id', None)) or bool(getattr(student_info, 'joined_societies', []) or [])
        if (not getattr(student_info, 'has_selected_tags', False)) or (not has_tags) or (not has_society):
            flash('请先完成社团和兴趣标签选择后再继续使用。', 'warning')
            return redirect(url_for('auth.select_tags'))
        
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
            deleted_notification_ids_subq = db.session.query(NotificationRead.notification_id).filter(
                NotificationRead.user_id == current_user.id,
                NotificationRead.is_deleted.is_(True)
            )

            # 获取公开通知和针对当前用户的通知
            notif_stmt = db.select(Notification).filter(
                or_(
                    Notification.is_public == True,  # 公开通知
                    and_(
                        Notification.is_public == False,  # 私人通知
                        Notification.created_by == current_user.id  # 发给当前用户的
                    )
                ),
                Notification.title.isnot(None),
                Notification.content.isnot(None),
                ~Notification.id.in_(deleted_notification_ids_subq),
                ~Notification.id.in_(
                    db.session.query(NotificationRead.notification_id).filter(
                        NotificationRead.user_id == current_user.id
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
        keyword = (request.args.get('q', '', type=str) or '').strip()
        selected_tag_id = request.args.get('tag_id', type=int)
        selected_society_id = request.args.get('society_id', type=int)

        tags = db.session.execute(db.select(Tag).order_by(Tag.name.asc())).scalars().all()
        societies = db.session.execute(
            db.select(Society).order_by(Society.is_active.desc(), Society.name.asc())
        ).scalars().all()
        
        # 基本查询 - 所有活动
        query = db.select(Activity).options(
            defer(Activity.poster_data),
            joinedload(Activity.tags),
            joinedload(Activity.society)
        )

        if selected_tag_id:
            query = query.join(Activity.tags).filter(Tag.id == selected_tag_id)

        if selected_society_id:
            query = query.filter(Activity.society_id == selected_society_id)

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.outerjoin(Society, Activity.society_id == Society.id).filter(
                or_(
                    Activity.title.ilike(keyword_like),
                    Activity.description.ilike(keyword_like),
                    Society.name.ilike(keyword_like)
                )
            )

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
        query = query.distinct().order_by(Activity.start_time)
            
        # 分页
        activities = get_compatible_paginate(db, query, page=page, per_page=10, error_out=False)
        
        # 查询用户已报名的活动ID（只包含已报名和已签到的，不包括已取消的）
        registered_activity_ids = _cached_registered_activity_ids(current_user.id)
        
        # 从time_helpers导入时间比较函数
        from src.utils.time_helpers import safe_less_than, safe_greater_than, safe_compare, safe_less_than_equal, display_datetime
        
        return render_template(
            'student/activities.html',
            activities=activities,
            registered_activity_ids=registered_activity_ids,
            now=now,
            current_status=current_status,
            keyword=keyword,
            selected_tag_id=selected_tag_id,
            selected_society_id=selected_society_id,
            tags=tags,
            societies=societies,
            safe_less_than=safe_less_than,
            safe_greater_than=safe_greater_than,
            safe_compare=safe_compare,
            safe_less_than_equal=safe_less_than_equal,
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
        activity = db.session.execute(
            db.select(Activity).where(Activity.id == id).options(defer(Activity.poster_data))
        ).scalar_one_or_none()
        if not activity:
            abort(404)
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
            (activity.registration_start_time is None or safe_less_than_equal(activity.registration_start_time, now)) and
            (activity.registration_deadline is None or safe_greater_than(activity.registration_deadline, now)) and
            (activity.max_participants == 0 or total_registered < activity.max_participants)
        )

        can_cancel = has_registered and safe_greater_than(activity.start_time, now)

        can_checkin = (
            has_registered and 
            not has_checked_in and 
            activity.checkin_enabled
        )

        current_user_review = db.session.execute(db.select(ActivityReview).filter_by(activity_id=id, user_id=current_user.id)).scalar_one_or_none()
        review_count = db.session.execute(
            db.select(func.count()).select_from(ActivityReview).filter_by(activity_id=id)
        ).scalar() or 0

        reviews = db.session.execute(
            db.select(ActivityReview)
            .filter_by(activity_id=id)
            .order_by(ActivityReview.created_at.desc())
            .limit(5)
        ).scalars().all()

        agg_stats = None
        if review_count > 0:
            agg_stats = db.session.execute(
                db.select(
                    func.avg(ActivityReview.rating),
                    func.avg(ActivityReview.content_quality),
                    func.avg(ActivityReview.organization),
                    func.avg(ActivityReview.facility)
                ).filter_by(activity_id=id)
            ).one()

        beijing_tz = pytz.timezone('Asia/Shanghai')
        for review in reviews:
            if review.created_at:
                if review.created_at.tzinfo is None:
                    review.display_created_at = beijing_tz.localize(review.created_at).strftime('%Y-%m-%d %H:%M')
                else:
                    review.display_created_at = review.created_at.astimezone(beijing_tz).strftime('%Y-%m-%d %H:%M')
            else:
                review.display_created_at = '未设置'

        average_rating = float(agg_stats[0] or 0) if agg_stats else 0
        avg_content_quality = float(agg_stats[1] or 0) if agg_stats else 0
        avg_organization = float(agg_stats[2] or 0) if agg_stats else 0
        avg_facility = float(agg_stats[3] or 0) if agg_stats else 0

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
                if weather_data:
                    logger.info(f"获取活动天气数据成功: {weather_data.get('description', 'N/A')}")
                else:
                    logger.info("本次未获取到活动天气数据（已降级为无天气展示）")
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
        activity = db.session.execute(
            db.select(Activity).where(Activity.id == id).with_for_update()
        ).scalar_one_or_none()
        if not activity:
            return jsonify({'success': False, 'message': '活动不存在'})

        if activity.status != 'active':
            return jsonify({'success': False, 'message': '该活动不在进行中，无法报名'})

        now = get_localized_now()
        if activity.registration_start_time and safe_greater_than(activity.registration_start_time, now):
            return jsonify({'success': False, 'message': '报名尚未开始'})

        if activity.registration_deadline and safe_less_than(activity.registration_deadline, now):
            return jsonify({'success': False, 'message': '该活动已过报名截止时间'})

        existing_reg = db.session.execute(db.select(Registration).filter_by(user_id=current_user.id, activity_id=id)).scalar_one_or_none()
        if existing_reg:
            if existing_reg.status == 'registered':
                return jsonify({'success': False, 'message': '您已报名此活动'})
            elif existing_reg.status == 'cancelled':
                if activity.max_participants > 0:
                    reg_count = db.session.execute(
                        db.select(func.count()).select_from(Registration).filter(
                            Registration.activity_id == id,
                            Registration.status.in_(['registered', 'attended'])
                        )
                    ).scalar() or 0
                    if reg_count >= activity.max_participants:
                        return jsonify({'success': False, 'message': '该活动报名人数已满'})

                existing_reg.status = 'registered'
                existing_reg.register_time = now
                student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
                if student_info and activity.society_id:
                    _ensure_student_join_society(student_info, activity.society_id)
                _create_registration_success_notification(current_user.id, activity)
                db.session.commit()
                return jsonify({'success': True, 'message': '已成功重新报名活动'})

        if activity.max_participants > 0:
            reg_count = db.session.execute(
                db.select(func.count()).select_from(Registration).filter(
                    Registration.activity_id == id,
                    Registration.status.in_(['registered', 'attended'])
                )
            ).scalar() or 0
            if reg_count >= activity.max_participants:
                return jsonify({'success': False, 'message': '该活动报名人数已满'})

        new_registration = Registration(
            user_id=current_user.id,
            activity_id=id,
            register_time=now,
            status='registered'
        )
        db.session.add(new_registration)

        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
        if student_info and activity.society_id:
            _ensure_student_join_society(student_info, activity.society_id)

        _create_registration_success_notification(current_user.id, activity)

        db.session.commit()
        cache.delete_memoized(_cached_registered_activity_ids, current_user.id)

        return jsonify({'success': True, 'message': '报名成功！'})
    except IntegrityError:
        db.session.rollback()
        logger.warning(f"并发报名触发唯一约束: user_id={current_user.id}, activity_id={id}")
        return jsonify({'success': False, 'message': '您已报名此活动'})
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
        cache.delete_memoized(_cached_registered_activity_ids, current_user.id)

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
        keyword = (request.args.get('q', '', type=str) or '').strip()
        selected_tag_id = request.args.get('tag_id', type=int)
        selected_society_id = request.args.get('society_id', type=int)
        
        # 使用北京时间进行状态判定
        from src.utils.time_helpers import get_localized_now, display_datetime, safe_less_than, safe_greater_than, safe_compare, get_activity_status, is_activity_completed
        now = get_localized_now()
        logger.info(f"my_activities - 当前北京时间: {now}")
        logger.info(f"my_activities - 用户ID: {current_user.id}, 状态筛选: {status}")
        
        # 使用别名避免表连接问题
        from sqlalchemy.orm import aliased
        ActivityAlias = aliased(Activity)
        SocietyAlias = aliased(Society)
        TagAlias = aliased(Tag)

        tags = db.session.execute(db.select(Tag).order_by(Tag.name.asc())).scalars().all()
        societies = db.session.execute(
            db.select(Society).order_by(Society.is_active.desc(), Society.name.asc())
        ).scalars().all()
        
        # 基本查询 - 获取用户的所有报名记录
        query = Registration.query.filter_by(user_id=current_user.id).join(ActivityAlias, ActivityAlias.id == Registration.activity_id)
        
        # 记录查询到的报名记录数量
        count = query.count()
        logger.info(f"my_activities - 找到 {count} 条报名记录")
        
        # 根据状态筛选
        if status == 'active':
            query = query.filter(ActivityAlias.status == 'active')
        elif status == 'completed':
            query = query.filter(ActivityAlias.status == 'completed')
        elif status == 'cancelled':
            query = query.filter_by(status='cancelled')

        if selected_tag_id:
            query = query.join(ActivityAlias.tags.of_type(TagAlias)).filter(TagAlias.id == selected_tag_id)

        if selected_society_id:
            query = query.filter(ActivityAlias.society_id == selected_society_id)

        if keyword:
            keyword_like = f"%{keyword}%"
            query = query.outerjoin(SocietyAlias, ActivityAlias.society_id == SocietyAlias.id).filter(
                or_(
                    ActivityAlias.title.ilike(keyword_like),
                    ActivityAlias.description.ilike(keyword_like),
                    SocietyAlias.name.ilike(keyword_like)
                )
            )
        
        # 获取报名记录，并预加载活动信息
        query = query.options(
            joinedload(Registration.activity).joinedload(Activity.tags),
            joinedload(Registration.activity).joinedload(Activity.society)
        )
        
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
        reviewed_activity_ids = set(
            db.session.execute(db.select(ActivityReview.activity_id).filter_by(user_id=current_user.id)).scalars().all()
        )
        pending_reviews = [
            reg.activity_id for reg in registrations.items
            if reg.activity and reg.activity.status == 'completed' and reg.activity_id not in reviewed_activity_ids
        ]
        
        # 确保模板中能正确处理数据
        return render_template('student/my_activities.html', 
                              registrations=registrations,
                              current_status=status,
                              keyword=keyword,
                              selected_tag_id=selected_tag_id,
                              selected_society_id=selected_society_id,
                              tags=tags,
                              societies=societies,
                              pending_reviews=pending_reviews,
                              reviewed_activity_ids=reviewed_activity_ids,
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
        
        joined_societies = student_info.joined_societies if getattr(student_info, 'joined_societies', None) else []
        return render_template('student/profile.html', student_info=student_info, joined_societies=joined_societies)
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
            requested_email = (request.form.get('email') or '').strip()
            email_change_requested = requested_email and requested_email != (current_user.email or '')
            if email_change_requested:
                email_exists = db.session.execute(
                    db.select(User).filter(User.email == requested_email, User.id != current_user.id)
                ).scalar_one_or_none()
                if email_exists:
                    flash('该邮箱已被其他账号使用，请更换。', 'warning')
                    return redirect(url_for('student.edit_profile'))

            phone = (form.phone.data or '').strip()
            phone_exists = db.session.execute(
                db.select(StudentInfo).filter(
                    StudentInfo.phone == phone,
                    StudentInfo.user_id != current_user.id
                )
            ).scalar_one_or_none()
            if phone_exists:
                flash('该手机号已被其他账号使用，请更换。', 'warning')
                return redirect(url_for('student.edit_profile'))

            student_info.real_name = form.real_name.data
            student_info.grade = form.grade.data
            student_info.major = form.major.data
            student_info.college = form.college.data
            student_info.phone = phone
            student_info.qq = form.qq.data

            selected_society_ids = [int(sid) for sid in request.form.getlist('societies') if sid and str(sid).isdigit()]
            selected_societies = db.session.execute(
                db.select(Society).filter(Society.id.in_(selected_society_ids), Society.is_active == True)
            ).scalars().all() if selected_society_ids else []
            student_info.joined_societies = selected_societies
            if selected_societies:
                selected_id_set = {s.id for s in selected_societies}
                if student_info.society_id not in selected_id_set:
                    student_info.society_id = selected_societies[0].id
            else:
                student_info.society_id = None
            
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
            if email_change_requested:
                try:
                    _send_email_change_verification_email(current_user, requested_email)
                    flash('资料更新成功！邮箱变更验证链接已发送到新邮箱，完成验证后才会生效。', 'success')
                except Exception as e:
                    logger.error(f"发送邮箱变更验证邮件失败: user_id={current_user.id}, error={e}", exc_info=True)
                    flash('资料更新成功！但邮箱变更验证邮件发送失败，请稍后重试。', 'warning')
                return redirect(url_for('student.profile'))

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
        all_societies = db.session.execute(db.select(Society).filter_by(is_active=True).order_by(Society.name.asc())).scalars().all()
        selected_society_ids = [s.id for s in (student_info.joined_societies or [])]
        if student_info.society_id and student_info.society_id not in selected_society_ids:
            selected_society_ids.append(student_info.society_id)
        
        return render_template('student/edit_profile.html', form=form, all_tags=all_tags, selected_tag_ids=selected_tag_ids, all_societies=all_societies, selected_society_ids=selected_society_ids)
    except Exception as e:
        logger.error(f"Error in edit profile: {e}")
        flash('编辑个人资料时发生错误', 'danger')
        return redirect(url_for('student.profile'))


@student_bp.route('/verify-email-change/<token>')
def verify_email_change(token):
    token_data, error = _verify_email_change_token(token)
    if error:
        flash(error, 'danger')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, token_data['uid'])
    if not user:
        flash('账号不存在或已被删除。', 'danger')
        return redirect(url_for('auth.login'))

    if (user.email or '') != token_data.get('old_email', ''):
        flash('当前账号邮箱已变更，此链接已失效，请重新提交邮箱变更申请。', 'warning')
        return redirect(url_for('student.edit_profile') if current_user.is_authenticated else url_for('auth.login'))

    new_email = (token_data.get('new_email') or '').strip()
    if not new_email:
        flash('新邮箱信息无效，请重新提交邮箱变更申请。', 'danger')
        return redirect(url_for('student.edit_profile') if current_user.is_authenticated else url_for('auth.login'))

    email_exists = db.session.execute(
        db.select(User).filter(User.email == new_email, User.id != user.id)
    ).scalar_one_or_none()
    if email_exists:
        flash('该邮箱已被其他账号使用，请更换后重试。', 'warning')
        return redirect(url_for('student.edit_profile') if current_user.is_authenticated else url_for('auth.login'))

    try:
        user.email = new_email
        db.session.commit()
        flash('新邮箱验证成功，账号邮箱已更新。', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"邮箱变更落库失败: user_id={user.id}, error={e}", exc_info=True)
        flash('邮箱更新失败，请稍后重试。', 'danger')

    return redirect(url_for('student.profile') if current_user.is_authenticated else url_for('auth.login'))

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
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
        if not student_info:
            flash('请先完善个人信息', 'warning')
            return redirect(url_for('student.edit_profile'))

        page = request.args.get('page', 1, type=int)
        query = db.select(PointsHistory).filter_by(student_id=student_info.id).order_by(PointsHistory.created_at.desc())
        points_history = get_compatible_paginate(db, query, page=page, per_page=15, error_out=False)

        beijing_tz = pytz.timezone('Asia/Shanghai')
        for history in points_history.items:
            if history.created_at:
                if history.created_at.tzinfo is None:
                    localized = beijing_tz.localize(history.created_at)
                else:
                    localized = history.created_at.astimezone(beijing_tz)
                history.display_created_at = localized.strftime('%Y-%m-%d %H:%M')
            else:
                history.display_created_at = '未设置'
        
        return render_template('student/points.html', 
                             student_info=student_info,
                             points_history=points_history)
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
                activity_id=activity_id,
                society_id=student.society_id
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
        registration = db.session.execute(
            db.select(Registration).filter(
                Registration.activity_id == activity_id,
                Registration.user_id == current_user.id,
                or_(
                    Registration.status == 'attended',
                    Registration.check_in_time.isnot(None)
                )
            )
        ).scalar_one_or_none()
        
        if not registration:
            flash('只有参加过活动的学生才能评价', 'warning')
            return redirect(url_for('student.activity_detail', id=activity_id))
        
        # 检查是否已评价过（已评价则进入编辑）
        existing_review = db.session.execute(db.select(ActivityReview).filter_by(
            activity_id=activity_id,
            user_id=current_user.id
        )).scalar_one_or_none()

        return render_template('student/review.html', activity=activity, existing_review=existing_review)
    except Exception as e:
        logger.error(f"Error in review activity page: {e}")
        flash('加载评价页面时出错', 'danger')
        return redirect(url_for('student.my_activities'))

@student_bp.route('/activity/<int:activity_id>/submit-review', methods=['POST'])
@login_required
def submit_review(activity_id):
    try:
        activity = db.get_or_404(Activity, activity_id)
        if activity.status != 'completed':
            flash('只能评价已结束的活动', 'warning')
            return redirect(url_for('student.activity_detail', id=activity_id))

        registration = db.session.execute(
            db.select(Registration).filter(
                Registration.activity_id == activity_id,
                Registration.user_id == current_user.id,
                or_(
                    Registration.status == 'attended',
                    Registration.check_in_time.isnot(None)
                )
            )
        ).scalar_one_or_none()

        if not registration:
            flash('只有参加过活动的学生才能评价', 'warning')
            return redirect(url_for('student.activity_detail', id=activity_id))

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

        for score in [content_quality, organization, facility]:
            if score is not None and not (1 <= score <= 5):
                flash('评价维度分值必须在1-5之间', 'warning')
                return redirect(url_for('student.review_activity', activity_id=activity_id))

        if len(review_text) < 10:
            flash('请至少输入10个字的评价内容', 'warning')
            return redirect(url_for('student.review_activity', activity_id=activity_id))

        existing_review = db.session.execute(
            db.select(ActivityReview).filter_by(activity_id=activity_id, user_id=current_user.id)
        ).scalar_one_or_none()

        is_new_review = existing_review is None
        
        if is_new_review:
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

            student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=current_user.id)).scalar_one_or_none()
            if student_info:
                student_info.points += 5
                db.session.add(PointsHistory(
                    student_id=student_info.id,
                    points=5,
                    reason='提交活动评价',
                    activity_id=activity_id,
                    society_id=student_info.society_id
                ))

            db.session.commit()
            flash('评价提交成功！获得5积分奖励', 'success')
            log_action('submit_review', f'提交活动评价: {activity_id}')
        else:
            existing_review.rating = rating
            existing_review.content_quality = content_quality
            existing_review.organization = organization
            existing_review.facility = facility
            existing_review.review = review_text
            existing_review.is_anonymous = is_anonymous

            db.session.commit()
            flash('评价更新成功', 'success')
            log_action('update_review', f'更新活动评价: {activity_id}')
        
        return redirect(url_for('student.activity_detail', id=activity_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error submitting review: {e}")
        flash('提交评价时出错', 'danger')
        return redirect(url_for('student.review_activity', activity_id=activity_id))

@student_bp.route('/points/rank')
@login_required
def points_rank():
    society_ids = _current_student_society_ids()
    student_info = db.session.execute(
        db.select(StudentInfo).filter_by(user_id=current_user.id)
    ).scalar_one_or_none()

    # 全站总积分榜
    total_top_students = db.session.execute(
        db.select(StudentInfo)
        .join(User, User.id == StudentInfo.user_id)
        .join(Role, Role.id == User.role_id)
        .filter(Role.name == 'Student')
        .order_by(StudentInfo.points.desc(), StudentInfo.id.asc())
        .limit(100)
    ).scalars().all()

    total_current_student_points = 0
    total_current_student_rank = None
    if student_info:
        total_current_student_points = int(student_info.points or 0)
        higher_points_count = db.session.execute(
            db.select(func.count(StudentInfo.id))
            .join(User, User.id == StudentInfo.user_id)
            .join(Role, Role.id == User.role_id)
            .filter(
                Role.name == 'Student',
                func.coalesce(StudentInfo.points, 0) > total_current_student_points
            )
        ).scalar_one()
        total_current_student_rank = int(higher_points_count or 0) + 1

    # 多社团积分榜：按每个社团单独聚合 points_history.society_id
    societies = (
        db.session.execute(
            db.select(Society).filter(Society.id.in_(society_ids)).order_by(Society.name)
        ).scalars().all()
        if society_ids else []
    )

    society_boards = []
    for society in societies:
        rows = db.session.execute(
            db.select(
                StudentInfo,
                func.coalesce(func.sum(PointsHistory.points), 0).label('society_points')
            )
            .outerjoin(
                PointsHistory,
                and_(
                    PointsHistory.student_id == StudentInfo.id,
                    PointsHistory.society_id == society.id
                )
            )
            .join(User, User.id == StudentInfo.user_id)
            .join(Role, Role.id == User.role_id)
            .filter(
                Role.name == 'Student',
                or_(
                    StudentInfo.society_id == society.id,
                    StudentInfo.joined_societies.any(Society.id == society.id)
                )
            )
            .group_by(StudentInfo.id)
            .order_by(desc('society_points'), StudentInfo.id.asc())
            .limit(100)
        ).all()

        students = []
        current_student_points = 0
        current_student_rank = None
        for idx, (student, society_points) in enumerate(rows, start=1):
            points_value = int(society_points or 0)
            setattr(student, 'society_points', points_value)
            students.append(student)
            if student_info and student.id == student_info.id:
                current_student_points = points_value
                current_student_rank = idx

        society_boards.append({
            'society': society,
            'students': students,
            'current_student_points': current_student_points,
            'current_student_rank': current_student_rank
        })

    return render_template(
        'student/points_rank.html',
        top_students=total_top_students,
        society_boards=society_boards,
        total_current_student_points=total_current_student_points,
        total_current_student_rank=total_current_student_rank
    )

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
def checkin():
    try:
        # 从请求数据中获取 key 和 activity_id（兼容 JSON 与表单）
        data = request.get_json(silent=True) or request.form or {}
        key = data.get('key') or data.get('checkin_key')
        if isinstance(key, str):
            key = key.strip()
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

        try:
            activity_id = int(activity_id)
        except (TypeError, ValueError):
            logger.warning(f"签到活动ID格式错误: activity_id={activity_id}")
            return jsonify({
                'success': False,
                'message': '活动ID格式错误'
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
                    society_id=student_info.society_id,
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
        
        # 修复历史数据中 created_at 为空导致“时间未知”
        missing_time_count = Message.query.filter(
            or_(
                Message.sender_id == current_user.id,
                Message.receiver_id == current_user.id
            ),
            Message.created_at.is_(None)
        ).count()
        if missing_time_count:
            now = get_localized_now()
            Message.query.filter(
                or_(
                    Message.sender_id == current_user.id,
                    Message.receiver_id == current_user.id
                ),
                Message.created_at.is_(None)
            ).update({Message.created_at: now}, synchronize_session=False)
            db.session.commit()

        # 不使用复杂的连接，保持简单查询
        messages = query.order_by(Message.created_at.desc()).paginate(page=page, per_page=10)
        
        return render_template('student/messages.html', 
                              messages=messages, 
                              filter_type=filter_type,
                              display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in messages page: {e}")
        flash('加载反馈列表时出错', 'danger')
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
@limiter.limit('12 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def create_message():
    try:
        # 创建一个空表单对象用于CSRF保护
        class MessageForm(FlaskForm):
            target_type = SelectField('接收对象', choices=[('super', '总管理员'), ('society', '指定社团管理员')], default='super')
            target_society_id = SelectField('目标社团', choices=[], coerce=int, validators=[Optional()])
            subject = StringField('主题', validators=[DataRequired(message='主题不能为空'), Length(max=120, message='主题最多120字')])
            content = TextAreaField('内容', validators=[DataRequired(message='内容不能为空'), Length(max=5000, message='内容最多5000字')])
            submit = SubmitField('提交反馈')
        
        form = MessageForm()
        societies = db.session.execute(db.select(Society).filter_by(is_active=True).order_by(Society.name)).scalars().all()
        form.target_society_id.choices = [(0, '请选择社团')] + [(s.id, s.name) for s in societies]
        
        if request.method == 'POST' and form.validate_on_submit():
            subject = sanitize_plain_text(form.subject.data, max_length=120)
            content = sanitize_plain_text(form.content.data, allow_multiline=True, max_length=5000)
            target_type = (form.target_type.data or 'super').strip()
            target_society_id = form.target_society_id.data if form.target_society_id.data and form.target_society_id.data > 0 else None
            if not subject or not content:
                flash('主题和内容不能为空（不支持HTML脚本内容）', 'warning')
                return render_template('student/message_form.html', title='提交问题反馈', form=form)
            if target_type == 'society' and not target_society_id:
                flash('请选择要发送的社团', 'warning')
                return render_template('student/message_form.html', title='提交问题反馈', form=form)
            
            admin_role = db.session.query(Role).filter_by(name='Admin').first()
            if not admin_role:
                flash('无法找到管理员，请联系系统管理员', 'danger')
                return redirect(url_for('student.messages'))

            admin_query = db.select(User).filter_by(role_id=admin_role.id)
            if target_type == 'society' and target_society_id:
                admin_query = admin_query.filter(User.managed_society_id == target_society_id, User.is_super_admin == False)
            else:
                admin_query = admin_query.filter(User.is_super_admin == True)

            admin_user = db.session.execute(admin_query.order_by(User.id.asc())).scalar_one_or_none()
            if not admin_user:
                flash('无法找到管理员，请联系系统管理员', 'danger')
                return redirect(url_for('student.messages'))
            
            # 创建消息
            message = Message(
                sender_id=current_user.id,
                receiver_id=admin_user.id,
                subject=subject,
                content=content,
                created_at=get_localized_now(),
                target_society_id=target_society_id
            )
            
            db.session.add(message)
            db.session.commit()
            
            log_action('send_message', f'提交问题反馈给管理员: {subject}')
            flash('反馈提交成功', 'success')
            return redirect(url_for('student.messages'))
        
        return render_template('student/message_form.html', title='提交问题反馈', form=form)
    except Exception as e:
        logger.error(f"Error in create_message: {e}")
        flash('提交反馈时出错', 'danger')
        return redirect(url_for('student.messages'))

@student_bp.route('/messages/mark_all_read', methods=['POST'])
@student_required
def mark_all_messages_read():
    try:
        updated = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).update({Message.is_read: True}, synchronize_session=False)
        db.session.commit()
        flash(f'已标记 {updated} 条未读消息', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in mark_all_messages_read: {e}")
        flash('一键已读失败，请稍后重试', 'danger')
    return redirect(url_for('student.messages', filter=request.args.get('filter', 'all')))

@student_bp.route('/messages/delete_read', methods=['POST'])
@student_required
def delete_read_messages():
    try:
        deleted = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == True
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(f'已删除 {deleted} 条已读消息', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_read_messages: {e}")
        flash('删除已读消息失败，请稍后重试', 'danger')
    return redirect(url_for('student.messages', filter=request.args.get('filter', 'all')))

@student_bp.route('/message/<int:id>/delete', methods=['POST'])
@student_required
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
        _ensure_activity_start_reminders(current_user.id)
        page = request.args.get('page', 1, type=int)
        
        # 获取当前时间，确保带有时区信息
        now = ensure_timezone_aware(datetime.now())
        
        deleted_notification_ids_subq = db.session.query(NotificationRead.notification_id).filter(
            NotificationRead.user_id == current_user.id,
            NotificationRead.is_deleted.is_(True)
        )

        # 获取有效的通知（未过期或无过期日期），并排除当前用户已删除通知
        notifications = Notification.query.filter(
            or_(
                Notification.is_public == True,
                and_(Notification.is_public == False, Notification.created_by == current_user.id)
            ),
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            ),
            Notification.title.isnot(None),
            Notification.content.isnot(None),
            ~Notification.id.in_(deleted_notification_ids_subq)
        ).order_by(Notification.is_important.desc(), Notification.created_at.desc()).paginate(page=page, per_page=10)
        
        # 获取当前用户已读通知的ID列表
        read_notification_ids = db.session.query(NotificationRead.notification_id).filter(
            NotificationRead.user_id == current_user.id,
            or_(NotificationRead.is_deleted == False, NotificationRead.is_deleted.is_(None))
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
        now = ensure_timezone_aware(datetime.now())
        deleted_read = db.session.execute(
            db.select(NotificationRead).filter(
                NotificationRead.notification_id == id,
                NotificationRead.user_id == current_user.id,
                NotificationRead.is_deleted.is_(True)
            )
        ).scalar_one_or_none()

        if deleted_read:
            flash('该通知已删除，无法查看详情', 'warning')
            return redirect(url_for('student.notifications'))

        notification = Notification.query.filter(
            Notification.id == id,
            or_(
                Notification.is_public == True,
                and_(Notification.is_public == False, Notification.created_by == current_user.id)
            ),
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            )
        ).first_or_404()
        
        # 标记为已读
        read_record = db.session.execute(
            db.select(NotificationRead)
            .filter(
                NotificationRead.notification_id == id,
                NotificationRead.user_id == current_user.id
            )
            .order_by(NotificationRead.id.desc())
        ).scalars().first()
        
        if not read_record:
            read_record = NotificationRead(
                notification_id=id,
                user_id=current_user.id,
                read_at=get_localized_now(),
                is_deleted=False
            )
            db.session.add(read_record)
        else:
            if not read_record.read_at:
                read_record.read_at = get_localized_now()

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
        now = ensure_timezone_aware(datetime.now())
        notification = Notification.query.filter(
            Notification.id == id,
            or_(
                Notification.is_public == True,
                and_(Notification.is_public == False, Notification.created_by == current_user.id)
            ),
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            )
        ).first_or_404()
        
        # 检查是否已经标记为已读
        read_record = db.session.execute(
            db.select(NotificationRead)
            .filter(
                NotificationRead.notification_id == id,
                NotificationRead.user_id == current_user.id
            )
            .order_by(NotificationRead.id.desc())
        ).scalars().first()

        if read_record and read_record.is_deleted:
            return jsonify({'success': False, 'deleted': True, 'message': '通知已删除，无法标记已读'}), 410
        
        if not read_record:
            read_record = NotificationRead(
                notification_id=id,
                user_id=current_user.id,
                read_at=get_localized_now(),
                is_deleted=False
            )
            db.session.add(read_record)
        else:
            if not read_record.read_at:
                read_record.read_at = get_localized_now()

        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error in mark_notification_read: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@student_bp.route('/notifications/mark_all_read', methods=['POST'])
@student_required
def mark_all_notifications_read():
    try:
        now = ensure_timezone_aware(datetime.now())
        deleted_notification_ids_subq = db.session.query(NotificationRead.notification_id).filter(
            NotificationRead.user_id == current_user.id,
            NotificationRead.is_deleted.is_(True)
        )
        accessible_notification_ids = db.session.query(Notification.id).filter(
            or_(
                Notification.is_public == True,
                and_(Notification.is_public == False, Notification.created_by == current_user.id)
            ),
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            ),
            Notification.title.isnot(None),
            Notification.content.isnot(None),
            ~Notification.id.in_(deleted_notification_ids_subq)
        ).all()
        accessible_notification_ids = [row[0] for row in accessible_notification_ids]

        if not accessible_notification_ids:
            flash('当前没有可标记的通知', 'info')
            return redirect(url_for('student.notifications', page=request.args.get('page', 1, type=int)))

        existing_reads = db.session.query(NotificationRead).filter(
            NotificationRead.user_id == current_user.id,
            NotificationRead.notification_id.in_(accessible_notification_ids),
            or_(NotificationRead.is_deleted == False, NotificationRead.is_deleted.is_(None))
        ).all()
        existing_map = {r.notification_id: r for r in existing_reads}

        updated = 0
        for nid in accessible_notification_ids:
            record = existing_map.get(nid)
            if record:
                changed = False
                if not record.read_at:
                    record.read_at = get_localized_now()
                    changed = True
                if changed:
                    updated += 1
            else:
                db.session.add(NotificationRead(
                    user_id=current_user.id,
                    notification_id=nid,
                    read_at=get_localized_now(),
                    is_deleted=False
                ))
                updated += 1

        db.session.commit()
        flash(f'已标记 {updated} 条通知为已读', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in mark_all_notifications_read: {e}")
        flash('一键已读通知失败，请稍后重试', 'danger')
    return redirect(url_for('student.notifications', page=request.args.get('page', 1, type=int)))


@student_bp.route('/notifications/delete_read', methods=['POST'])
@student_required
def delete_read_notifications():
    try:
        now = ensure_timezone_aware(datetime.now())
        accessible_notification_ids = db.session.query(Notification.id).filter(
            or_(
                Notification.is_public == True,
                and_(Notification.is_public == False, Notification.created_by == current_user.id)
            ),
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            ),
            Notification.title.isnot(None),
            Notification.content.isnot(None)
        ).all()
        accessible_notification_ids = [row[0] for row in accessible_notification_ids]

        if not accessible_notification_ids:
            flash('当前没有可删除的通知', 'info')
            return redirect(url_for('student.notifications', page=request.args.get('page', 1, type=int)))

        updated = db.session.query(NotificationRead).filter(
            NotificationRead.user_id == current_user.id,
            NotificationRead.notification_id.in_(accessible_notification_ids),
            or_(NotificationRead.is_deleted == False, NotificationRead.is_deleted.is_(None)),
            NotificationRead.read_at.isnot(None)
        ).update({NotificationRead.is_deleted: True}, synchronize_session=False)

        db.session.commit()
        flash(f'已删除 {updated} 条已读通知', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_read_notifications: {e}")
        flash('删除已读通知失败，请稍后重试', 'danger')
    return redirect(url_for('student.notifications', page=request.args.get('page', 1, type=int)))

@student_bp.route('/api/notifications/unread')
@student_required
def get_unread_notifications():
    try:
        _ensure_activity_start_reminders(current_user.id)
        # 获取当前时间，确保带有时区信息
        now = ensure_timezone_aware(datetime.now())
        
        # 获取未读通知（公开通知，包含重要与普通）
        unread_notifications = Notification.query.filter(
            or_(
                Notification.is_public == True,
                and_(Notification.is_public == False, Notification.created_by == current_user.id)
            ),
            or_(
                Notification.expiry_date == None,
                Notification.expiry_date >= now
            ),
            Notification.title.isnot(None),
            Notification.content.isnot(None),
            ~Notification.id.in_(
                db.session.query(NotificationRead.notification_id).filter(
                    NotificationRead.user_id == current_user.id
                )
            )
        ).order_by(Notification.is_important.desc(), Notification.created_at.desc()).limit(20).all()
        
        # 格式化通知数据
        notifications_data = []
        for notification in unread_notifications:
            notifications_data.append({
                'id': notification.id,
                'title': notification.title,
                'content': notification.content,
                'is_important': bool(notification.is_important),
                'created_at': display_datetime(notification.created_at, None, '%Y-%m-%d %H:%M') if notification.created_at else ''
            })
        
        response = jsonify({
            'success': True,
            'notifications': notifications_data
        })
        # 显式禁止浏览器与中间层缓存，避免跨页面切换读取旧通知状态
        response.headers['Cache-Control'] = 'private, no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['CDN-Cache-Control'] = 'no-store'
        response.headers['Surrogate-Control'] = 'no-store'
        return response
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
