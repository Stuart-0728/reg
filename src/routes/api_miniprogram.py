from flask import Blueprint, jsonify, request, current_app
from src.utils.time_helpers import display_datetime
from src.models import Activity, User, StudentInfo, Registration
from src import db

api_mp_bp = Blueprint('api_mp', __name__, url_prefix='/api/mp')

@api_mp_bp.route('/login', methods=['POST'])
def mp_login():
    data = request.json or {}
    student_id = data.get('student_id')
    password = data.get('password')

    if not student_id or not password:
        return jsonify({'success': False, 'msg': '请提供账号和密码'})

    # 1. 查找用户
    user = None
    # 尝试按用户名或邮箱匹配 User 表
    user = User.query.filter((User.username == student_id) | (User.email == student_id)).first()
    
    if not user:
        # 尝试按学号或手机号匹配 StudentInfo 表
        student = StudentInfo.query.filter((StudentInfo.student_id == student_id) | (StudentInfo.phone == student_id)).first()
        if student:
            user = User.query.get(student.user_id)

    if not user:
        return jsonify({'success': False, 'msg': '账号不存在或未绑定系统'})
    
    # 2. 验证密码
    if not user.verify_password(password):
        return jsonify({'success': False, 'msg': '账号或密码错误'})
        
    # 3. 检查激活状态 (邮箱验证)
    if not user.active:
        return jsonify({'success': False, 'msg': '账号尚未通过邮箱验证，请先前往邮箱验证'})

    student = user.student_info
    if not student:
        return jsonify({'success': False, 'msg': '账号未绑定学生档案'})

    # 如果传了 openid，就顺便绑定
    openid = data.get('openid')
    if openid and hasattr(User, 'wx_openid'):
        # 解绑其他用这个 openid 的账号（只允许一个微信号绑一个学号）
        old_user = User.query.filter_by(wx_openid=openid).first()
        if old_user:
            old_user.wx_openid = None
        user.wx_openid = openid
        db.session.commit()

    # 3. 统计已参与的活动次数
    from src.models import Registration
    attended_count = Registration.query.filter_by(user_id=user.id, status='attended').count()

    # (可扩展：用 JWT 或者自带的 session_id 返回 token)
    return jsonify({
        'success': True,
        'token': 'token_' + str(user.id),
        'user': {
            'real_name': student.real_name,
            'student_id': student.student_id,
            'points': student.points
        },
        'stats': {
            'attended': attended_count
        }
    })

@api_mp_bp.route('/activities', methods=['GET'])
def get_activities():
    try:
        query = Activity.query.filter_by(status='active')
        society_id = request.args.get('society_id', type=int)
        if society_id:
            query = query.filter_by(society_id=society_id)
            
        activities = query.order_by(Activity.start_time.desc()).all()
        data = []
        for a in activities:
            poster_full_url = a.poster_url
            if poster_full_url and not poster_full_url.startswith('http'):
                poster_full_url = f"{request.host_url.rstrip('/')}{poster_full_url}"
                
            data.append({
                'id': a.id,
                'title': a.title,
                'description': a.description,
                'start_time': display_datetime(a.start_time, '%Y-%m-%d %H:%M') if a.start_time else '待定',
                'poster_url': poster_full_url,
                'type': a.type,
                'organizer': a.society.name if a.society else '智能社团+',
                'current_participants': a.registrations.filter_by(status='registered').count(),
                'points': a.points
            })
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)})

