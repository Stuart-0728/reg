from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort, send_from_directory, g, session, jsonify, make_response
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import logging
from sqlalchemy import func, desc, text, and_, or_, case
from sqlalchemy.orm import joinedload
from src import db
from src.models import Activity, Registration, User, Tag, Notification, Announcement, Role
from src.utils.time_helpers import get_localized_now, ensure_timezone_aware, safe_less_than, safe_greater_than, display_datetime, get_activity_status
import time
import traceback
import pytz
from flask_wtf import FlaskForm
import os
from src.utils import get_compatible_paginate

logger = logging.getLogger(__name__)

main_bp = Blueprint('main', __name__)

# 测试加载动画路由
@main_bp.route('/test-loading')
def test_loading():
    """测试加载动画页面"""
    return render_template('test_loading.html')

@main_bp.route('/demo/loading')
def demo_loading():
    """加载动画演示页面"""
    return render_template('demo_loading.html')

@main_bp.route('/')
def index():
    try:
        # 检查是否存在管理员账户，如果没有则重定向到设置页面
        admin_role = db.session.execute(db.select(Role).filter_by(name='Admin')).scalar_one_or_none()
        if admin_role:
            admin_exists = db.session.execute(db.select(User).filter_by(role_id=admin_role.id)).scalar_one_or_none()
            if not admin_exists:
                return redirect(url_for('auth.setup_admin'))
        else:
            return redirect(url_for('auth.setup_admin'))
        
        # 获取当前北京时间
        now = get_localized_now()
        logger.info(f"当前北京时间: {now}")
        
        # 获取静态文件目录
        static_folder = current_app.static_folder
        logger.info(f"静态文件目录: {static_folder}")
        
        # 获取公共通知
        try:
            public_notifications = Notification.query.filter(
                Notification.is_public == True,
                or_(
                    Notification.expiry_date == None,
                    Notification.expiry_date > now
                )
            ).order_by(Notification.is_important.desc(), Notification.created_at.desc()).limit(3).all()
            logger.info(f"获取到{len(public_notifications)}条公共通知")
        except Exception as e:
            logger.error(f"获取公共通知出错: {e}")
            public_notifications = []
        
        # 获取特色活动
        try:
            featured_activities = Activity.query.filter(
                Activity.is_featured == True,
                Activity.status == 'active'
            ).order_by(Activity.created_at.desc()).limit(3).all()
        except Exception as e:
            logger.error(f"获取特色活动出错: {e}")
            featured_activities = []
        
        # 记录特色活动信息
        for i, activity in enumerate(featured_activities, 1):
            logger.info(f"特色活动 {i}: ID={activity.id}, 标题={activity.title}, 海报={activity.poster_image}")
            
            # 检查海报文件是否存在
            if activity.poster_image:
                poster_path = os.path.join(static_folder, 'uploads', 'posters', activity.poster_image)
                if os.path.exists(poster_path):
                    logger.info(f"  海报文件存在: {poster_path}")
                else:
                    logger.info(f"  海报文件不存在: {poster_path}")
                    
                    # 尝试查找匹配的海报文件
                    if static_folder:  # 确保static_folder不为None
                        poster_dir = os.path.join(static_folder, 'uploads', 'posters')
                        if os.path.exists(poster_dir):
                            matching_files = [f for f in os.listdir(poster_dir) if f.startswith(f"activity_{activity.id}_")]
                            if matching_files:
                                logger.info(f"  找到匹配的海报文件: {matching_files[0]}")
                                activity.poster_image = matching_files[0]
                    
                    # 如果仍然没有找到海报，设置默认图片
                    poster_path = os.path.join(static_folder, 'uploads', 'posters', activity.poster_image) if static_folder and activity.poster_image else ""
                    if not os.path.exists(poster_path):
                        logger.info(f"设置活动详情页备用风景图: landscape.jpg")
        
        # 获取最新活动
        try:
            latest_activities = Activity.query.filter_by(
                status='active'
            ).order_by(Activity.created_at.desc()).limit(6).all()
        except Exception as e:
            logger.error(f"获取最新活动出错: {e}")
            latest_activities = []
            
        # 获取即将开始的活动
        try:
            upcoming_activities = Activity.query.filter(
                Activity.status == 'active',
                Activity.start_time > now
            ).order_by(Activity.start_time.asc()).limit(3).all()
        except Exception as e:
            logger.error(f"获取即将开始的活动出错: {e}")
            upcoming_activities = []
            
        # 获取热门活动（按报名人数排序）
        try:
            # 使用子查询计算每个活动的报名人数
            reg_count_subq = db.session.query(
                Registration.activity_id,
                func.count(Registration.id).label('reg_count')
            ).filter(
                Registration.status.in_(['registered', 'attended'])
            ).group_by(Registration.activity_id).subquery()
        
            # 查询活动并按报名人数排序
            popular_activities = db.session.query(Activity).join(
                reg_count_subq,
                Activity.id == reg_count_subq.c.activity_id,
                isouter=True
            ).filter(
                Activity.status == 'active'
            ).order_by(
                reg_count_subq.c.reg_count.desc().nullslast()
            ).limit(3).all()
        except Exception as e:
            logger.error(f"获取热门活动出错: {e}")
            popular_activities = []
        
        # 检查活动是否有二进制海报数据
        for activity in featured_activities + latest_activities:
            if hasattr(activity, 'poster_data') and activity.poster_data:
                logger.info(f"活动ID={activity.id}在数据库中有二进制海报数据，大小: {len(activity.poster_data)} 字节")
        
        # 渲染模板
        return render_template('main/index.html',
                            featured_activities=featured_activities,
                              latest_activities=latest_activities,
                            upcoming_activities=upcoming_activities,
                            popular_activities=popular_activities,
                            public_notifications=public_notifications,
                              now=now,
                            display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in index: {e}")
        # 在出错时返回一个简化的页面
        return render_template('main/index.html', 
                              featured_activities=[],
                              latest_activities=[],
                               upcoming_activities=[],
                               popular_activities=[],
                              public_notifications=[],
                              now=datetime.now(pytz.timezone('Asia/Shanghai')),
                              display_datetime=display_datetime)

# 辅助函数：处理活动海报
def process_activity_poster(activity, static_folder):
    """处理活动海报，确保使用最新的海报文件
    
    Args:
        activity: 活动对象
        static_folder: 静态文件目录
    """
    try:
        # 检查是否有海报
        if activity.poster_image is None or str(activity.poster_image).strip() == '':
            logger.info(f"活动ID={activity.id}没有海报图片，设置默认图片")
            setattr(activity, 'poster_image', "landscape.jpg")
            return
            
        # 检查数据库中是否有二进制海报数据
        if hasattr(activity, 'poster_data') and activity.poster_data:
            logger.info(f"活动ID={activity.id}在数据库中有二进制海报数据，大小: {len(activity.poster_data)} 字节")
            # 如果有二进制数据，优先使用数据库中的图片
            # 确保poster_image字段与文件名一致
            return
            
        # 检查文件是否存在
        if static_folder:
            poster_dir = os.path.join(static_folder, 'uploads', 'posters')
            logger.info(f"检查海报目录: {poster_dir}")
            
            if os.path.exists(poster_dir):
                # 查找以活动ID开头的任何海报文件
                try:
                    matching_files = [f for f in os.listdir(poster_dir) if f.startswith(f"activity_{activity.id}_")]
                    logger.info(f"找到匹配活动ID={activity.id}的海报文件: {matching_files}")
                    
                    if matching_files:
                        # 使用最新的匹配文件 - 按时间戳排序
                        matching_files.sort(reverse=True)  # 按文件名降序排序，通常最新的时间戳在最前面
                        new_poster = matching_files[0]
                        logger.info(f"选择最新的海报文件: {new_poster}")
                        
                        # 检查是否需要更新活动的海报文件名
                        if new_poster != activity.poster_image:
                            logger.info(f"更新活动ID={activity.id}的海报: {activity.poster_image} -> {new_poster}")
                            setattr(activity, 'poster_image', new_poster)
                        
                        poster_path = os.path.join(poster_dir, new_poster)
                        if os.path.exists(poster_path):
                            logger.info(f"海报文件存在: {poster_path}")
                            # 尝试读取文件内容并更新数据库中的二进制数据
                            try:
                                if hasattr(activity, 'poster_data') and not activity.poster_data:
                                    with open(poster_path, 'rb') as f:
                                        binary_data = f.read()
                                        setattr(activity, 'poster_data', binary_data)
                                        logger.info(f"已从文件读取海报数据并更新到数据库，大小: {len(binary_data)} 字节")
                            except Exception as e:
                                logger.warning(f"读取海报文件失败: {e}")
                            return
                except Exception as e:
                    logger.error(f"处理匹配海报文件时出错: {e}")
                
                # 如果没有找到匹配的文件或文件不存在，检查指定的海报是否存在
                if activity.poster_image:
                    poster_path = os.path.join(poster_dir, str(activity.poster_image))
                    if os.path.exists(poster_path):
                        logger.info(f"使用指定海报文件: {activity.poster_image}")
                        return
                    else:
                        logger.warning(f"海报文件不存在: {poster_path}")
                        setattr(activity, 'poster_image', "landscape.jpg")
                        logger.info(f"设置活动详情页备用风景图: landscape.jpg")
                else:
                    setattr(activity, 'poster_image', "landscape.jpg")
                    logger.info(f"设置活动详情页备用风景图: landscape.jpg")
            else:
                logger.warning(f"海报目录不存在: {poster_dir}")
                setattr(activity, 'poster_image', "landscape.jpg")
                logger.info(f"海报目录不存在，设置备用风景图: landscape.jpg")
        else:
            logger.warning("静态文件目录未设置")
            setattr(activity, 'poster_image', "landscape.jpg")
            logger.info("静态文件目录未设置，使用备用风景图")
    except Exception as e:
        logger.error(f"处理活动海报出错: {e}")
        setattr(activity, 'poster_image', "landscape.jpg")
        logger.info(f"处理出错，设置备用风景图: landscape.jpg")

@main_bp.route('/activities')
def activities():
    try:
        # 延迟导入，避免循环导入问题
        from src.models import Activity, Registration
        from src.utils.time_helpers import get_localized_now, safe_less_than, safe_greater_than, safe_compare, display_datetime
        from src import db
        
        # 获取当前北京时间
        now = get_localized_now()
        
        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        search_query = request.args.get('search', '')
        status = request.args.get('status', 'active')
        
        # 基本查询
        query = db.select(Activity)
        
        # 搜索功能 - 只有当搜索查询不为空时才过滤
        if search_query:
            query = query.filter(
                or_(
                    Activity.title.ilike(f'%{search_query}%'),
                    Activity.description.ilike(f'%{search_query}%'),
                    Activity.location.ilike(f'%{search_query}%')
                )
            )
        
        # 根据状态筛选 - 使用北京时间进行状态判定
        from src.utils.time_helpers import get_localized_now
        now = get_localized_now()
        
        if status == 'active':
            # 活动状态为'active'且未结束
            query = query.filter(Activity.status == 'active')
            query = query.filter(Activity.end_time > now)
        elif status == 'past':
            # 已结束的活动
            query = query.filter(
                or_(
                    Activity.status == 'completed',
                    and_(Activity.status == 'active', Activity.end_time <= now)
                )
            )
        
        # 排序
        query = query.order_by(Activity.created_at.desc())
        
        # 分页
        try:
            # 分页
            activities_list = get_compatible_paginate(db, query, page=page, per_page=9, error_out=False)
            
            # 获取用户已报名的活动ID列表
            registered_activity_ids = []
            if current_user.is_authenticated:
                reg_stmt = db.select(Registration.activity_id).filter(
                    Registration.user_id == current_user.id,
                        Registration.status.in_(['registered', 'attended'])
                )
                registered = db.session.execute(reg_stmt).all()
                registered_activity_ids = [r[0] for r in registered]
            
            return render_template('main/search.html',
                                   activities=activities_list,
                                   search_query=search_query,
                                   current_status=status,
                                   registered_activity_ids=registered_activity_ids,
                                    display_datetime=display_datetime)
        except Exception as e:
            logger.error(f"分页或获取已报名活动出错: {e}")
            # 尝试不使用分页获取活动列表
            activities_query = db.session.execute(query).scalars().all()
            return render_template('main/search.html', 
                                activities=activities_query,
                                search_query=search_query,
                                current_status=status,
                                registered_activity_ids=[],
                                display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in activities page: {e}")
        flash('加载活动列表时出错', 'danger')
        # 返回一个空的活动列表页面而不是重定向
        return render_template('main/search.html', 
                             activities=[],
                             search_query=search_query if 'search_query' in locals() else '',
                             current_status=status if 'status' in locals() else 'active',
                             registered_activity_ids=[],
                             display_datetime=display_datetime)

@main_bp.route('/activity/<int:activity_id>')
def activity_detail(activity_id):
    """活动详情页"""
    try:
        # 延迟导入，避免循环导入问题
        from src import db
        from src.models import Activity, Registration, User, Tag
        from src.utils.time_helpers import display_datetime, get_localized_now, safe_less_than, safe_greater_than, safe_compare, ensure_timezone_aware
        # 导入FlaskForm创建CSRF令牌
        from flask_wtf import FlaskForm
        
        activity = db.get_or_404(Activity, activity_id)
        
        # 检查海报文件是否存在，如果不存在则设置备用海报
        try:
            static_folder = current_app.static_folder
            process_activity_poster(activity, static_folder)
            poster_image = str(activity.poster_image) if activity.poster_image else "landscape.jpg"
            if static_folder:
                logger.info(f"检查活动海报路径: {os.path.join(static_folder, 'uploads', 'posters', poster_image)}")
        except Exception as e:
            logger.error(f"处理活动海报时出错: {e}")
            setattr(activity, 'poster_image', "landscape.jpg")
            logger.info(f"设置活动详情页备用风景图: landscape.jpg")
        
        # 创建空表单对象用于CSRF保护
        form = FlaskForm()
        
        # 获取报名人数
        reg_stmt = db.select(func.count()).select_from(Registration).filter_by(activity_id=activity_id)
        registration_count = db.session.execute(reg_stmt).scalar()
        logger.info(f"活动ID={activity_id} 的报名人数: {registration_count}")
        
        # 检查当前用户是否已报名
        is_registered = False
        registration = None
        if current_user.is_authenticated:
            reg_stmt = db.select(Registration).filter_by(
                user_id=current_user.id,
                activity_id=activity_id
            )
            registration = db.session.execute(reg_stmt).scalar_one_or_none()
            
            # 只有当注册状态为'registered'或'attended'时才视为已报名
            is_registered = registration is not None and registration.status in ['registered', 'attended']
        
        # 获取当前时间（带时区的UTC时间）
        now = get_localized_now()
        logger.info(f"当前UTC时间: {now}, 活动截止时间: {activity.registration_deadline}, 活动开始时间: {activity.start_time}")
        
        # 判断是否可以报名 - 使用安全比较函数
        # 确保所有时间都有时区信息
        deadline_aware = ensure_timezone_aware(activity.registration_deadline)
        start_time_aware = ensure_timezone_aware(activity.start_time)
        
        can_register = (
            not is_registered and 
            activity.status == 'active' and
            safe_greater_than(deadline_aware, now) and
            (activity.max_participants == 0 or registration_count < activity.max_participants)
        )
        
        # 判断是否可以取消报名 - 使用安全比较函数
        can_cancel = (
            is_registered and
            safe_greater_than(start_time_aware, now)
        )
        
        # 判断当前用户是否为学生
        is_student = current_user.is_authenticated and current_user.is_student
        
        # 获取天气数据
        weather_data = None
        try:
            from src.utils.weather_api import get_activity_weather
            if activity.start_time:
                weather_data = get_activity_weather(activity.start_time)
                logger.info(f"获取活动天气数据成功: {weather_data.get('description', 'N/A') if weather_data else 'None'}")
        except Exception as e:
            logger.warning(f"获取天气数据失败: {e}")
            weather_data = None
        
        return render_template('main/activity_detail.html', 
                              activity=activity,
                              registration_count=registration_count,
                              is_registered=is_registered,
                              registration=registration,
                              can_register=can_register,
                              can_cancel=can_cancel,
                              is_student=is_student,
                              display_datetime=display_datetime,
                              form=form,
                              now=now,
                              safe_less_than=safe_less_than,
                              safe_greater_than=safe_greater_than,
                              safe_compare=safe_compare,
                              weather_data=weather_data)
    except Exception as e:
        logger.error(f"Error in activity_detail: {str(e)}")
        flash('加载活动详情时发生错误，请稍后再试', 'danger')
        return redirect(url_for('main.index'))

@main_bp.route('/about')
def about():
    """关于页面"""
    return render_template('main/about.html')

@main_bp.route('/contact')
def contact():
    try:
        return render_template('main/contact.html')
    except Exception as e:
        logger.error(f"Error in contact: {e}")
        flash('加载联系页面时发生错误', 'danger')
        return redirect(url_for('main.index'))

@main_bp.route('/privacy')
def privacy():
    try:
        return render_template('main/privacy.html')
    except Exception as e:
        logger.error(f"Error in privacy: {e}")
        flash('加载隐私政策页面时发生错误', 'danger')
        return redirect(url_for('main.index'))

@main_bp.route('/terms')
def terms():
    try:
        return render_template('main/terms.html')
    except Exception as e:
        logger.error(f"Error in terms: {e}")
        flash('加载使用条款页面时发生错误', 'danger')
        return redirect(url_for('main.index'))

@main_bp.route('/search')
def search():
    try:
        from src import db
        from src.models import Activity, Tag
        
        query = request.args.get('q', '')
        if not query:
            return render_template('main/search.html', activities=[], query='')
        
        # 使用SQLAlchemy 2.0语法进行搜索
        search_stmt = db.select(Activity).filter(
            or_(
                Activity.title.ilike(f'%{query}%'),
                Activity.description.ilike(f'%{query}%'),
                Activity.location.ilike(f'%{query}%')
            )
        ).order_by(Activity.created_at.desc())
        
        activities = db.session.execute(search_stmt).scalars().all()
        
        return render_template('main/search.html', activities=activities, query=query)
    except Exception as e:
        logger.error(f"Error in search: {e}")
        flash('搜索时发生错误', 'danger')
        return render_template('main/search.html', activities=[], query='')

@main_bp.route('/uploads/<path:filename>')
def uploaded_file(filename):
    try:
        return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
    except Exception as e:
        logger.error(f"Error accessing uploaded file {filename}: {e}")
        abort(404)

@main_bp.route('/utils/ai_chat/clear_history', methods=['POST'])
@login_required
def clear_ai_chat_history():
    try:
        # 支持JSON和表单数据
        if request.is_json:
            data = request.get_json()
            session_id = data.get('session_id')
        else:
            session_id = request.form.get('session_id')

        logger.info(f"清除AI聊天历史记录请求: session_id={session_id}, user_id={current_user.id}")
        
        if not session_id:
            logger.warning("清除AI聊天历史记录失败: 缺少session_id")
            return jsonify({'success': False, 'message': '缺少 session_id'}), 400

        from src.models import AIChatHistory
        deleted = AIChatHistory.query.filter_by(session_id=session_id, user_id=current_user.id).delete()
        db.session.commit()
        
        logger.info(f"已清除AI聊天历史记录: {deleted} 条记录")
        return jsonify({'success': True, 'message': f'聊天记录已清除: {deleted} 条记录'})

    except Exception as e:
        logger.error(f"清除聊天记录时出错: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'message': f'服务器错误: {str(e)}'}), 500

@main_bp.route('/poster/<int:activity_id>')
def poster_image(activity_id):
    """直接从数据库获取海报图片"""
    try:
        from src.models import Activity
        
        # 获取活动信息
        activity = db.get_or_404(Activity, activity_id)
        
        # 检查活动是否有图片数据
        if not activity.poster_data:
            # 如果没有图片数据，重定向到默认图片
            return redirect(url_for('static', filename='img/landscape.jpg'))
        
        # 获取MIME类型，默认为image/png
        mime_type = activity.poster_mimetype or 'image/png'
        
        # 返回图片数据
        response = make_response(activity.poster_data)
        response.headers.set('Content-Type', mime_type)
        response.headers.set('Cache-Control', 'public, max-age=3600')  # 缓存1小时
        return response
    except Exception as e:
        logger.error(f"获取活动海报时出错: {e}")
        # 重定向到默认图片
        return redirect(url_for('static', filename='img/landscape.jpg'))

@main_bp.route('/tencent5668923388243771053.txt')
def tencent_verification():
    """处理腾讯站长验证文件请求"""
    verification_content = "3552953637355933699"
    return verification_content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
