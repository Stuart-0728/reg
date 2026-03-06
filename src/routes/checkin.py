from flask import Blueprint, request, jsonify, flash, redirect, url_for, render_template, current_app, abort
from flask_login import login_required, current_user
from src.models import db, Activity, ActivityCheckin, Registration, StudentInfo, PointsHistory, User
from datetime import datetime, timezone, timedelta
import logging
from src.utils.time_helpers import get_localized_now, localize_time, ensure_timezone_aware, normalize_datetime_for_db
from sqlalchemy import func, select

logger = logging.getLogger(__name__)
checkin_bp = Blueprint('checkin', __name__, url_prefix='/checkin')

# 签到接口
@checkin_bp.route('/<int:activity_id>', methods=['POST'])
@login_required
def checkin(activity_id):
    try:
        activity = db.get_or_404(Activity, activity_id)
        
        # 检查是否已签到
        stmt = db.select(ActivityCheckin).filter_by(activity_id=activity_id, user_id=current_user.id)
        existing_checkin = db.session.execute(stmt).scalar_one_or_none()
        
        if existing_checkin:
            return jsonify({'success': False, 'msg': '已签到'})
            
        # 创建签到记录
        checkin_record = ActivityCheckin(
            activity_id=activity_id,
            user_id=current_user.id,
            checkin_time=datetime.now(timezone.utc)
        )
        db.session.add(checkin_record)
        db.session.commit()
        return jsonify({'success': True, 'msg': '签到成功'})
    except Exception as e:
        logger.error(f"签到失败: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'msg': f'签到失败: {str(e)}'})

# 扫描二维码签到路由
@checkin_bp.route('/scan/<int:activity_id>/<string:checkin_key>')
@login_required
def scan_checkin(activity_id, checkin_key):
    try:
        # 检查活动是否存在
        activity = db.get_or_404(Activity, activity_id)
        
        # 验证签到密钥是否有效
        valid_key = False
        now = get_localized_now()
        
        # 导入安全比较函数
        from src.utils.time_helpers import safe_greater_than_equal
        
        checkin_key_field = getattr(activity, 'checkin_key', None)
        expires_time = getattr(activity, 'checkin_key_expires', None)
        
        # 使用安全的时间比较函数
        if checkin_key_field == checkin_key and expires_time and safe_greater_than_equal(expires_time, now):
            valid_key = True
            
        if not valid_key:
            flash('签到二维码无效或已过期', 'danger')
            return redirect(url_for('student.activities'))
        
        # 检查活动状态
        if activity.status != 'active':
            flash('该活动当前不可签到', 'warning')
            return redirect(url_for('student.activity_detail', id=activity_id))
        
        # 检查是否手动开启了签到
        checkin_enabled = getattr(activity, 'checkin_enabled', False)
        logger.info(f"活动签到状态: 活动ID={activity_id}, 签到已手动开启={checkin_enabled}")
        
        # 如果没有手动开启签到，则验证当前时间是否在活动时间范围内
        if not checkin_enabled:
            # 导入安全比较函数
            from src.utils.time_helpers import safe_less_than, safe_greater_than
            
            # 确保活动时间有时区信息，并且都转换为北京时间进行比较
            start_time = ensure_timezone_aware(activity.start_time) if activity.start_time else now
            end_time = ensure_timezone_aware(activity.end_time) if activity.end_time else now + timedelta(hours=2)
                
            # 添加灵活度：允许活动开始前30分钟和结束后30分钟的签到
            if start_time:
                start_time_buffer = start_time - timedelta(minutes=30)
            else:
                start_time_buffer = now - timedelta(minutes=30)
                
            if end_time:
                end_time_buffer = end_time + timedelta(minutes=30)
            else:
                end_time_buffer = now + timedelta(hours=2, minutes=30)
        
            logger.info(f"签到时间检查: 当前北京时间={now}, 活动开始时间={start_time}, 活动结束时间={end_time}")
            
            # 使用安全的时间比较函数
            if safe_less_than(now, start_time_buffer) or safe_greater_than(now, end_time_buffer):
                flash('不在活动签到时间范围内', 'warning')
                return redirect(url_for('student.activity_detail', id=activity_id))
        else:
            logger.info(f"签到时间检查已忽略: 活动ID={activity_id}，已手动开启签到")
        
        # 检查用户是否已报名该活动
        stmt = db.select(Registration).filter_by(
            user_id=current_user.id,
            activity_id=activity_id
        )
        registration = db.session.execute(stmt).scalar_one_or_none()
        
        if not registration:
            flash('您尚未报名此活动，请先报名', 'warning')
            return redirect(url_for('student.activity_detail', id=activity_id))
        
        # 检查是否已签到
        stmt = db.select(ActivityCheckin).filter_by(
            user_id=current_user.id,
            activity_id=activity_id
        )
        existing_checkin = db.session.execute(stmt).scalar_one_or_none()
        
        if existing_checkin:
            flash('您已经签到过了', 'info')
            return redirect(url_for('student.activity_detail', id=activity_id))
        
        # 创建签到记录
        checkin = ActivityCheckin(
            activity_id=activity_id,
            user_id=current_user.id,
            checkin_time=datetime.now(timezone.utc),
            is_manual=False
        )
        db.session.add(checkin)
        
        # 记录签到时间的日志
        logger.info(f"用户签到: 用户ID={current_user.id}, 活动ID={activity_id}, 签到时间={checkin.checkin_time}")
        
        # 添加积分奖励
        points = activity.points or 10  # 使用活动自定义积分或默认值
        
        stmt = db.select(StudentInfo).filter_by(user_id=current_user.id)
        student_info = db.session.execute(stmt).scalar_one_or_none()
        
        if student_info:
            student_info.points = (student_info.points or 0) + points
            # 记录积分历史
            points_history = PointsHistory(
                user_id=current_user.id,
                activity_id=activity.id,
                points=points,
                reason=f"参与活动：{activity.title}"
            )
            db.session.add(points_history)
        
        db.session.commit()
        flash(f'签到成功！获得 {points} 积分', 'success')
        
        # 重定向到活动详情页
        return redirect(url_for('student.activity_detail', id=activity_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"扫码签到失败: {e}", exc_info=True)
        flash('签到失败，请重试', 'danger')
        return redirect(url_for('student.activities'))

# 签到统计页面
@checkin_bp.route('/statistics/<int:activity_id>', methods=['GET'])
@login_required
def checkin_statistics(activity_id):
    try:
        activity = db.get_or_404(Activity, activity_id)
        
        stmt = db.select(ActivityCheckin).filter_by(activity_id=activity_id)
        checkins = db.session.execute(stmt).scalars().all()
        
        return render_template('admin/checkin_statistics.html', activity=activity, checkins=checkins)
    except Exception as e:
        logger.error(f"加载签到统计失败: {e}")
        flash('加载签到统计失败', 'danger')
        return redirect(url_for('admin.activities'))

@checkin_bp.route('/register/<int:activity_id>', methods=['POST'])
@login_required
def register_activity(activity_id):
    """用户报名活动"""
    try:
        # 获取活动信息
        activity = db.get_or_404(Activity, activity_id)
        
        # 检查活动是否可以报名
        now = datetime.now(timezone.utc)
        if now > activity.registration_deadline:
            flash('该活动已截止报名', 'warning')
            return redirect(url_for('main.activity_detail', activity_id=activity_id))
        
        # 检查活动状态
        if activity.status != 'active':
            flash('该活动不可报名', 'warning')
            return redirect(url_for('main.activity_detail', activity_id=activity_id))
        
        # 检查是否已经报名
        stmt = db.select(Registration).filter_by(
            user_id=current_user.id,
            activity_id=activity_id
        )
        existing_registration = db.session.execute(stmt).scalar_one_or_none()
        
        if existing_registration:
            flash('您已经报名了此活动', 'info')
            return redirect(url_for('main.activity_detail', activity_id=activity_id))
        
        # 检查活动人数限制
        if activity.max_participants > 0:
            count_stmt = db.select(func.count()).select_from(Registration).filter_by(activity_id=activity_id)
            current_count = db.session.execute(count_stmt).scalar()
            
            if current_count >= activity.max_participants:
                flash('该活动报名人数已满', 'warning')
                return redirect(url_for('main.activity_detail', activity_id=activity_id))
        
        # 创建报名记录
        registration = Registration(
            user_id=current_user.id,
            activity_id=activity_id,
            status='registered',
            register_time=datetime.now(timezone.utc)
        )
        
        db.session.add(registration)
        db.session.commit()
        
        flash('报名成功！', 'success')
        return redirect(url_for('main.activity_detail', activity_id=activity_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"报名活动出错: {str(e)}", exc_info=True)
        flash('报名过程中出错，请稍后再试', 'danger')
        return redirect(url_for('main.activity_detail', activity_id=activity_id))

@checkin_bp.route('/unregister/<int:activity_id>', methods=['POST'])
@login_required
def unregister_activity(activity_id):
    """用户取消报名活动"""
    try:
        # 获取活动信息
        activity = db.get_or_404(Activity, activity_id)
        
        # 检查活动是否已开始
        now = datetime.now(timezone.utc)
        if now > activity.start_time:
            flash('活动已开始，无法取消报名', 'warning')
            return redirect(url_for('student.my_activities'))
        
        # 查找报名记录
        stmt = db.select(Registration).filter_by(
            user_id=current_user.id,
            activity_id=activity_id
        )
        registration = db.session.execute(stmt).scalar_one_or_none()
        
        if not registration:
            flash('您未报名此活动', 'info')
            return redirect(url_for('student.my_activities'))
        
        # 删除报名记录
        db.session.delete(registration)
        db.session.commit()
        
        flash('已成功取消报名', 'success')
        return redirect(url_for('student.my_activities'))
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"取消报名出错: {str(e)}")
        flash('取消报名过程中出错，请稍后再试', 'danger')
        return redirect(url_for('student.my_activities'))

@checkin_bp.route('/api/checkin/<int:activity_id>', methods=['POST'])
@login_required
def api_checkin(activity_id):
    """API接口：用户签到"""
    try:
        # 获取活动信息
        activity = db.get_or_404(Activity, activity_id)
        
        # 检查活动状态
        if activity.status != 'active':
            return jsonify({'success': False, 'message': '该活动不可签到'})
        
        # 检查是否已报名
        reg_stmt = db.select(Registration).filter_by(
            user_id=current_user.id,
            activity_id=activity_id
        )
        registration = db.session.execute(reg_stmt).scalar_one_or_none()
        
        if not registration:
            return jsonify({'success': False, 'message': '您未报名此活动，无法签到'})
        
        # 检查是否已签到
        checkin_stmt = db.select(ActivityCheckin).filter_by(
            user_id=current_user.id,
            activity_id=activity_id
        )
        existing_checkin = db.session.execute(checkin_stmt).scalar_one_or_none()
        
        if existing_checkin:
            return jsonify({'success': False, 'message': '您已签到，请勿重复操作'})
        
        # 创建签到记录
        checkin = ActivityCheckin(
            user_id=current_user.id,
            activity_id=activity_id,
            checkin_time=datetime.now(timezone.utc)
        )
        
        # 更新报名状态
        registration.status = 'attended'
        
        # 记录积分
        if activity.points > 0:
            # 查询用户
            user_stmt = db.select(User).filter_by(id=current_user.id)
            user = db.session.execute(user_stmt).scalar_one_or_none()
            
            if user and hasattr(user, 'student_info') and user.student_info:
                # 更新积分
                user.student_info.points += activity.points
                
                # 记录积分历史
                points_history = PointsHistory(
                    user_id=current_user.id,
                    activity_id=activity_id,
                    points=activity.points,
                    reason=f'参加活动：{activity.title}'
                )
                db.session.add(points_history)
        
        db.session.add(checkin)
        db.session.commit()
        
        return jsonify({
            'success': True, 
            'message': f'签到成功！{activity.points > 0 and f"获得{activity.points}积分" or ""}'
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"签到出错: {str(e)}")
        return jsonify({'success': False, 'message': '签到过程中出错，请稍后再试'})