@api_mp_bp.route('/activities/<int:id>', methods=['GET'])
def get_activity_detail(id):
    try:
        a = Activity.query.get_or_404(id)
        poster_full_url = a.poster_url
        if poster_full_url and not poster_full_url.startswith('http'):
            poster_full_url = f"{request.host_url.rstrip('/')}{poster_full_url}"
            
        user_status = 'not_registered'
        token = request.headers.get('Authorization')
        if token and token.startswith('token_'):
            user_id = token.replace('token_', '')
            user = User.query.get(user_id)
            if user:
                from src.models import Registration
                reg = Registration.query.filter_by(user_id=user.id, activity_id=a.id).order_by(Registration.created_at.desc()).first()
                if reg:
                    user_status = reg.status

        data = {
            'id': a.id,
            'title': a.title,
            'description': a.description,
            'start_time': display_datetime(a.start_time, '%Y-%m-%d %H:%M') if a.start_time else '待定',
            'end_time': display_datetime(a.end_time, '%Y-%m-%d %H:%M') if a.end_time else '待定',
            'registration_start_time': display_datetime(getattr(a, 'registration_start_time', None), '%Y-%m-%d %H:%M') if getattr(a, 'registration_start_time', None) else '待定',
            'registration_end_time': display_datetime(getattr(a, 'registration_end_time', None), '%Y-%m-%d %H:%M') if getattr(a, 'registration_end_time', None) else '待定',
            'checkin_enabled': getattr(a, 'checkin_enabled', False),
            'user_status': user_status,
            'location': a.location or '待定',
            'poster_url': poster_full_url,
            'type': a.type,
            'organizer': a.society.name if a.society else '智能社团+',
            'current_participants': a.registrations.filter_by(status='registered').count(),
            'points': a.points,
            'max_participants': a.max_participants
        }
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)})

from functools import wraps
from src.models import Registration, PointsHistory
from datetime import datetime
import pytz

def require_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or not token.startswith('token_'):
            return jsonify({'success': False, 'msg': '无效的凭证，请重新登录', 'need_login': True}), 401
        try:
            user_id = int(token.split('_')[1])
            user = User.query.get(user_id)
            if not user:
                return jsonify({'success': False, 'msg': '用户不存在', 'need_login': True}), 401
            request.mp_user = user
        except:
            return jsonify({'success': False, 'msg': '身份验证解析失败', 'need_login': True}), 401
        return f(*args, **kwargs)
    return decorated

@api_mp_bp.route('/my_activities', methods=['GET'])
@require_token
def my_activities():
    user = request.mp_user
    regs = Registration.query.filter_by(user_id=user.id).order_by(Registration.register_time.desc()).all()
    data = []
    for r in regs:
        a = r.activity
        poster_full_url = a.poster_url
        if poster_full_url and not poster_full_url.startswith('http'):
            poster_full_url = f"{request.host_url.rstrip('/')}{poster_full_url}"
        data.append({
            'activity_id': a.id,
            'title': a.title,
            'poster_url': poster_full_url,
            'start_time': display_datetime(a.start_time, '%Y-%m-%d %H:%M') if a.start_time else '待定',
            'status': r.status, # registered, attended, cancelled
            'activity_status': a.status,
            'type': a.type,
            'organizer': a.society.name if a.society else '智能社团+',
            'current_participants': a.registrations.filter_by(status='registered').count(),
            'points': a.points
        })
    return jsonify({'success': True, 'data': data})

@api_mp_bp.route('/activities/<int:id>/cancel', methods=['POST'])
@require_token
def cancel_activity(id):
    try:
        user = request.mp_user
        reg = Registration.query.filter_by(user_id=user.id, activity_id=id).first()
        if not reg:
            return jsonify({'success': False, 'msg': '并未报名该活动'})
        if reg.status == 'attended':
            return jsonify({'success': False, 'msg': '已签到无法取消'})
        
        reg.status = 'cancelled'
        db.session.commit()
        return jsonify({'success': True, 'msg': '取消报名成功'})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)})

@api_mp_bp.route('/activities/<int:id>/register', methods=['POST'])
@require_token
def register_activity(id):
    user = request.mp_user
    a = Activity.query.get_or_404(id)
    if a.status != 'active':
        return jsonify({'success': False, 'msg': '活动不在报名中'})
        
    existing = Registration.query.filter_by(user_id=user.id, activity_id=id).first()
    if existing:
        if existing.status == 'cancelled':
            if a.max_participants > 0:
                current_count = Registration.query.filter_by(activity_id=id, status='registered').count() + Registration.query.filter_by(activity_id=id, status='attended').count()
                if current_count >= a.max_participants:
                    return jsonify({'success': False, 'msg': '名额已满'})
            existing.status = 'registered'
            db.session.commit()
            return jsonify({'success': True, 'msg': '重新报名成功'})
        return jsonify({'success': False, 'msg': '您已经报名过该活动啦'})

    if a.max_participants > 0:
        current_count = Registration.query.filter_by(activity_id=id, status='registered').count() + Registration.query.filter_by(activity_id=id, status='attended').count()
        if current_count >= a.max_participants:
            return jsonify({'success': False, 'msg': '名额已满'})

    new_reg = Registration(user_id=user.id, activity_id=id)
    db.session.add(new_reg)
    db.session.commit()
    return jsonify({'success': True, 'msg': '报名成功！'})

@api_mp_bp.route('/checkin', methods=['POST'])
@require_token
def mp_checkin():
    user = request.mp_user
    data = request.json or {}
    checkin_payload = data.get('checkin_key')
    if not checkin_payload:
        return jsonify({'success': False, 'msg': '扫码内容无效'})
    
    # 解析二维码内容，兼容完整URL和纯key
    # URL 格式类似于: https://domain.com/checkin/scan/1/abc123def456
    actual_checkin_key = checkin_payload
    if '/checkin/scan/' in checkin_payload:
        parts = checkin_payload.split('/checkin/scan/')
        if len(parts) > 1:
            path_parts = parts[1].split('/')
            if len(path_parts) >= 2:
                actual_checkin_key = path_parts[1]  # 取出第二个部分，即 checkin_key
    
    # actual_checkin_key 对应 Activity
    activity = Activity.query.filter_by(checkin_key=actual_checkin_key).first()
    if not activity:
        return jsonify({'success': False, 'msg': '未找到对应的签到活动'})
    if not activity.checkin_enabled:
        return jsonify({'success': False, 'msg': '该活动目前未开放签到'})
        
    # Check registration
    reg = Registration.query.filter_by(user_id=user.id, activity_id=activity.id).first()
    if not reg:
        return jsonify({'success': False, 'msg': '您还没有报名此活动，请先报名'})
    
    if reg.status == 'attended':
        return jsonify({'success': False, 'msg': '您已经签到过了，无需重复签到'})
        
    # Mark as attended and add points
    reg.status = 'attended'
    reg.check_in_time = datetime.now(pytz.utc)
    
    if user.student_info:
        user.student_info.points += activity.points
        ph = PointsHistory(student_id=user.student_info.id, points=activity.points, reason=f'参加活动: {activity.title}')
        db.session.add(ph)
        
    db.session.commit()
    
    # Attempt to send WeChat subscription message
    if user.wx_openid:
        from src.utils.wechat_api import send_subscribe_message
        from src.utils.time_helpers import display_datetime
        checkin_time = display_datetime(datetime.now(pytz.utc), '%Y-%m-%d %H:%M')
        # 签到提醒: T25ILSqS41_ZhDXZl77iQESliXV9J8na1f5IyARQDbM
        # 字段映射（根据用户截图）：
        # 活动名称 thing1
        # 签到奖励 thing10
        # 签到方式 thing2
        # 签到时间 time16
        # 温馨提醒 thing9
        msg_data = {
            "thing1": {"value": activity.title[:20]},
            "thing10": {"value": f"{activity.points} 积分"},
            "thing2": {"value": "扫码签到"},
            "time16": {"value": checkin_time},
            "thing9": {"value": "积分已发送至账户"}
        }
        # Send async so it doesn't block the response
        try:
            send_subscribe_message(user.wx_openid, 'T25ILSqS41_ZhDXZl77iQESliXV9J8na1f5IyARQDbM', "pages/my_activities/my_activities", msg_data)
        except Exception as e:
            current_app.logger.warning(f"Failed to send template message for checkin: {e}")
            
    return jsonify({'success': True, 'msg': '签到成功！积分已增加'})



import requests

@api_mp_bp.route('/wx_login', methods=['POST'])
def wx_login():
    data = request.json or {}
    code = data.get('code')
    if not code:
        return jsonify({'success': False, 'msg': '缺少 code'})
    
    appid = current_app.config.get('WX_APPID', 'wx1234567890abcdef')
    secret = current_app.config.get('WX_APPSECRET', 'your_app_secret')
    
    if appid == 'wx1234567890abcdef':
        return jsonify({'success': False, 'msg': '后端未配置微信 APPID_SECRET_XXX，请先使用学号登录'})

    url = f"https://api.weixin.qq.com/sns/jscode2session?appid={appid}&secret={secret}&js_code={code}&grant_type=authorization_code"
    try:
        resp = requests.get(url, timeout=5).json()
    except Exception as e:
        return jsonify({'success': False, 'msg': f'微信接口请求超时: {str(e)}'})

    openid = resp.get('openid')
    if not openid:
        return jsonify({'success': False, 'msg': f"获取 openid 失败，微信返回: {resp.get('errmsg', '未知错误')}"})

    # 查找是否有用户已经绑定了这个 openid
    user = User.query.filter_by(wx_openid=openid).first()
    if user:
        student = user.student_info
        from src.models import Registration
        attended_count = Registration.query.filter_by(user_id=user.id, status='attended').count()
        return jsonify({
            'success': True,
            'token': 'token_' + str(user.id),
            'user': {
                'real_name': student.real_name if student else user.username,
                'student_id': student.student_id if student else '',
                'points': student.points if student else 0
            },
            'stats': {
                'attended': attended_count
            }
        })
    else:
        # 没有绑定过，返回需要绑定
        return jsonify({
            'success': True, 
            'need_bind': True, 
            'openid': openid,
            'msg': '首次登录需要绑定/注册账号'
        })


@api_mp_bp.route('/notifications', methods=['GET'])
@require_token
def mp_notifications():
    from src.models import Notification, NotificationRead
    user = request.mp_user
    # 查找所有公开或直接给该用户的通知
    notifications = Notification.query.filter_by(is_public=True).order_by(Notification.created_at.desc()).limit(20).all()
    # 也可以过滤掉已过期的
    
    # 找到所有的已读记录
    # (考虑到性能可以用in_，不过这里记录不多)
    reads = NotificationRead.query.filter_by(user_id=user.id).all()
    read_ids = [r.notification_id for r in reads if not r.is_deleted] if hasattr(NotificationRead, 'is_deleted') else [r.notification_id for r in reads]
    
    data = []
    for n in notifications:
        data.append({
            'id': n.id,
            'title': n.title,
            'content': n.content,
            'summary': n.content[:50] + '...' if len(n.content) > 50 else n.content,
            'time': display_datetime(n.created_at, '%Y-%m-%d %H:%M') if n.created_at else '未知时间',
            'is_read': n.id in read_ids
        })
    return jsonify({'success': True, 'data': data})


from werkzeug.security import generate_password_hash
from src.models import Role, Society

@api_mp_bp.route('/societies', methods=['GET'])
def get_societies():
    societies = Society.query.all()
    return jsonify({
        'success': True,
        'data': [{'id': s.id, 'name': s.name} for s in societies]
    })

@api_mp_bp.route('/tags', methods=['GET'])
def get_tags():
    from src.models import Tag
    tags = Tag.query.all()
    return jsonify({
        'success': True,
        'data': [{'id': t.id, 'name': t.name} for t in tags]
    })

@api_mp_bp.route('/register', methods=['POST'])
def mp_register():
    data = request.json or {}
    
    # 必填检验
    required_fields = ['username', 'email', 'password', 'real_name', 'student_id', 'phone', 'qq', 'college', 'major', 'grade']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'success': False, 'msg': f'请填写完整信息: {field}'})

    student_id = data.get('student_id')
    username = data.get('username')
    email = data.get('email')

    # 检查冲突
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'msg': '用户名已被使用'})
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'msg': '邮箱已被注册'})
    if StudentInfo.query.filter_by(student_id=student_id).first():
        return jsonify({'success': False, 'msg': '学号已被绑定'})

    # 角色
    stmt = db.select(Role).filter_by(name='Student')
    student_role = db.session.execute(stmt).scalar_one_or_none()
    if not student_role:
        student_role = Role(name='Student')
        db.session.add(student_role)
        db.session.commit()

    wx_openid = data.get('wx_openid')
    is_wx_mode = bool(wx_openid)

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(data.get('password')),
        role=student_role,
        active=is_wx_mode,
        wx_openid=wx_openid if is_wx_mode else None,
        register_source='miniprogram_wx' if is_wx_mode else 'miniprogram_form'
    )
    db.session.add(user)
    db.session.flush()

    student_info = StudentInfo(
        user_id=user.id,
        real_name=data.get('real_name'),
        student_id=student_id,
        grade=data.get('grade'),
        major=data.get('major'),
        college=data.get('college'),
        phone=data.get('phone', ''),
        qq=data.get('qq', ''),
        has_selected_tags=False
    )
    
    society_ids = data.get('society_ids')
    if society_ids and isinstance(society_ids, list):
        for sid in society_ids:
            soc = Society.query.get(sid)
            if soc:
                if not student_info.society_id:
                    student_info.society_id = soc.id
                student_info.joined_societies.append(soc)

    tag_ids = data.get('tag_ids')
    if tag_ids and isinstance(tag_ids, list):
        from src.models import Tag
        for tid in tag_ids:
            tag = Tag.query.get(tid)
            if tag:
                student_info.tags.append(tag)
        student_info.has_selected_tags = True
        
    db.session.add(student_info)
    
    from src.models import AIUserPreferences
    ai_preferences = AIUserPreferences(
        user_id=user.id,
        enable_history=True,
        max_history_count=50
    )
    db.session.add(ai_preferences)
    
    db.session.commit()
    
    if not is_wx_mode:
        from src.routes.auth import _send_verification_email
        try:
            _send_verification_email(user)
            return jsonify({'success': True, 'msg': '注册成功！请前往邮箱查收验证邮件后再登录。'})
        except Exception as e:
            current_app.logger.error(f"发 送邮箱验证邮件失败: user_id={user.id}, error={e}", exc_info=True)
            return jsonify({'success': True, 'msg': '注册成功，但验证邮件发送失败，需在网页端重试。'})
    else:
        return jsonify({'success': True, 'msg': '注册并关联微信成功，请返回一键登录！'})

@api_mp_bp.route('/notifications/<int:id>/read', methods=['POST'])
@require_token
def mp_notification_read(id):
    from src.models import NotificationRead
    user = request.mp_user
    # 查找是否已存在记录
    n_read = NotificationRead.query.filter_by(user_id=user.id, notification_id=id).first()
    if not n_read:
        n_read = NotificationRead(user_id=user.id, notification_id=id)
        db.session.add(n_read)
        db.session.commit()
    return jsonify({'success': True})


@api_mp_bp.route('/profile', methods=['GET', 'POST'])
@require_token
def mp_profile():
    user = request.mp_user
    student = user.student_info
    if not student:
        return jsonify({'success': False, 'msg': '请先完善档案', 'need_info': True})

    if request.method == 'GET':
        soc_name = student.society.name if student.society else '未选择社团'
        return jsonify({
            'success': True,
            'data': {
                'username': user.username,
                'email': user.email,
                'real_name': student.real_name,
                'student_id': student.student_id,
                'college': student.college,
                'major': student.major,
                'grade': student.grade,
                'phone': student.phone,
                'qq': student.qq,
                'society_name': soc_name,
                'points': student.points
            }
        })
    else:
        # POST Update Profile
        data = request.json or {}
        
        # 仅允许更新部分非核心安全信息
        email = data.get('email')
        if email and email != user.email:
            existing_email = User.query.filter_by(email=email).first()
            if existing_email and existing_email.id != user.id:
                return jsonify({'success': False, 'msg': '邮箱已存在'})
            user.email = email
            
        if data.get('real_name'): student.real_name = data.get('real_name')
        if data.get('college'): student.college = data.get('college')
        if data.get('major'): student.major = data.get('major')
        if data.get('grade'): student.grade = data.get('grade')
        if data.get('phone') is not None: student.phone = data.get('phone')
        if data.get('qq') is not None: student.qq = data.get('qq')
        
        # 不要让用户随意改社团（看需求），如果需要可以在这里加上society_id的更新
        society_id = data.get('society_id')
        if society_id:
            from src.models import Society
            soc = Society.query.get(society_id)
            if soc:
                student.society_id = soc.id
                if soc not in student.joined_societies:
                    student.joined_societies.append(soc)

        db.session.commit()
        return jsonify({'success': True, 'msg': '个人资料已更新'})

@api_mp_bp.route('/chat', methods=['POST'])
@require_token
def mp_ai_chat():
    from flask import current_app, request, jsonify
    import os
    import requests
    
    user = request.mp_user
    data = request.get_json(silent=True) or {}
    prompt = (data.get('message') or data.get('prompt') or '').strip()
    if not prompt:
        return jsonify({'success': False, 'msg': '请输入内容'}), 400

    api_key = os.environ.get("ARK_API_KEY") or current_app.config.get('VOLCANO_API_KEY')
    if not api_key:
        return jsonify({'success': False, 'msg': 'AI服务未配置：缺少API Key'}), 500

    url = current_app.config.get('VOLCANO_API_URL', "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    try:
        from src.routes.utils import build_site_data_context
        site_ctx = build_site_data_context(max_activities=15)
        
        student_info = user.student_info
        user_ctx = ""
        if student_info:
            user_tags = [t.name for t in student_info.tags] if student_info.tags else []
            regs = [r.activity.title for r in user.registrations if r.status in ('registered', 'attended')][:5]
            society_name = student_info.society.name if student_info.society else "无"
            user_name = student_info.real_name or "未填"
            user_ctx = f"【当前用户信息】\n姓名:{user_name}\n所属社团:{society_name}\n兴趣标签:{','.join(user_tags)}\n近期活动:{','.join(regs)}"
    except Exception as e:
        site_ctx = ""
        user_ctx = ""

    messages = [
        {
            'role': 'system',
            'content': f"你是智能社团+专属AI团小智。请基于以下系统上下文精准回答，态度亲切活泼。系统数据：\n{site_ctx}\n{user_ctx}"
        }
    ]

    history = data.get('history') or []
    if isinstance(history, list):
        for item in history[-8:]:
            role = item.get('role') if isinstance(item, dict) else None
            content = item.get('content') if isinstance(item, dict) else None
            if role in ('user', 'assistant') and content:
                messages.append({'role': role, 'content': str(content)[:1000]})

    messages.append({'role': 'user', 'content': prompt})

    text_model = current_app.config.get(
        'AI_TEXT_MODEL',
        current_app.config.get('VOLCANO_MODEL', 'ep-20260320185026-9cc4w')
    )

    payload = {
        'model': text_model,
        'messages': messages,
        'temperature': 0.7,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=40)
        if resp.status_code == 200:
            result = resp.json()
            answer = result['choices'][0]['message']['content']
            return jsonify({'success': True, 'data': answer})
        else:
            return jsonify({'success': False, 'msg': f"AI引擎错误: {resp.status_code}"}), 500
    except Exception as e:
        return jsonify({'success': False, 'msg': f"AI请求异常: {str(e)}"}), 500

@api_mp_bp.route('/wechat/webhook', methods=['GET', 'POST'])
def wechat_webhook():
    import hashlib
    from flask import request
    
    token = current_app.config.get('WX_MESSAGE_TOKEN', 'RegWechatToken2026')
    
    if request.method == 'GET':
        signature = request.args.get('signature', '')
        timestamp = request.args.get('timestamp', '')
        nonce = request.args.get('nonce', '')
        echostr = request.args.get('echostr', '')
        
        # 按照微信官方要求：字典排序 -> 拼接 -> sha1 加密
        s = [token, timestamp, nonce]
        s.sort()
        s = ''.join(s)
        
        hash_str = hashlib.sha1(s.encode('utf-8')).hexdigest()
        
        if hash_str == signature:
            return echostr
        else:
            return "Signature Verification Failed", 403
            
    # POST 请求是微信发送的真实消息推送，这里可以直接返回 success
    return "success"
