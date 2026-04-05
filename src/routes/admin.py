import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import logging
from datetime import datetime, timedelta
import hashlib
import json
import re
import io
import threading
import uuid
import time
from io import BytesIO  # 添加BytesIO导入
import csv
import qrcode
from PIL import Image, ImageDraw, ImageFont
import base64
import pandas as pd  # 添加pandas导入
import tempfile  # 添加tempfile导入
import zipfile  # 添加zipfile导入
import pytz
import requests
import mimetypes
from itsdangerous import URLSafeTimedSerializer
from flask import (
    Blueprint, render_template, redirect, url_for, flash, request, current_app, 
    send_from_directory, send_file, Response, make_response, jsonify
)
from flask_login import current_user, login_required
from sqlalchemy import func, desc, or_, and_, extract, text, case
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename
from src import cache, limiter
from src.models import db, User, Role, StudentInfo, Activity, ActivityTeam, Registration, SystemLog, Tag, Message, Notification, NotificationRead, PointsHistory, ActivityReview, ActivityCheckin, AIChatHistory, AIChatSession, AIUserPreferences, ActivityDocument, student_tags, activity_tags, student_societies, Announcement, Society
from src.routes.utils import admin_required, log_action, is_super_admin
from src.utils.time_helpers import normalize_datetime_for_db, display_datetime, ensure_timezone_aware, get_localized_now, get_beijing_time, safe_less_than, safe_greater_than, get_activity_status
from src.forms import ActivityForm  # 添加ActivityForm导入
from flask_wtf.csrf import generate_csrf, validate_csrf
from src.utils import get_compatible_paginate
from src.utils.input_safety import sanitize_plain_text, sanitize_rich_html

# 创建蓝图
admin_bp = Blueprint('admin', __name__)

# 配置日志记录器
logger = logging.getLogger(__name__)

DOCUMENT_CATEGORY_LABELS = {
    'certificate': '参赛证明',
    'award': '奖状',
    'notice': '官方通知',
    'other': '其他资料'
}


def _invalidate_home_page_caches():
    """后台内容变更后精准失效首页公共缓存。"""
    try:
        home_activities_view = current_app.view_functions.get('main.home_activities_api')
        if home_activities_view:
            cache.delete_memoized(home_activities_view)

        public_notifications_view = current_app.view_functions.get('main.public_notifications_api')
        if public_notifications_view:
            cache.delete_memoized(public_notifications_view)
    except Exception as e:
        logger.warning(f"首页缓存失效失败（已忽略）: {e}")


def _current_scope_society_id():
    if is_super_admin(current_user):
        return None
    return getattr(current_user, 'managed_society_id', None)


def _apply_activity_scope(query):
    scope_id = _current_scope_society_id()
    if scope_id:
        query = query.filter(Activity.society_id == scope_id)
    return query


def _apply_student_scope(query):
    scope_id = _current_scope_society_id()
    if scope_id:
        query = query.filter(
            or_(
                StudentInfo.society_id == scope_id,
                StudentInfo.joined_societies.any(Society.id == scope_id)
            )
        )
    return query


def _scope_guard_student(student):
    scope_id = _current_scope_society_id()
    if not scope_id:
        return True
    if not student:
        return False
    if getattr(student, 'society_id', None) == scope_id:
        return True
    joined_ids = {s.id for s in (getattr(student, 'joined_societies', []) or [])}
    return scope_id in joined_ids


def _scope_guard_activity(activity):
    scope_id = _current_scope_society_id()
    if not scope_id:
        return True
    return bool(activity and getattr(activity, 'society_id', None) == scope_id)


def _scope_display_label():
    scope_id = _current_scope_society_id()
    if not scope_id:
        return '全站数据'
    society = db.session.get(Society, scope_id)
    return f"{society.name}社团" if society else '当前社团'


def _flash_form_errors(form, fallback_message='表单填写有误，请检查后重试'):
    """将WTForms错误汇总为可读提示，避免用户不知道失败原因。"""
    try:
        error_messages = []
        for field_name, messages in (form.errors or {}).items():
            field = getattr(form, field_name, None)
            label = getattr(getattr(field, 'label', None), 'text', None) or field_name
            if messages:
                error_messages.append(f"{label}：{messages[0]}")

        if error_messages:
            flash('保存失败，请修正：' + '；'.join(error_messages), 'warning')
        else:
            flash(fallback_message, 'warning')
    except Exception:
        flash(fallback_message, 'warning')


def _collect_form_error_messages(form):
    """收集表单错误信息，供AJAX接口返回前端展示。"""
    messages = []
    try:
        for field_name, field_messages in (form.errors or {}).items():
            field = getattr(form, field_name, None)
            label = getattr(getattr(field, 'label', None), 'text', None) or field_name
            for msg in (field_messages or []):
                messages.append(f"{label}：{msg}")
    except Exception:
        return []
    return messages


def _is_ajax_request():
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in (request.headers.get('Accept') or '')
    )


def _create_approval_request(req_type, req_action, payload, target_id=None):
    details = {
        'status': 'pending',
        'type': req_type,
        'action': req_action,
        'payload': payload or {},
        'target_id': target_id,
        'requester_id': current_user.id,
        'requester_name': current_user.username,
        'requested_at': datetime.now(pytz.utc).isoformat()
    }
    db.session.add(SystemLog(
        user_id=current_user.id,
        action='approval_request',
        details=json.dumps(details, ensure_ascii=False),
        ip_address=request.remote_addr,
        created_at=datetime.now(pytz.utc)
    ))
    db.session.commit()


def _remove_student_from_scope_society(student):
    scope_id = _current_scope_society_id()
    if not scope_id or not student:
        return False

    changed = False
    joined = list(student.joined_societies or [])
    remaining = [s for s in joined if s.id != scope_id]
    if len(remaining) != len(joined):
        student.joined_societies = remaining
        changed = True

    if student.society_id == scope_id:
        student.society_id = remaining[0].id if remaining else None
        changed = True

    return changed


def _notify_approval_result(requester_id, req_type, req_action, approved, reject_reason=''):
    try:
        requester = db.session.get(User, requester_id)
        if not requester or requester.id == current_user.id:
            return

        status_text = '已通过' if approved else '已驳回'
        action_map = {
            'create': '新增',
            'edit': '修改',
            'delete': '删除'
        }
        type_map = {
            'notification': '通知',
            'tag': '标签',
            'announcement': '公告'
        }
        action_text = action_map.get(req_action, req_action or '操作')
        type_text = type_map.get(req_type, req_type or '内容')

        subject = f'审核结果通知：{type_text}{action_text}{status_text}'
        content = f'你提交的{type_text}{action_text}审核申请{status_text}。'
        if reject_reason:
            content += f' 驳回原因：{reject_reason}'

        db.session.add(Message(
            sender_id=current_user.id,
            receiver_id=requester.id,
            subject=subject,
            content=content,
            is_read=False,
            created_at=get_localized_now()
        ))
    except Exception as e:
        logger.warning(f"发送审核结果站内信失败 requester_id={requester_id}: {e}")


@admin_bp.route('/societies')
@admin_required
def manage_societies():
    if not is_super_admin(current_user):
        flash('仅总管理员可管理社团', 'danger')
        return redirect(url_for('admin.dashboard'))

    societies = db.session.execute(db.select(Society).order_by(Society.created_at.desc())).scalars().all()
    admin_rows = db.session.execute(
        db.select(User.id, User.username, User.managed_society_id)
        .join(Role, User.role_id == Role.id)
        .filter(func.lower(Role.name) == 'admin')
    ).all()
    admin_users = db.session.execute(
        db.select(User)
        .join(Role, User.role_id == Role.id)
        .filter(func.lower(Role.name) == 'admin', User.is_super_admin == False)
        .order_by(User.username.asc())
    ).scalars().all()
    admin_map = {}
    for row in admin_rows:
        if not row.managed_society_id:
            continue
        admin_map.setdefault(row.managed_society_id, []).append({'id': row.id, 'username': row.username})

    return render_template('admin/societies.html', societies=societies, admin_map=admin_map, admin_users=admin_users)


@admin_bp.route('/society/create', methods=['POST'])
@admin_required
def create_society():
    if not is_super_admin(current_user):
        flash('仅总管理员可新增社团', 'danger')
        return redirect(url_for('admin.dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(url_for('admin.manage_societies'))

    name = (request.form.get('name') or '').strip()
    code = (request.form.get('code') or '').strip().lower()
    description = (request.form.get('description') or '').strip()
    if not name or not code:
        flash('社团名称和编码不能为空', 'warning')
        return redirect(url_for('admin.manage_societies'))

    exists = db.session.execute(db.select(Society).filter(or_(Society.name == name, Society.code == code))).scalar_one_or_none()
    if exists:
        flash('社团名称或编码已存在', 'warning')
        return redirect(url_for('admin.manage_societies'))

    society = Society(name=name, code=code, description=description, is_active=True)
    db.session.add(society)
    db.session.commit()
    flash('社团已创建', 'success')
    return redirect(url_for('admin.manage_societies'))


@admin_bp.route('/society/<int:society_id>/edit', methods=['POST'])
@admin_required
def edit_society(society_id):
    if not is_super_admin(current_user):
        flash('仅总管理员可编辑社团', 'danger')
        return redirect(url_for('admin.dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(url_for('admin.manage_societies'))

    society = db.get_or_404(Society, society_id)
    name = (request.form.get('name') or '').strip()
    code = (request.form.get('code') or '').strip().lower()
    description = (request.form.get('description') or '').strip()
    is_active = bool(request.form.get('is_active'))

    if not name or not code:
        flash('社团名称和编码不能为空', 'warning')
        return redirect(url_for('admin.manage_societies'))

    exists = db.session.execute(
        db.select(Society).filter(
            Society.id != society.id,
            or_(Society.name == name, Society.code == code)
        )
    ).scalar_one_or_none()
    if exists:
        flash('社团名称或编码已存在', 'warning')
        return redirect(url_for('admin.manage_societies'))

    society.name = name
    society.code = code
    society.description = description
    society.is_active = is_active
    db.session.commit()
    flash('社团信息已更新', 'success')
    return redirect(url_for('admin.manage_societies'))


@admin_bp.route('/society/<int:society_id>/delete', methods=['POST'])
@admin_required
def delete_society(society_id):
    if not is_super_admin(current_user):
        flash('仅总管理员可删除社团', 'danger')
        return redirect(url_for('admin.dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(url_for('admin.manage_societies'))

    society = db.get_or_404(Society, society_id)
    if (society.code or '').strip().lower() == 'default':
        flash('默认社团不可删除', 'warning')
        return redirect(url_for('admin.manage_societies'))

    try:
        activity_ids = db.session.execute(
            db.select(Activity.id).filter(Activity.society_id == society.id)
        ).scalars().all()

        deleted_registration = 0
        deleted_checkin = 0
        deleted_review = 0
        deleted_activity = 0
        deleted_points = 0
        deleted_messages = 0
        cleared_admin_bindings = 0
        affected_students = 0

        if activity_ids:
            db.session.execute(activity_tags.delete().where(activity_tags.c.activity_id.in_(activity_ids)))

            deleted_registration = Registration.query.filter(Registration.activity_id.in_(activity_ids)).delete(synchronize_session=False) or 0
            deleted_checkin = ActivityCheckin.query.filter(ActivityCheckin.activity_id.in_(activity_ids)).delete(synchronize_session=False) or 0
            deleted_review = ActivityReview.query.filter(ActivityReview.activity_id.in_(activity_ids)).delete(synchronize_session=False) or 0

            deleted_points += PointsHistory.query.filter(
                or_(
                    PointsHistory.activity_id.in_(activity_ids),
                    PointsHistory.society_id == society.id
                )
            ).delete(synchronize_session=False) or 0

            deleted_activity = Activity.query.filter(Activity.id.in_(activity_ids)).delete(synchronize_session=False) or 0
        else:
            deleted_points += PointsHistory.query.filter(PointsHistory.society_id == society.id).delete(synchronize_session=False) or 0

        deleted_messages = Message.query.filter(Message.target_society_id == society.id).delete(synchronize_session=False) or 0

        cleared_admin_bindings = User.query.filter(User.managed_society_id == society.id).update(
            {User.managed_society_id: None}, synchronize_session=False
        ) or 0

        students = db.session.execute(
            db.select(StudentInfo).filter(
                or_(
                    StudentInfo.society_id == society.id,
                    StudentInfo.joined_societies.any(Society.id == society.id)
                )
            )
        ).scalars().all()

        for stu in students:
            before_count = len(stu.joined_societies or [])
            remaining_societies = [s for s in (stu.joined_societies or []) if s.id != society.id]
            stu.joined_societies = remaining_societies
            if stu.society_id == society.id:
                stu.society_id = remaining_societies[0].id if remaining_societies else None
            if before_count != len(remaining_societies) or stu.society_id != society.id:
                affected_students += 1

        db.session.execute(student_societies.delete().where(student_societies.c.society_id == society.id))

        db.session.delete(society)
        db.session.commit()

        flash(
            f'社团已删除，并清理关联数据：活动{deleted_activity}、报名{deleted_registration}、签到{deleted_checkin}、评价{deleted_review}、积分记录{deleted_points}、消息{deleted_messages}、管理员解绑{cleared_admin_bindings}、学生关系调整{affected_students}',
            'success'
        )
        return redirect(url_for('admin.manage_societies'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"删除社团失败，尝试外键兜底清理 society_id={society_id}: {e}", exc_info=True)

        # 兜底：若存在遗漏外键，统一置空/解绑后再重试删除
        try:
            db.session.execute(db.text("UPDATE users SET managed_society_id = NULL WHERE managed_society_id = :sid"), {'sid': society_id})
            db.session.execute(db.text("UPDATE student_info SET society_id = NULL WHERE society_id = :sid"), {'sid': society_id})
            db.session.execute(db.text("UPDATE activities SET society_id = NULL WHERE society_id = :sid"), {'sid': society_id})
            db.session.execute(db.text("UPDATE points_history SET society_id = NULL WHERE society_id = :sid"), {'sid': society_id})
            db.session.execute(db.text("UPDATE message SET target_society_id = NULL WHERE target_society_id = :sid"), {'sid': society_id})
            db.session.execute(student_societies.delete().where(student_societies.c.society_id == society_id))
            db.session.flush()

            society_retry = db.session.get(Society, society_id)
            if society_retry:
                db.session.delete(society_retry)
            db.session.commit()
            flash('社团已删除（已自动执行外键兜底清理）', 'success')
            return redirect(url_for('admin.manage_societies'))
        except Exception as retry_e:
            db.session.rollback()
            logger.error(f"删除社团兜底清理仍失败 society_id={society_id}: {retry_e}", exc_info=True)
            flash('删除社团失败：存在未清理的关联数据，请联系开发排查具体外键', 'danger')
            return redirect(url_for('admin.manage_societies'))


@admin_bp.route('/society/<int:society_id>/assign-admin', methods=['POST'])
@admin_required
def assign_society_admin(society_id):
    if not is_super_admin(current_user):
        flash('仅总管理员可分配社团管理员', 'danger')
        return redirect(url_for('admin.dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(url_for('admin.manage_societies'))

    society = db.get_or_404(Society, society_id)
    admin_user_id = request.form.get('admin_user_id', type=int)
    admin_user = db.session.get(User, admin_user_id) if admin_user_id else None
    if not admin_user or not admin_user.role or (admin_user.role.name or '').strip().lower() != 'admin':
        flash('请选择有效的管理员账号', 'warning')
        return redirect(url_for('admin.manage_societies'))
    if bool(getattr(admin_user, 'is_super_admin', False)):
        flash('总管理员不能绑定为社团管理员', 'warning')
        return redirect(url_for('admin.manage_societies'))

    admin_user.managed_society_id = society.id
    db.session.commit()
    flash(f'已将管理员 {admin_user.username} 绑定到社团 {society.name}', 'success')
    return redirect(url_for('admin.manage_societies'))


@admin_bp.route('/select-society', methods=['GET'])
@admin_required
def select_admin_society():
    if is_super_admin(current_user):
        return redirect(url_for('admin.dashboard'))
    if getattr(current_user, 'managed_society_id', None):
        return redirect(url_for('admin.dashboard'))

    societies = db.session.execute(db.select(Society).filter_by(is_active=True).order_by(Society.name)).scalars().all()
    return render_template('admin/select_society.html', societies=societies)


@admin_bp.route('/select-society', methods=['POST'])
@admin_required
def select_admin_society_submit():
    if is_super_admin(current_user):
        return redirect(url_for('admin.dashboard'))
    if getattr(current_user, 'managed_society_id', None):
        return redirect(url_for('admin.dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新后重试', 'danger')
        return redirect(url_for('admin.select_admin_society'))

    society_id = request.form.get('society_id', type=int)
    society = db.session.get(Society, society_id) if society_id else None
    if not society or not society.is_active:
        flash('请选择有效社团', 'warning')
        return redirect(url_for('admin.select_admin_society'))

    current_user.managed_society_id = society.id
    db.session.commit()
    flash(f'已绑定社团：{society.name}', 'success')
    return redirect(url_for('admin.dashboard'))

def _to_utc_naive_datetime(dt):
    """将表单时间统一转换为 UTC naive，避免数据库时区字段混乱导致 +8h 偏移。"""
    if not dt:
        return None
    aware_dt = ensure_timezone_aware(dt, 'Asia/Shanghai')
    return aware_dt.astimezone(pytz.utc).replace(tzinfo=None)

def _format_review_time_for_display(dt):
    """评价时间展示：兼容历史 naive 数据，统一显示北京时间。"""
    if not dt:
        return '未设置'
    beijing_tz = pytz.timezone('Asia/Shanghai')
    if dt.tzinfo is None:
        localized = beijing_tz.localize(dt)
    else:
        localized = dt.astimezone(beijing_tz)
    return localized.strftime('%Y-%m-%d %H:%M')

def _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.6, max_tokens=1200, timeout_seconds=45, max_retries=1):
    api_key = os.environ.get("ARK_API_KEY") or current_app.config.get('VOLCANO_API_KEY')
    if not api_key:
        raise ValueError('未配置ARK_API_KEY，无法使用AI生成能力')

    url = current_app.config.get('VOLCANO_API_URL', "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    text_model = current_app.config.get(
        'AI_TEXT_MODEL',
        current_app.config.get('VOLCANO_MODEL', 'ep-20260320185026-9cc4w')
    )

    payload = {
        "model": text_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    last_exception = None
    total_attempts = max(1, int(max_retries) + 1)
    for attempt in range(1, total_attempts + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=(8, timeout_seconds))
            response.raise_for_status()
            data = response.json()
            return data['choices'][0]['message']['content'].strip()
        except requests.exceptions.Timeout as e:
            last_exception = e
            logger.warning(f"ARK文本请求超时，第{attempt}/{total_attempts}次: read_timeout={timeout_seconds}s")
            if attempt < total_attempts:
                time.sleep(min(1.5 * attempt, 3.0))
                continue
            raise
        except requests.exceptions.ConnectionError as e:
            last_exception = e
            logger.warning(f"ARK文本请求连接异常，第{attempt}/{total_attempts}次: {e}")
            if attempt < total_attempts:
                time.sleep(min(1.0 * attempt, 2.0))
                continue
            raise
        except requests.exceptions.HTTPError as e:
            last_exception = e
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)
            # 服务端暂时性错误重试，4xx参数错误不重试
            if status_code and status_code >= 500 and attempt < total_attempts:
                logger.warning(f"ARK文本请求服务端错误，第{attempt}/{total_attempts}次: status={status_code}")
                time.sleep(min(1.2 * attempt, 2.5))
                continue
            raise

    if last_exception:
        raise last_exception
    raise ValueError('ARK文本请求失败：未知错误')

def _extract_json_block(raw_text):
    text = (raw_text or '').strip()
    if not text:
        return {}

    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}
    return {}


def _normalize_ai_datetime_value(raw_value):
    """将AI时间字段统一规范为北京时间字符串: YYYY-MM-DD HH:MM。"""
    text = str(raw_value or '').strip()
    if not text:
        return ''

    beijing_tz = pytz.timezone('Asia/Shanghai')

    def _fmt(dt_obj):
        if dt_obj.tzinfo is None:
            dt_obj = beijing_tz.localize(dt_obj)
        else:
            dt_obj = dt_obj.astimezone(beijing_tz)
        return dt_obj.strftime('%Y-%m-%d %H:%M')

    normalized = text.replace('/', '-')
    normalized = re.sub(r'\s+', ' ', normalized).strip()

    # 优先处理ISO-8601及带时区格式，确保Z/±HH:MM按北京时间展示
    iso_candidate = normalized.replace('T', ' ')
    if iso_candidate.endswith('Z'):
        iso_candidate = iso_candidate[:-1] + '+00:00'
    if re.match(r'.*[+-]\d{4}$', iso_candidate):
        iso_candidate = f"{iso_candidate[:-5]}{iso_candidate[-5:-2]}:{iso_candidate[-2:]}"

    for candidate in (iso_candidate, normalized):
        try:
            parsed = datetime.fromisoformat(candidate)
            return _fmt(parsed)
        except Exception:
            pass

    # 兼容常见中文文本中抽取出的时间格式
    format_candidates = [
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%d'
    ]
    for fmt in format_candidates:
        try:
            parsed = datetime.strptime(normalized, fmt)
            if fmt == '%Y-%m-%d':
                parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            return _fmt(parsed)
        except Exception:
            continue

    # 最后兜底：从混合文本中提取日期与时间
    match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})\s+(\d{1,2}:\d{2})(?::\d{2})?', normalized)
    if match:
        dt_text = f"{match.group(1)} {match.group(2)}"
        try:
            parsed = datetime.strptime(dt_text, '%Y-%m-%d %H:%M')
            return _fmt(parsed)
        except Exception:
            return ''

    return ''

def _normalize_activity_ai_payload(payload):
    if not isinstance(payload, dict):
        return {}

    raw_mode = str(payload.get('registration_mode', '') or '').strip().lower()
    if raw_mode in ('team', 'teams', 'group', 'grouped', '团队', '组队', '团队报名', '小组'):
        normalized_mode = 'team'
    elif raw_mode in ('individual', 'single', 'solo', '个人', '个人报名', '单人'):
        normalized_mode = 'individual'
    else:
        normalized_mode = ''

    normalized = {
        'title': str(payload.get('title', '') or '').strip(),
        'description': str(payload.get('description', '') or '').strip(),
        'location': str(payload.get('location', '') or '').strip(),
        'start_time': str(payload.get('start_time', '') or '').strip(),
        'end_time': str(payload.get('end_time', '') or '').strip(),
        'registration_start_time': str(payload.get('registration_start_time', '') or '').strip(),
        'registration_deadline': str(payload.get('registration_deadline', '') or '').strip(),
        'max_participants': payload.get('max_participants', ''),
        'points': payload.get('points', ''),
        'status': str(payload.get('status', '') or '').strip(),
        'is_featured': bool(payload.get('is_featured', False)),
        'registration_mode': normalized_mode,
        'team_max_members': payload.get('team_max_members', ''),
        'team_max_count': payload.get('team_max_count', '')
    }

    for int_key in ('max_participants', 'points', 'team_max_members', 'team_max_count'):
        value = normalized[int_key]
        if value in ('', None):
            normalized[int_key] = ''
            continue
        try:
            normalized[int_key] = int(value)
        except Exception:
            normalized[int_key] = ''

    if normalized['team_max_members'] != '':
        normalized['team_max_members'] = max(1, int(normalized['team_max_members']))
    if normalized['team_max_count'] != '':
        normalized['team_max_count'] = max(0, int(normalized['team_max_count']))

    if normalized['status'] not in ('active', 'completed', 'cancelled'):
        normalized['status'] = 'active'

    datetime_fields = (
        'start_time',
        'end_time',
        'registration_start_time',
        'registration_deadline'
    )
    for field_name in datetime_fields:
        normalized[field_name] = _normalize_ai_datetime_value(normalized.get(field_name, ''))

    return normalized

def _attach_ai_poster_from_url(activity, image_url):
    if not image_url:
        return False

    if image_url.startswith('data:image/'):
        try:
            header, encoded = image_url.split(',', 1)
        except ValueError as exc:
            raise ValueError('AI生成图片数据格式无效') from exc

        mime_match = re.match(r'^data:(image/[a-zA-Z0-9.+-]+);base64$', header)
        if not mime_match:
            raise ValueError('AI生成图片MIME类型无效')

        mime_type = mime_match.group(1).lower()
        raw_bytes = base64.b64decode(encoded)

        ext_map = {
            'image/png': 'png',
            'image/jpeg': 'jpg',
            'image/jpg': 'jpg',
            'image/webp': 'webp'
        }
        extension = ext_map.get(mime_type, 'png')
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"activity_{activity.id}_ai_{timestamp}.{extension}"

        activity.poster_image = filename
        activity.poster_data = raw_bytes
        activity.poster_mimetype = mime_type
        return True

    response = requests.get(image_url, timeout=60)
    response.raise_for_status()

    mime_type = response.headers.get('Content-Type', 'image/png').split(';')[0].strip().lower()
    if not mime_type.startswith('image/'):
        raise ValueError('AI生成结果不是图片格式')

    ext_map = {
        'image/png': 'png',
        'image/jpeg': 'jpg',
        'image/jpg': 'jpg',
        'image/webp': 'webp'
    }
    extension = ext_map.get(mime_type, 'png')
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"activity_{activity.id}_ai_{timestamp}.{extension}"

    activity.poster_image = filename
    activity.poster_data = response.content
    activity.poster_mimetype = mime_type
    return True

def _find_available_font(size):
    font_candidates = [
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/arphic/ukai.ttc',
        '/usr/share/fonts/truetype/arphic/uming.ttc',
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Hiragino Sans GB.ttc',
        '/System/Library/Fonts/STHeiti Medium.ttc',
    ]
    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

def _is_cjk_font(font_obj):
    try:
        font_name = str(getattr(font_obj, 'path', '') or getattr(font_obj, 'getname', lambda: ('', ''))()[0]).lower()
    except Exception:
        font_name = ''
    cjk_keys = ('noto', 'wqy', 'ukai', 'uming', 'pingfang', 'heiti', 'hiragino')
    return any(key in font_name for key in cjk_keys)

def _build_share_poster_image(activity, detail_url):
    target_width = 1080
    target_height = 1520
    bottom_panel_height = 340
    top_panel_height = target_height - bottom_panel_height

    source_image = None
    if activity.poster_data:
        source_image = Image.open(BytesIO(activity.poster_data)).convert('RGB')
    else:
        static_folder = current_app.static_folder or ''
        candidate_paths = []
        poster_name = str(activity.poster_image or '').strip()
        if poster_name:
            if 'banner' in poster_name:
                candidate_paths.append(os.path.join(static_folder, 'img', poster_name))
            candidate_paths.append(os.path.join(static_folder, 'uploads', 'posters', poster_name))
        candidate_paths.append(os.path.join(static_folder, 'img', 'landscape.jpg'))

        for candidate in candidate_paths:
            if candidate and os.path.exists(candidate):
                source_image = Image.open(candidate).convert('RGB')
                break

    if source_image is None:
        source_image = Image.new('RGB', (target_width, top_panel_height), '#f5f6fa')

    src_w, src_h = source_image.size
    scale = max(target_width / src_w, top_panel_height / src_h)
    resized_w = int(src_w * scale)
    resized_h = int(src_h * scale)
    poster_resized = source_image.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    crop_left = (resized_w - target_width) // 2
    crop_top = (resized_h - top_panel_height) // 2
    poster_cropped = poster_resized.crop((crop_left, crop_top, crop_left + target_width, crop_top + top_panel_height))

    final_image = Image.new('RGB', (target_width, target_height), 'white')
    final_image.paste(poster_cropped, (0, 0))

    panel = Image.new('RGB', (target_width, bottom_panel_height), 'white')
    final_image.paste(panel, (0, top_panel_height))

    draw = ImageDraw.Draw(final_image)
    title_font = _find_available_font(52)
    hint_font = _find_available_font(34)
    has_cjk = _is_cjk_font(title_font) and _is_cjk_font(hint_font)

    title = (activity.title or '活动报名').strip() if has_cjk else (activity.title or f'Activity #{activity.id}').strip()
    max_title_width = 670
    wrapped_lines = []
    current = ''
    for ch in title:
        test_line = f"{current}{ch}"
        line_width = draw.textbbox((0, 0), test_line, font=title_font)[2]
        if line_width <= max_title_width:
            current = test_line
        else:
            if current:
                wrapped_lines.append(current)
            current = ch
        if len(wrapped_lines) >= 2:
            break
    if current and len(wrapped_lines) < 2:
        wrapped_lines.append(current)
    if len(title) > sum(len(line) for line in wrapped_lines) and wrapped_lines:
        wrapped_lines[-1] = wrapped_lines[-1].rstrip() + '…'

    text_x = 60
    title_y = top_panel_height + 56
    for idx, line in enumerate(wrapped_lines[:2]):
        draw.text((text_x, title_y + idx * 68), line, font=title_font, fill='#1f2937')

    hint_text = '扫码查看活动详情并报名' if has_cjk else 'Scan QR to view activity details'
    draw.text((text_x, top_panel_height + 210), hint_text, font=hint_font, fill='#4b5563')

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(detail_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    qr_img = qr_img.resize((220, 220), Image.Resampling.NEAREST)
    final_image.paste(qr_img, (target_width - 280, top_panel_height + 58))

    return final_image

AI_POSTER_JOB_TTL_SECONDS = 30 * 60
AI_PARSE_JOB_TTL_SECONDS = 15 * 60
AI_TEXT_JOB_TTL_SECONDS = 20 * 60


def _text_job_dir(app):
    base_dir = app.config.get('INSTANCE_PATH') or app.instance_path or tempfile.gettempdir()
    job_dir = os.path.join(base_dir, 'ai_text_jobs')
    os.makedirs(job_dir, exist_ok=True)
    return job_dir


def _text_job_path(app, job_id):
    safe_job_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(job_id or ''))
    if not safe_job_id:
        raise ValueError('无效任务ID')
    return os.path.join(_text_job_dir(app), f'{safe_job_id}.json')


def _write_text_job(app, job_id, payload):
    file_path = _text_job_path(app, job_id)
    temp_path = f'{file_path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(temp_path, file_path)


def _read_text_job(app, job_id):
    file_path = _text_job_path(app, job_id)
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cleanup_expired_text_jobs(app):
    job_dir = _text_job_dir(app)
    now_ts = datetime.utcnow().timestamp()
    for filename in os.listdir(job_dir):
        if not filename.endswith('.json'):
            continue
        path = os.path.join(job_dir, filename)
        try:
            if now_ts - os.path.getmtime(path) > AI_TEXT_JOB_TTL_SECONDS:
                os.remove(path)
        except Exception:
            continue


def _run_async_text_job(app, job_id, job_kind, payload):
    with app.app_context():
        try:
            current_payload = _read_text_job(app, job_id) or {}
            current_payload.update({
                'job_id': job_id,
                'status': 'running',
                'success': True,
                'done': False,
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            })
            _write_text_job(app, job_id, current_payload)

            result_data = {}

            if job_kind == 'activity_description':
                title = (payload.get('title') or '').strip()
                system_prompt = "你是高校活动运营助手，只输出简洁、可直接发布的活动文案。"
                user_prompt = (
                    f"活动标题：{title}\n"
                    "请输出一段活动描述，包含：活动亮点、参与对象、流程要点、收获价值。"
                    "要求：中文、150-280字、自然口语化、不要使用Markdown标题。"
                )
                content = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.7, max_tokens=800)
                result_data = {'description': content}

            elif job_kind == 'review_cluster_summary':
                activity_id = int(payload.get('activity_id'))
                activity = db.get_or_404(Activity, activity_id)
                reviews = ActivityReview.query.filter_by(activity_id=activity_id).order_by(ActivityReview.created_at.desc()).all()

                if not reviews:
                    result_data = {'summary': '该活动暂无评价数据，暂无法生成聚类总结。'}
                else:
                    review_lines = []
                    for idx, review in enumerate(reviews[:120], start=1):
                        review_text = (review.review or '').replace('\n', ' ').strip()
                        if len(review_text) > 180:
                            review_text = review_text[:180] + '…'
                        review_lines.append(
                            f"{idx}. 总评{review.rating}/5，内容{review.content_quality or '-'}，组织{review.organization or '-'}，设施{review.facility or '-'}，反馈：{review_text}"
                        )

                    system_prompt = "你是高校活动评价分析助手，擅长把大量反馈聚类并输出行动建议。"
                    user_prompt = (
                        f"活动标题：{activity.title}\n"
                        f"评价总数：{len(reviews)}\n"
                        f"评价样本：\n" + "\n".join(review_lines) + "\n\n"
                        "请输出：\n"
                        "1) 评价主题聚类（3-6类，每类含‘主题名、占比估计、典型反馈、优先级’）\n"
                        "2) Top3 优点\n"
                        "3) Top3 问题\n"
                        "4) 可执行改进清单（按高/中/低优先级）\n"
                        "要求：中文，结构清晰，直接可用于运营复盘。"
                    )
                    summary = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.3, max_tokens=1600)
                    result_data = {'summary': summary}

            elif job_kind == 'retrospective_report':
                activity_id = int(payload.get('activity_id'))
                activity = db.get_or_404(Activity, activity_id)
                reviews = ActivityReview.query.filter_by(activity_id=activity_id).all()
                registrations = Registration.query.filter_by(activity_id=activity_id).all()

                total_registered = len(registrations)
                attended_count = sum(1 for r in registrations if r.status == 'attended')
                cancelled_count = sum(1 for r in registrations if r.status == 'cancelled')
                no_show_count = max(total_registered - attended_count - cancelled_count, 0)
                attendance_rate = (attended_count / total_registered * 100.0) if total_registered else 0.0

                avg_rating = (sum((r.rating or 0) for r in reviews) / len(reviews)) if reviews else 0.0
                avg_content = (sum((r.content_quality or 0) for r in reviews) / len(reviews)) if reviews else 0.0
                avg_organization = (sum((r.organization or 0) for r in reviews) / len(reviews)) if reviews else 0.0
                avg_facility = (sum((r.facility or 0) for r in reviews) / len(reviews)) if reviews else 0.0

                sample_reviews = []
                for idx, review in enumerate(reviews[:40], start=1):
                    text_sample = (review.review or '').replace('\n', ' ').strip()
                    if len(text_sample) > 160:
                        text_sample = text_sample[:160] + '…'
                    sample_reviews.append(f"{idx}. {text_sample}")

                system_prompt = "你是高校活动运营复盘顾问，擅长产出可执行复盘报告。"
                user_prompt = (
                    f"活动：{activity.title}\n"
                    f"状态：{activity.status}\n"
                    f"时间：{display_datetime(activity.start_time, None, '%Y-%m-%d %H:%M')} - {display_datetime(activity.end_time, None, '%Y-%m-%d %H:%M')}\n"
                    f"地点：{activity.location or '未设置'}\n"
                    f"积分：{activity.points or 0}\n"
                    f"报名人数：{total_registered}\n"
                    f"到场人数：{attended_count}\n"
                    f"取消人数：{cancelled_count}\n"
                    f"疑似未到场人数：{no_show_count}\n"
                    f"到场率：{attendance_rate:.1f}%\n"
                    f"评价数：{len(reviews)}\n"
                    f"平均总评分：{avg_rating:.2f}\n"
                    f"内容均分：{avg_content:.2f}\n"
                    f"组织均分：{avg_organization:.2f}\n"
                    f"设施均分：{avg_facility:.2f}\n"
                    f"评价样本：\n{chr(10).join(sample_reviews) if sample_reviews else '暂无评价样本'}\n\n"
                    "请生成复盘报告，包含：\n"
                    "1) 活动目标达成评估\n"
                    "2) 数据结论（报名/到场/评分）\n"
                    "3) 关键问题与根因\n"
                    "4) 下一次活动优化方案（会前/会中/会后）\n"
                    "5) 下次可量化KPI建议（3-5条）\n"
                    "要求：中文、结构清晰、可执行、不要空泛。"
                )
                report = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.35, max_tokens=1900)
                result_data = {'report': report}

            elif job_kind == 'message_reply_draft':
                message_id = int(payload.get('message_id'))
                message = db.get_or_404(Message, message_id)
                sender = db.session.get(User, message.sender_id) if message.sender_id else None
                sender_info = None
                if sender:
                    sender_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=sender.id)).scalar_one_or_none()

                sender_name = (
                    sender_info.real_name if sender_info and sender_info.real_name
                    else (sender.username if sender else '同学')
                )
                sender_student_id = sender_info.student_id if sender_info else ''

                system_prompt = "你是高校社团管理后台助手，请生成专业、友好、可直接发送的中文回复。"
                user_prompt = (
                    f"收到的消息主题：{message.subject or ''}\n"
                    f"发件人：{sender_name}"
                    f"{f'（学号：{sender_student_id}）' if sender_student_id else ''}\n"
                    f"消息内容：\n{(message.content or '').strip()}\n\n"
                    "请输出一段回复正文，要求：\n"
                    "1) 先表示已收到并理解问题\n"
                    "2) 给出明确处理建议或下一步\n"
                    "3) 语气简洁礼貌，不要空话\n"
                    "4) 120-220字\n"
                    "5) 不要使用Markdown标题"
                )
                reply_content = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.5, max_tokens=700)
                reply_subject = f"回复：{message.subject}" if message.subject else "回复：你的反馈"
                result_data = {
                    'reply_subject': reply_subject,
                    'reply_content': reply_content,
                    'receiver_id': message.sender_id
                }
            else:
                raise ValueError('不支持的任务类型')

            done_payload = {
                'job_id': job_id,
                'status': 'success',
                'success': True,
                'done': True,
                'message': 'AI任务已完成',
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            }
            done_payload.update(result_data)
            _write_text_job(app, job_id, done_payload)

        except Exception as e:
            logger.error(f"异步文本任务失败 job_id={job_id}, kind={job_kind}: {e}")
            if isinstance(e, requests.exceptions.Timeout):
                fail_message = 'AI任务超时，请稍后重试'
            elif isinstance(e, requests.exceptions.HTTPError):
                detail = _extract_ark_error_message(getattr(e, 'response', None)) if getattr(e, 'response', None) is not None else ''
                fail_message = f"任务失败: {detail or str(e)}"
            else:
                fail_message = f'任务失败: {str(e)}'

            _write_text_job(app, job_id, {
                'job_id': job_id,
                'status': 'failed',
                'success': False,
                'done': True,
                'message': fail_message,
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            })


def _enqueue_text_job(job_kind, payload):
    app_ref = current_app._get_current_object()
    _cleanup_expired_text_jobs(app_ref)
    job_id = f"text_{uuid.uuid4().hex}"
    _write_text_job(app_ref, job_id, {
        'job_id': job_id,
        'owner_id': current_user.id,
        'job_kind': job_kind,
        'status': 'queued',
        'success': True,
        'done': False,
        'message': '任务已提交',
        'updated_at': datetime.utcnow().isoformat() + 'Z'
    })
    worker = threading.Thread(
        target=_run_async_text_job,
        args=(app_ref, job_id, job_kind, payload),
        daemon=True
    )
    worker.start()
    return job_id


def _parse_job_dir(app):
    base_dir = app.config.get('INSTANCE_PATH') or app.instance_path or tempfile.gettempdir()
    job_dir = os.path.join(base_dir, 'ai_parse_jobs')
    os.makedirs(job_dir, exist_ok=True)
    return job_dir


def _parse_job_path(app, job_id):
    safe_job_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(job_id or ''))
    if not safe_job_id:
        raise ValueError('无效任务ID')
    return os.path.join(_parse_job_dir(app), f'{safe_job_id}.json')


def _write_parse_job(app, job_id, payload):
    file_path = _parse_job_path(app, job_id)
    temp_path = f'{file_path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(temp_path, file_path)


def _read_parse_job(app, job_id):
    file_path = _parse_job_path(app, job_id)
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cleanup_expired_parse_jobs(app):
    job_dir = _parse_job_dir(app)
    now_ts = datetime.utcnow().timestamp()
    for filename in os.listdir(job_dir):
        if not filename.endswith('.json'):
            continue
        path = os.path.join(job_dir, filename)
        try:
            if now_ts - os.path.getmtime(path) > AI_PARSE_JOB_TTL_SECONDS:
                os.remove(path)
        except Exception:
            continue


def _parse_activity_content_with_ai(raw_content):
    system_prompt = "你是活动表单解析助手，必须输出严格JSON。"
    now_beijing = get_beijing_time()
    weekday_map = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    weekday_text = weekday_map[now_beijing.weekday()]
    now_text = now_beijing.strftime('%Y-%m-%d %H:%M')
    user_prompt = (
        "请从下面文本提取活动表单字段，并仅输出JSON对象，不要其他文字。\n"
        "字段: title, description, location, start_time, end_time, registration_start_time, registration_deadline, max_participants, points, status, is_featured, registration_mode, team_max_members, team_max_count\n"
        "规则:\n"
        "1) 时间格式必须是 YYYY-MM-DD HH:MM，无法确定填空字符串\n"
        "2) status 仅可为 active/completed/cancelled，默认active\n"
        "3) max_participants/points 返回数字；未知返回空字符串\n"
        "4) is_featured 返回布尔值\n"
        "5) registration_mode 仅可为 individual 或 team\n"
        "6) 团队报名信息出现时提取 team_max_members 和 team_max_count（数字）\n"
        "7) 允许解析相对时间表达（例如 今天/明天/后天/本周四/下周一/今晚）\n"
        f"当前北京时间: {now_text} {weekday_text}（解析相对时间时请严格基于此时间）\n"
        f"\n原始文本:\n{raw_content}"
    )
    parsed_text = _call_ark_chat_completion(
        system_prompt,
        user_prompt,
        temperature=0.2,
        max_tokens=520,
        timeout_seconds=35,
        max_retries=1
    )
    parsed_json = _extract_json_block(parsed_text)
    return _normalize_activity_ai_payload(parsed_json)


def _run_async_parse_job(app, job_id, raw_content):
    with app.app_context():
        try:
            current_payload = _read_parse_job(app, job_id) or {}
            current_payload.update({
                'job_id': job_id,
                'status': 'running',
                'success': True,
                'done': False,
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            })
            _write_parse_job(app, job_id, current_payload)

            normalized = _parse_activity_content_with_ai(raw_content)
            _write_parse_job(app, job_id, {
                'job_id': job_id,
                'status': 'success',
                'success': True,
                'done': True,
                'data': normalized,
                'message': 'AI已自动填充表单',
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            })
        except Exception as e:
            logger.error(f"异步解析活动内容失败 job_id={job_id}: {e}")
            if isinstance(e, requests.exceptions.Timeout):
                fail_message = 'AI解析超时，请稍后重试'
            elif isinstance(e, requests.exceptions.HTTPError):
                detail = _extract_ark_error_message(getattr(e, 'response', None)) if getattr(e, 'response', None) is not None else ''
                fail_message = f"解析失败: {detail or str(e)}"
            else:
                fail_message = f'解析失败: {str(e)}'
            _write_parse_job(app, job_id, {
                'job_id': job_id,
                'status': 'failed',
                'success': False,
                'done': True,
                'message': fail_message,
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            })


def _poster_quality_profile(quality):
    level = (quality or 'high').strip().lower()
    profiles = {
        'balanced': {
            'size': '1024x1024',
            'guidance_scale': 3,
            'timeout': (8, 35),
            'label': '标准'
        },
        'high': {
            'size': '2K',
            'guidance_scale': 4,
            'timeout': (8, 70),
            'label': '高清'
        },
        'ultra': {
            'size': '2K',
            'guidance_scale': 5,
            'timeout': (8, 85),
            'label': '高细节'
        }
    }
    return profiles.get(level, profiles['high']), (level if level in profiles else 'high')


def _extract_ark_error_message(response):
    """尽量提取ARK返回的可读错误信息，便于前端定位参数问题。"""
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        candidates = [
            data.get('message'),
            data.get('msg'),
            (data.get('error') or {}).get('message') if isinstance(data.get('error'), dict) else None,
            (data.get('error') or {}).get('msg') if isinstance(data.get('error'), dict) else None,
            data.get('detail')
        ]
        for item in candidates:
            if isinstance(item, str) and item.strip():
                return item.strip()

    body_text = (response.text or '').strip()
    if body_text:
        return body_text[:500]
    return ''


def _ark_payload_candidates(model_name, prompt, profile):
    """按兼容性从高到低构造参数组合，尽量避免400参数拒绝。"""
    primary_size = profile['size']
    primary_guidance = int(profile['guidance_scale'])

    candidates = [
        {
            "model": model_name,
            "prompt": prompt,
            "response_format": "url",
            "size": primary_size,
            "watermark": True,
            "guidance_scale": primary_guidance,
        },
        {
            "model": model_name,
            "prompt": prompt,
            "response_format": "url",
            "size": primary_size,
            "watermark": True,
        },
    ]

    if primary_size != '1024x1024':
        candidates.extend([
            {
                "model": model_name,
                "prompt": prompt,
                "response_format": "url",
                "size": "1024x1024",
                "watermark": True,
                "guidance_scale": min(primary_guidance, 3),
            },
            {
                "model": model_name,
                "prompt": prompt,
                "response_format": "url",
                "size": "1024x1024",
                "watermark": True,
            },
        ])

    # 去重，避免同内容重复请求
    seen = set()
    uniq = []
    for item in candidates:
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker in seen:
            continue
        seen.add(marker)
        uniq.append(item)
    return uniq


def _poster_job_dir(app):
    base_dir = app.config.get('INSTANCE_PATH') or app.instance_path or tempfile.gettempdir()
    job_dir = os.path.join(base_dir, 'ai_poster_jobs')
    os.makedirs(job_dir, exist_ok=True)
    return job_dir


def _poster_job_path(app, job_id):
    safe_job_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(job_id or ''))
    if not safe_job_id:
        raise ValueError('无效任务ID')
    return os.path.join(_poster_job_dir(app), f'{safe_job_id}.json')


def _write_poster_job(app, job_id, payload):
    file_path = _poster_job_path(app, job_id)
    temp_path = f'{file_path}.tmp'
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(temp_path, file_path)


def _read_poster_job(app, job_id):
    file_path = _poster_job_path(app, job_id)
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _cleanup_expired_poster_jobs(app):
    job_dir = _poster_job_dir(app)
    now_ts = datetime.utcnow().timestamp()
    for filename in os.listdir(job_dir):
        if not filename.endswith('.json'):
            continue
        path = os.path.join(job_dir, filename)
        try:
            if now_ts - os.path.getmtime(path) > AI_POSTER_JOB_TTL_SECONDS:
                os.remove(path)
        except Exception:
            continue


def _run_async_poster_job(app, job_id, payload):
    with app.app_context():
        try:
            current_payload = _read_poster_job(app, job_id) or {}
            current_payload.update({
                'status': 'running',
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            })
            _write_poster_job(app, job_id, current_payload)

            title = (payload.get('title') or '').strip()
            description = (payload.get('description') or '').strip()
            requirements = (payload.get('requirements') or '').strip()
            model_value = (payload.get('model') or 'ark:doubao-seedream-5-0-260128').strip()
            quality = (payload.get('quality') or 'high').strip().lower()

            prompt = (
                f"高校活动海报，主题：{title}。"
                f"活动简介：{description[:220]}。"
                "视觉要求：现代、青春、清晰排版、主体突出、适合校园宣传。"
            )
            if requirements:
                prompt += f" 额外要求：{requirements}。"

            provider, _, model_name = model_value.partition(':')
            provider = provider.strip().lower()
            model_name = model_name.strip()
            if provider != 'ark' or not model_name:
                raise ValueError('暂不支持该图片模型提供商')

            profile, normalized_quality = _poster_quality_profile(quality)
            image_url = _generate_poster_via_ark(prompt, model_name, normalized_quality)

            image_data_url = ''
            try:
                data_timeout = 18 if normalized_quality in ('high', 'ultra') else 12
                image_data_url = _convert_image_url_to_data_url(image_url, timeout=data_timeout)
            except Exception as convert_error:
                logger.warning(f"异步海报任务转dataURL失败，将回退外链预览: {convert_error}")

            done_payload = {
                'job_id': job_id,
                'status': 'success',
                'success': True,
                'done': True,
                'image_url': image_url,
                'image_data_url': image_data_url,
                'prompt': prompt,
                'model': model_value,
                'model_used': model_value,
                'quality': normalized_quality,
                'quality_label': profile.get('label', ''),
                'fallback': bool(not image_data_url and image_url),
                'message': 'AI海报已生成' + ('（已本地化预览）' if image_data_url else '（外链预览）'),
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            }
            _write_poster_job(app, job_id, done_payload)
        except Exception as e:
            logger.error(f"异步海报任务失败 job_id={job_id}: {e}")
            if isinstance(e, requests.exceptions.Timeout):
                fail_message = 'AI生图超时，请稍后重试'
            elif isinstance(e, requests.exceptions.HTTPError):
                detail = _extract_ark_error_message(getattr(e, 'response', None)) if getattr(e, 'response', None) is not None else ''
                fail_message = f"生成海报失败: {detail or str(e)}"
            else:
                fail_message = f'生成海报失败: {str(e)}'
            _write_poster_job(app, job_id, {
                'job_id': job_id,
                'status': 'failed',
                'success': False,
                'done': True,
                'message': fail_message,
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            })


def _generate_poster_via_ark(prompt, model_name, quality='high'):
    api_key = os.environ.get("ARK_API_KEY") or current_app.config.get('VOLCANO_API_KEY')
    if not api_key:
        raise ValueError('未配置ARK_API_KEY，无法生成海报')

    profile, normalized_quality = _poster_quality_profile(quality)
    image_api = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    payload_candidates = _ark_payload_candidates(model_name, prompt, profile)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    last_error_message = ''
    for index, image_payload in enumerate(payload_candidates):
        response = requests.post(image_api, headers=headers, json=image_payload, timeout=profile['timeout'])
        if response.ok:
            result = response.json()
            data_list = result.get('data') or []
            image_url = ''
            if data_list and isinstance(data_list[0], dict):
                image_url = data_list[0].get('url', '')

            if not image_url:
                raise ValueError('ARK已返回，但未拿到可用图片链接')
            return image_url

        last_error_message = _extract_ark_error_message(response)

        should_try_next = (
            response.status_code in (400, 422) and
            index < len(payload_candidates) - 1
        )
        if should_try_next:
            logger.warning(
                f"ARK生图参数被拒绝，尝试降级重试: status={response.status_code}, "
                f"size={image_payload.get('size')}, msg={last_error_message}"
            )
            continue

        status_text = f"{response.status_code}"
        detail = f": {last_error_message}" if last_error_message else ''
        raise ValueError(f"ARK请求失败({status_text}){detail}")

    if last_error_message:
        raise ValueError(f'ARK请求失败: {last_error_message}')
    raise ValueError('ARK请求失败，未返回可用错误信息')


def _convert_image_url_to_data_url(image_url, timeout=45):
    """将远程图片链接转换为data URL，避免前端预览依赖外网可达性。"""
    if not image_url:
        return ''

    response = requests.get(image_url, timeout=timeout)
    response.raise_for_status()

    mime_type = (response.headers.get('Content-Type', 'image/png') or 'image/png').split(';')[0].strip().lower()
    if not mime_type.startswith('image/'):
        raise ValueError('远程图片返回的Content-Type不是图片')

    raw_bytes = response.content or b''
    if not raw_bytes:
        raise ValueError('远程图片内容为空')

    # 控制体积，避免隐藏字段过大导致提交失败
    if len(raw_bytes) > 2 * 1024 * 1024:
        try:
            img = Image.open(BytesIO(raw_bytes)).convert('RGB')
            max_width = 1920
            if img.width > max_width:
                ratio = max_width / float(img.width)
                img = img.resize((max_width, int(img.height * ratio)), Image.Resampling.LANCZOS)

            output = BytesIO()
            img.save(output, format='JPEG', quality=88, optimize=True)
            raw_bytes = output.getvalue()
            mime_type = 'image/jpeg'
        except Exception:
            # 压缩失败则保持原图，后续由调用方兜底
            pass

    encoded = base64.b64encode(raw_bytes).decode('utf-8')
    return f'data:{mime_type};base64,{encoded}'

@admin_bp.route('/activity/ai/poster-models', methods=['GET'])
@admin_required
def ai_poster_models():
    try:
        static_models = [
            {
                'value': 'ark:doubao-seedream-5-0-260128',
                'label': '火山方舟 · doubao-seedream-5-0-260128（默认，￥0.22/张）'
            },
            {
                'value': 'ark:doubao-seedream-3-0-t2i-250415',
                'label': '火山方舟 · doubao-seedream-3-0-t2i-250415（￥0.26/张）'
            },
            {
                'value': 'ark:doubao-seedream-4-5-251128',
                'label': '火山方舟 · doubao-seedream-4-5-251128（￥0.25/张）'
            },
            {
                'value': 'ark:doubao-seedream-4-0-250828',
                'label': '火山方舟 · doubao-seedream-4-0-250828（￥0.20/张）'
            }
        ]

        return jsonify({
            'success': True,
            'models': static_models
        })
    except Exception as e:
        logger.error(f"获取海报模型列表失败: {e}")
        return jsonify({'success': False, 'message': f'获取模型列表失败: {str(e)}'}), 500

@admin_bp.route('/activity/ai/generate-description', methods=['POST'])
@admin_required
def ai_generate_activity_description():
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        payload = request.get_json(silent=True) or {}
        title = (payload.get('title') or '').strip()
        if not title:
            return jsonify({'success': False, 'message': '请先输入活动标题'}), 400

        system_prompt = "你是高校活动运营助手，只输出简洁、可直接发布的活动文案。"
        user_prompt = (
            f"活动标题：{title}\n"
            "请输出一段活动描述，包含：活动亮点、参与对象、流程要点、收获价值。"
            "要求：中文、150-280字、自然口语化、不要使用Markdown标题。"
        )
        content = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.7, max_tokens=800)
        return jsonify({'success': True, 'description': content})
    except Exception as e:
        logger.error(f"AI生成活动描述失败: {e}")
        return jsonify({'success': False, 'message': f'生成失败: {str(e)}'}), 500


@admin_bp.route('/activity/ai/generate-description-async', methods=['POST'])
@admin_required
def ai_generate_activity_description_async():
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        payload = request.get_json(silent=True) or {}
        title = (payload.get('title') or '').strip()
        if not title:
            return jsonify({'success': False, 'message': '请先输入活动标题'}), 400

        job_id = _enqueue_text_job('activity_description', {'title': title})
        return jsonify({'success': True, 'done': False, 'job_id': job_id, 'message': '任务已提交，正在生成文案'})
    except Exception as e:
        logger.error(f"提交活动描述异步任务失败: {e}")
        return jsonify({'success': False, 'message': f'提交失败: {str(e)}'}), 500

@admin_bp.route('/activity/ai/parse-content', methods=['POST'])
@admin_required
def ai_parse_activity_content():
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        payload = request.get_json(silent=True) or {}
        raw_content = (payload.get('content') or '').strip()
        if not raw_content:
            return jsonify({'success': False, 'message': '请先粘贴活动内容'}), 400

        app_ref = current_app._get_current_object()
        _cleanup_expired_parse_jobs(app_ref)

        job_id = f"parse_{uuid.uuid4().hex}"
        _write_parse_job(app_ref, job_id, {
            'job_id': job_id,
            'status': 'queued',
            'success': True,
            'done': False,
            'message': '解析任务已提交',
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        })

        worker = threading.Thread(
            target=_run_async_parse_job,
            args=(app_ref, job_id, raw_content),
            daemon=True
        )
        worker.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'done': False,
            'message': '解析任务已提交，正在处理中'
        })
    except Exception as e:
        logger.error(f"AI解析活动内容失败: {e}")
        return jsonify({'success': False, 'message': f'解析失败: {str(e)}'}), 500


@admin_bp.route('/activity/ai/parse-content/status/<job_id>', methods=['GET'])
@admin_required
def ai_parse_activity_content_status(job_id):
    try:
        _cleanup_expired_parse_jobs(current_app)
        payload = _read_parse_job(current_app, job_id)
        if not payload:
            return jsonify({'success': False, 'message': '任务不存在或已过期'}), 404
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        logger.error(f"查询AI解析任务状态失败: {e}")
        return jsonify({'success': False, 'message': f'查询失败: {str(e)}'}), 500

@admin_bp.route('/activity/ai/generate-poster', methods=['POST'])
@admin_required
def ai_generate_activity_poster():
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        payload = request.get_json(silent=True) or {}
        title = (payload.get('title') or '').strip()
        description = (payload.get('description') or '').strip()
        requirements = (payload.get('requirements') or '').strip()
        model_value = (payload.get('model') or 'ark:doubao-seedream-5-0-260128').strip()
        quality = (payload.get('quality') or 'high').strip().lower()

        if not title:
            return jsonify({'success': False, 'message': '请先输入活动标题'}), 400

        prompt = (
            f"高校活动海报，主题：{title}。"
            f"活动简介：{description[:220]}。"
            "视觉要求：现代、青春、清晰排版、主体突出、适合校园宣传。"
        )
        if requirements:
            prompt += f" 额外要求：{requirements}。"

        provider, _, model_name = model_value.partition(':')
        provider = provider.strip().lower()
        model_name = model_name.strip()

        if not provider or not model_name:
            return jsonify({'success': False, 'message': '模型参数无效'}), 400

        if provider == 'ark':
            image_url = _generate_poster_via_ark(prompt, model_name, quality)
            image_data_url = ''
            try:
                # 控制总接口时长，避免代理层长时间等待触发524。
                image_data_url = _convert_image_url_to_data_url(image_url, timeout=18 if quality in ('high', 'ultra') else 12)
            except Exception as convert_error:
                logger.warning(f"AI海报外链转dataURL失败，前端将回退外链预览: {convert_error}")

            return jsonify({
                'success': True,
                'image_url': image_url,
                'image_data_url': image_data_url,
                'prompt': prompt,
                'model': model_value,
                'model_used': model_value,
                'quality': quality,
                'message': 'AI海报已生成' + ('（已本地化预览）' if image_data_url else '')
            })
        else:
            return jsonify({'success': False, 'message': '暂不支持该图片模型提供商'}), 400
    except Exception as e:
        logger.error(f"AI生成海报失败: {e}")
        if isinstance(e, requests.exceptions.Timeout):
            return jsonify({'success': False, 'message': 'AI生图超时，请稍后重试'}), 504
        return jsonify({'success': False, 'message': f'生成海报失败: {str(e)}'}), 500


@admin_bp.route('/activity/ai/generate-poster-async', methods=['POST'])
@admin_required
def ai_generate_activity_poster_async():
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        payload = request.get_json(silent=True) or {}
        title = (payload.get('title') or '').strip()
        if not title:
            return jsonify({'success': False, 'message': '请先输入活动标题'}), 400

        app = current_app._get_current_object()
        _cleanup_expired_poster_jobs(app)

        job_id = uuid.uuid4().hex
        _write_poster_job(app, job_id, {
            'job_id': job_id,
            'status': 'pending',
            'success': True,
            'done': False,
            'message': '任务已创建，正在排队生成',
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'updated_at': datetime.utcnow().isoformat() + 'Z'
        })

        worker = threading.Thread(
            target=_run_async_poster_job,
            args=(app, job_id, payload),
            daemon=True
        )
        worker.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'message': '已提交海报生成任务'
        })
    except Exception as e:
        logger.error(f"创建异步海报任务失败: {e}")
        return jsonify({'success': False, 'message': f'提交任务失败: {str(e)}'}), 500


@admin_bp.route('/activity/ai/generate-poster-async/<job_id>', methods=['GET'])
@admin_required
def ai_generate_activity_poster_async_status(job_id):
    try:
        app = current_app._get_current_object()
        _cleanup_expired_poster_jobs(app)

        if not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', str(job_id or '')):
            return jsonify({'success': False, 'message': '任务ID无效'}), 400

        data = _read_poster_job(app, job_id)
        if not data:
            return jsonify({'success': False, 'message': '任务不存在或已过期'}), 404

        # running/pending 也返回 success=True，前端据 done 字段判断是否完成
        if not data.get('done'):
            return jsonify({
                'success': True,
                'done': False,
                'job_id': job_id,
                'status': data.get('status', 'pending'),
                'message': data.get('message', '任务进行中')
            })

        if data.get('success'):
            return jsonify(data)
        return jsonify({
            'success': False,
            'done': True,
            'job_id': job_id,
            'status': data.get('status', 'failed'),
            'message': data.get('message', '任务失败')
        }), 200
    except Exception as e:
        logger.error(f"查询异步海报任务失败: {e}")
        return jsonify({'success': False, 'message': f'查询任务失败: {str(e)}'}), 500

@admin_bp.route('/activity/<int:id>/share-poster')
@admin_required
def export_activity_share_poster(id):
    try:
        activity = db.get_or_404(Activity, id)
        detail_url = url_for('main.activity_detail', activity_id=id, _external=True)
        share_image = _build_share_poster_image(activity, detail_url)

        output = BytesIO()
        share_image.save(output, format='PNG', optimize=True)
        output.seek(0)

        safe_title = re.sub(r'[^\w\u4e00-\u9fff-]+', '_', (activity.title or 'activity')).strip('_') or 'activity'
        return send_file(
            output,
            mimetype='image/png',
            as_attachment=True,
            download_name=f'{safe_title}_分享海报.png'
        )
    except Exception as e:
        logger.error(f"导出活动分享海报失败: {e}")
        flash('生成分享海报失败，请稍后重试', 'danger')
        return redirect(url_for('admin.activity_view', id=id))

def handle_poster_upload(file_data, activity_id):
    """处理活动海报上传
    
    Args:
        file_data: 文件对象
        activity_id: 活动ID
    
    Returns:
        dict: 包含文件名、二进制数据和MIME类型的字典
    """
    try:
        if not file_data or not hasattr(file_data, 'filename') or not file_data.filename:
            logger.warning("无效的文件上传")
            return None
        
        logger.info(f"开始处理海报上传: 文件名={file_data.filename}, 活动ID={activity_id}")
        
        # 确保文件名安全
        filename = secure_filename(file_data.filename)
        
        # 获取MIME类型
        mime_type = file_data.mimetype
        logger.info(f"文件MIME类型: {mime_type}")
        
        # 生成唯一文件名 - 确保活动ID不为None
        _, file_extension = os.path.splitext(filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        
        # 确保 activity_id 是有效的字符串
        if activity_id is None:
            unique_filename = f"activity_temp_{timestamp}{file_extension}"
            logger.info(f"活动ID为空，使用临时ID: {unique_filename}")
        else:
            # 先转换成字符串，处理整数ID情况
            if isinstance(activity_id, int):
                str_activity_id = str(activity_id)
                logger.info(f"活动ID是整数，直接转换为字符串: {str_activity_id}")
            else:
                # 处理活动ID - 如果是对象，获取id属性；如果是基本类型，直接使用
                try:
                    # 尝试访问id属性，适用于ORM对象
                    if hasattr(activity_id, 'id'):
                        str_activity_id = str(activity_id.id)
                        logger.info(f"从对象中提取活动ID: {str_activity_id}")
                    else:
                        # 如果不是对象或没有id属性，直接使用
                        str_activity_id = str(activity_id)
                        logger.info(f"直接使用活动ID: {str_activity_id}")
                except Exception as e:
                    # 如果出错，直接尝试转换为字符串
                    str_activity_id = str(activity_id)
                    logger.warning(f"处理活动ID时出错，使用直接转换: {str_activity_id}, 错误: {e}")
            
            unique_filename = f"activity_{str_activity_id}_{timestamp}{file_extension}"
        
        logger.info(f"生成的唯一文件名: {unique_filename}")
        
        # 保存到文件系统 (同时保留这部分，确保向后兼容)
        try:
            # 确保上传目录存在
            upload_dir = current_app.config['UPLOAD_FOLDER']
            if not os.path.exists(upload_dir):
                os.makedirs(upload_dir, exist_ok=True)
                logger.info(f"创建上传目录: {upload_dir}")
            
            # 保存文件
            file_path = os.path.join(upload_dir, unique_filename)
            file_data.save(file_path)
            logger.info(f"海报文件已保存到: {file_path}")
            
            # 设置文件权限为可读
            try:
                os.chmod(file_path, 0o644)
                logger.info(f"设置文件权限为644: {file_path}")
            except Exception as e:
                logger.warning(f"无法设置文件权限: {e}")
        except Exception as e:
            logger.warning(f"保存文件到文件系统失败: {e}")
        
        # 读取二进制数据 (先保存文件再读取是为了确保文件指针位置正确)
        file_data.seek(0)
        binary_data = file_data.read()
        logger.info(f"已读取二进制数据，大小: {len(binary_data)} 字节")
        
        # 返回文件信息 (包含文件名、二进制数据和MIME类型)
        logger.info(f"活动海报已处理: {unique_filename}")
        return {
            'filename': unique_filename,
            'data': binary_data,
            'mimetype': mime_type
        }
        
    except Exception as e:
        logger.error(f"海报上传失败: {str(e)}", exc_info=True)
        return None


def _activity_docs_upload_dir():
    docs_dir = current_app.config.get('ACTIVITY_DOCS_DIR')
    if not docs_dir:
        base_upload = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, 'static', 'uploads')
        docs_dir = os.path.join(base_upload, 'activity_docs')
    os.makedirs(docs_dir, exist_ok=True)
    return docs_dir


def _activity_docs_allowed_dirs():
    docs_dir = _activity_docs_upload_dir()
    base_upload = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, 'static', 'uploads')
    legacy_dir = os.path.join(base_upload, 'activity_docs')
    return [os.path.realpath(docs_dir), os.path.realpath(legacy_dir)]


def _is_within_allowed_activity_docs(path):
    if not path:
        return False
    try:
        real_path = os.path.realpath(path)
        for allowed_dir in _activity_docs_allowed_dirs():
            try:
                if os.path.commonpath([real_path, allowed_dir]) == allowed_dir:
                    return True
            except ValueError:
                continue
    except Exception:
        return False
    return False


def _resolve_activity_document_file_path(doc):
    if not doc:
        return None

    raw_path = str(doc.file_path or '').replace('\x00', '').strip()
    candidates = []
    if raw_path:
        candidates.append(raw_path)
        # 兼容历史路径：按文件名回落到当前资料目录
        candidates.append(os.path.join(_activity_docs_upload_dir(), os.path.basename(raw_path)))

    for path in candidates:
        if path and os.path.exists(path) and _is_within_allowed_activity_docs(path):
            return path
    return None


def _is_allowed_activity_document(file_obj):
    if not file_obj or not getattr(file_obj, 'filename', None):
        return False
    raw_filename = str(file_obj.filename or '').strip()
    if not raw_filename:
        return False
    clean_name = os.path.basename(raw_filename).replace('\x00', '').strip()
    ext = clean_name.rsplit('.', 1)[-1].lower() if '.' in clean_name else ''
    allowed_exts = set(current_app.config.get('ALLOWED_EXTENSIONS') or set())
    return bool(ext and ext in allowed_exts)


def _save_activity_documents(activity, files, category='certificate', is_public=False, title_prefix='', per_file_meta=None):
    if not activity or not files:
        return []

    saved_docs = []
    docs_dir = _activity_docs_upload_dir()
    now = datetime.now()

    safe_category = category if category in DOCUMENT_CATEGORY_LABELS else 'other'
    safe_prefix = sanitize_plain_text(title_prefix, max_length=64) if title_prefix else ''
    safe_meta = per_file_meta if isinstance(per_file_meta, dict) else {}
    max_single_file_size = 80 * 1024 * 1024

    for file_index, file_obj in enumerate(files):
        if not file_obj or not getattr(file_obj, 'filename', None):
            continue
        if not _is_allowed_activity_document(file_obj):
            continue

        file_meta = safe_meta.get(file_index, {}) if isinstance(safe_meta.get(file_index, {}), dict) else {}

        original_name = os.path.basename(str(file_obj.filename or '')).replace('\x00', '').strip()
        if not original_name:
            continue

        ext = os.path.splitext(original_name)[1].lower() or ''
        if not ext:
            continue

        # 单文件限制 80MB
        current_pos = file_obj.stream.tell()
        file_obj.stream.seek(0, os.SEEK_END)
        stream_size = file_obj.stream.tell()
        file_obj.stream.seek(current_pos, os.SEEK_SET)
        if stream_size and stream_size > max_single_file_size:
            logger.warning(f"活动资料超限已跳过: name={original_name}, size={stream_size}")
            continue

        unique_name = f"activity_doc_{activity.id}_{uuid.uuid4().hex[:12]}_{now.strftime('%Y%m%d%H%M%S')}{ext}"
        save_path = os.path.join(docs_dir, unique_name)
        file_obj.save(save_path)

        try:
            os.chmod(save_path, 0o644)
        except Exception:
            pass

        display_title = sanitize_plain_text(file_meta.get('title', ''), max_length=128)
        if not display_title:
            display_title = os.path.splitext(original_name)[0][:120]
            if safe_prefix:
                display_title = f"{safe_prefix} - {display_title}"[:128]

        meta_category = str(file_meta.get('category', '') or '').strip().lower()
        final_category = meta_category if meta_category in DOCUMENT_CATEGORY_LABELS else safe_category

        meta_public = file_meta.get('is_public', is_public)
        if isinstance(meta_public, str):
            final_public = meta_public.strip().lower() in ['1', 'true', 'yes', 'on']
        else:
            final_public = bool(meta_public)

        file_size = 0
        try:
            file_size = os.path.getsize(save_path)
        except Exception:
            file_size = 0

        mime_type = (getattr(file_obj, 'mimetype', None) or '').strip()
        if not mime_type:
            guessed_mime, _ = mimetypes.guess_type(original_name)
            mime_type = guessed_mime or 'application/octet-stream'

        doc = ActivityDocument(
            activity_id=activity.id,
            uploaded_by=current_user.id,
            title=display_title or f"活动资料_{activity.id}",
            category=final_category,
            file_name=original_name,
            file_path=save_path,
            mime_type=mime_type,
            file_size=file_size,
            is_public=final_public
        )
        db.session.add(doc)
        saved_docs.append(doc)

    return saved_docs


def _notify_students_for_new_documents(activity, docs):
    if not activity or not docs:
        return

    recipient_ids = db.session.execute(
        db.select(Registration.user_id).filter(
            Registration.activity_id == activity.id,
            Registration.status.in_(['registered', 'attended'])
        ).distinct()
    ).scalars().all()

    if not recipient_ids:
        return

    doc_names = [f"《{(d.title or d.file_name or '活动资料')[:30]}》" for d in docs[:3]]
    suffix = '等资料' if len(docs) > 3 else '资料'
    doc_desc = '、'.join(doc_names) + suffix

    for user_id in recipient_ids:
        db.session.add(Notification(
            title=f"活动资料已更新：{activity.title}",
            content=f"你报名的活动《{activity.title}》新增了{doc_desc}，请及时查看并下载。",
            is_important=True,
            created_at=get_localized_now(),
            created_by=user_id,
            is_public=False
        ))

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    # 导入display_datetime函数供所有模板使用
    from src.utils.time_helpers import display_datetime
    try:
        # 获取基本统计数据
        total_students_stmt = _apply_student_scope(db.select(func.count()).select_from(StudentInfo))
        total_students = db.session.execute(total_students_stmt).scalar()
        
        total_activities_stmt = _apply_activity_scope(db.select(func.count()).select_from(Activity))
        total_activities = db.session.execute(total_activities_stmt).scalar()
        
        active_activities_stmt = _apply_activity_scope(db.select(func.count()).select_from(Activity).filter_by(status='active'))
        active_activities = db.session.execute(active_activities_stmt).scalar()
        
        # 获取最近活动
        recent_activities_stmt = _apply_activity_scope(db.select(Activity)).order_by(Activity.created_at.desc()).limit(5)
        recent_activities = db.session.execute(recent_activities_stmt).scalars().all()
        
        # 获取最近注册的学生 - 修复查询，使用Role关联而不是role_id
        recent_students_stmt = db.select(User).join(Role).filter(Role.name == 'Student').join(
            StudentInfo, User.id == StudentInfo.user_id
        )
        if _current_scope_society_id():
            scope_id = _current_scope_society_id()
            recent_students_stmt = recent_students_stmt.filter(
                or_(
                    StudentInfo.society_id == scope_id,
                    StudentInfo.joined_societies.any(Society.id == scope_id)
                )
            )
        recent_students_stmt = recent_students_stmt.order_by(User.created_at.desc()).limit(5)
        recent_students = db.session.execute(recent_students_stmt).scalars().all()
        
        # 获取报名统计
        total_registrations_stmt = db.select(func.count()).select_from(Registration)
        scope_id = _current_scope_society_id()
        if scope_id:
            total_registrations_stmt = total_registrations_stmt.join(Activity, Registration.activity_id == Activity.id).filter(Activity.society_id == scope_id)
        total_registrations = db.session.execute(total_registrations_stmt).scalar()
        
        return render_template('admin/dashboard.html',
                              total_students=total_students,
                              total_activities=total_activities,
                              active_activities=active_activities,
                              recent_activities=recent_activities,
                              recent_students=recent_students,
                              total_registrations=total_registrations,
                              scope_label=_scope_display_label(),
                              display_datetime=display_datetime,
                              Registration=Registration)
    except Exception as e:
        logger.error(f"Error in admin dashboard: {e}")
        flash('加载管理面板时出错', 'danger')
        return render_template('admin/dashboard.html')

@admin_bp.route('/activities')
@admin_bp.route('/activities/<status>')
@admin_required
def activities(status='all'):
    try:
        from src.utils import get_compatible_paginate

        per_page_options = [10, 20, 50, 100]
        requested_per_page = request.args.get('per_page', 10, type=int)
        per_page = requested_per_page if requested_per_page in per_page_options else 10

        jump_page = request.args.get('jump_page', type=int)
        page = jump_page if jump_page and jump_page > 0 else request.args.get('page', 1, type=int)
        page = page if page and page > 0 else 1

        search = (request.args.get('search', '') or '').strip()
        selected_society_id = request.args.get('society_id', type=int)
        date_from = (request.args.get('date_from', '') or '').strip()
        date_to = (request.args.get('date_to', '') or '').strip()

        scope_society_id = _current_scope_society_id()
        
        # 基本查询
        query = _apply_activity_scope(db.select(Activity))

        # 搜索功能
        if search:
            query = query.filter(
                db.or_(
                    Activity.title.ilike(f'%{search}%'),
                    Activity.description.ilike(f'%{search}%'),
                    Activity.location.ilike(f'%{search}%')
                )
            )

        # 社团筛选（社团管理员固定在本社团）
        if scope_society_id:
            selected_society_id = scope_society_id
        elif selected_society_id:
            query = query.filter(Activity.society_id == selected_society_id)

        # 时间范围筛选（按活动开始时间）
        if date_from:
            try:
                start_dt = datetime.strptime(date_from, '%Y-%m-%d')
                query = query.filter(Activity.start_time >= start_dt)
            except ValueError:
                date_from = ''

        if date_to:
            try:
                end_dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
                query = query.filter(Activity.start_time < end_dt)
            except ValueError:
                date_to = ''
        
        # 状态筛选
        if status == 'upcoming':
            now = get_localized_now()
            query = query.filter(
                Activity.status == 'active',
                Activity.start_time > now
            )
        elif status == 'active':
            query = query.filter(Activity.status == 'active')
        elif status == 'completed':
            query = query.filter(Activity.status == 'completed')
        elif status == 'cancelled':
            query = query.filter(Activity.status == 'cancelled')
        elif status == 'draft':
            query = query.filter(Activity.status == 'draft')
        
        # 排序
        query = query.order_by(Activity.created_at.desc())

        # 使用兼容性分页查询
        activities = get_compatible_paginate(db, query, page=page, per_page=per_page, error_out=False)

        if activities.pages > 0 and page > activities.pages:
            page = activities.pages
            activities = get_compatible_paginate(db, query, page=page, per_page=per_page, error_out=False)
        
        # 优化：使用子查询一次性获取所有活动的报名人数
        activity_ids = [activity.id for activity in activities.items]
        if activity_ids:
            reg_counts_stmt = db.select(
                Registration.activity_id,
                func.count(Registration.id).label('count')
            ).filter(
                Registration.activity_id.in_(activity_ids),
                or_(
                    Registration.status == 'registered',
                    Registration.status == 'attended'
                )
            ).group_by(Registration.activity_id)
            
            reg_counts_result = db.session.execute(reg_counts_stmt).all()
            registration_counts = {activity_id: count for activity_id, count in reg_counts_result}
        else:
            registration_counts = {}
        
        # 导入display_datetime函数供模板使用
        from src.utils.time_helpers import display_datetime

        if scope_society_id:
            scope_society = db.session.get(Society, scope_society_id)
            societies = [scope_society] if scope_society else []
        else:
            societies = db.session.execute(
                db.select(Society).filter(Society.is_active == True).order_by(Society.name.asc())
            ).scalars().all()
        
        return render_template('admin/activities.html', 
                              activities=activities, 
                              current_status=status,
                              registration_counts=registration_counts,
                              display_datetime=display_datetime,
                              search=search,
                              societies=societies,
                              selected_society_id=selected_society_id,
                              date_from=date_from,
                              date_to=date_to,
                              per_page=per_page,
                              per_page_options=per_page_options)
    except Exception as e:
        logger.error(f"Error in activities page: {e}")
        flash('加载活动列表时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/activity/create', methods=['GET', 'POST'])
@admin_required
@limiter.limit('20 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def create_activity():
    """创建活动"""
    form = ActivityForm()
    
    # 加载所有标签并设置选项
    tags_stmt = db.select(Tag).order_by(Tag.name)
    tags = db.session.execute(tags_stmt).scalars().all()
    choices = [(tag.id, tag.name) for tag in tags]
    form.tags.choices = choices
    action = (request.form.get('submit_action') or request.form.get('action') or 'publish').strip().lower() if request.method == 'POST' else 'publish'
    is_draft_save = request.method == 'POST' and action == 'save_draft'
    
    if form.validate_on_submit() or is_draft_save:
        try:
            # 获取表单数据
            title = sanitize_plain_text(form.title.data, max_length=120)
            description = sanitize_plain_text(form.description.data, allow_multiline=True, max_length=8000)
            location = sanitize_plain_text(form.location.data, max_length=200)
            start_time = form.start_time.data
            end_time = form.end_time.data
            registration_start_time = form.registration_start_time.data
            registration_deadline = form.registration_deadline.data
            registration_success_message = sanitize_plain_text(
                form.registration_success_message.data,
                allow_multiline=True,
                max_length=1000
            )
            registration_mode = (form.registration_mode.data or 'individual').strip().lower()
            team_max_members = form.team_max_members.data if form.team_max_members.data is not None else 1
            team_max_count = form.team_max_count.data if form.team_max_count.data is not None else 0
            max_participants = form.max_participants.data
            if max_participants is None:
                max_participants = 0
            points = form.points.data
            status = 'draft' if is_draft_save else 'active'
            is_featured = False
            ai_poster_url = (request.form.get('ai_poster_url') or '').strip()

            if is_draft_save:
                if not title:
                    title = '未命名草稿'
                if not location:
                    location = '待定'
            elif not title or not description or not location:
                flash('标题、活动描述、活动地点不能为空（不支持HTML脚本内容）', 'warning')
                return render_template('admin/activity_form.html', form=form, activity=None, existing_documents=[], document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)
            
            # 统一写库：北京时间输入 -> UTC naive（数据库）
            start_time = _to_utc_naive_datetime(start_time)
            end_time = _to_utc_naive_datetime(end_time)
            registration_start_time = _to_utc_naive_datetime(registration_start_time)
            registration_deadline = _to_utc_naive_datetime(registration_deadline)

            if registration_mode not in ('individual', 'team'):
                registration_mode = 'individual'
            if registration_mode == 'individual':
                team_max_members = 1
                team_max_count = 0

            if registration_start_time and registration_deadline and registration_start_time > registration_deadline:
                flash('报名开始时间不能晚于报名截止时间', 'warning')
                return render_template('admin/activity_form.html', form=form, activity=None, existing_documents=[], document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)
            
            # 创建活动
            activity = Activity(
                title=title,
                description=description,
                location=location,
                start_time=start_time,
                end_time=end_time,
                registration_start_time=registration_start_time,
                registration_deadline=registration_deadline,
                registration_success_message=registration_success_message,
                registration_mode=registration_mode,
                team_max_members=max(1, int(team_max_members or 1)),
                team_max_count=max(0, int(team_max_count or 0)),
                max_participants=max_participants,
                points=points,
                status=status,
                is_featured=is_featured,
                created_by=current_user.id,
                society_id=_current_scope_society_id()
            )

            # 先加入会话并flush，确保新建活动拿到稳定ID，避免海报文件名异常
            db.session.add(activity)
            db.session.flush()
            
            # 处理标签
            selected_tag_ids = request.form.getlist('tags')
            if selected_tag_ids:
                # 根据ID直接查询标签对象
                valid_tag_ids = []
                for tag_id_str in selected_tag_ids:
                    try:
                        if tag_id_str and str(tag_id_str).strip().isdigit():
                            valid_tag_ids.append(int(tag_id_str))
                    except Exception as e:
                        logger.warning(f"处理标签ID时出错: {e}, tag_id={tag_id_str}")
                
                logger.info(f"活动标签处理 - 有效标签ID: {valid_tag_ids}")
                
                # 批量获取标签
                if valid_tag_ids:
                    tags_stmt = db.select(Tag).filter(Tag.id.in_(valid_tag_ids))
                    selected_tags = db.session.execute(tags_stmt).scalars().all()
                    logger.info(f"活动标签处理 - 找到{len(selected_tags)}个标签")
                    
                    # 添加标签关联
                    for tag in selected_tags:
                        activity.tags.append(tag)
                        logger.info(f"活动标签处理 - 添加标签: [{tag.id}]{tag.name}")
            
            # 处理海报图片上传
            if form.poster.data and hasattr(form.poster.data, 'filename') and form.poster.data.filename:
                try:
                    # 记录调试信息
                    logger.info(f"准备上传海报，活动ID={activity.id}, 文件名={form.poster.data.filename}")
                    
                    # 使用活动的实际ID上传图片
                    poster_info = handle_poster_upload(form.poster.data, activity.id)
                    if poster_info:
                        # 记录旧海报文件名，以便稍后删除
                        old_poster = activity.poster_image
                        
                        # 更新海报信息
                        activity.poster_image = poster_info['filename']
                        activity.poster_data = poster_info['data']
                        activity.poster_mimetype = poster_info['mimetype']
                        logger.info(f"活动海报信息已更新: {poster_info['filename']}")
                        
                        # 尝试删除旧海报文件（如果存在且不是默认banner）
                        if old_poster and 'banner' not in old_poster:
                            try:
                                old_poster_path = os.path.join(current_app.static_folder or 'src/static', 'uploads', 'posters', old_poster)
                                if os.path.exists(old_poster_path):
                                    os.remove(old_poster_path)
                                    logger.info(f"已删除旧海报文件: {old_poster_path}")
                            except Exception as e:
                                logger.warning(f"删除旧海报文件时出错: {e}")
                    else:
                        logger.error("上传海报失败，未获得有效的文件信息")
                        flash('上传海报失败，请重试', 'warning')
                except Exception as e:
                    logger.error(f"上传海报时出错: {e}", exc_info=True)
                    flash('上传海报时出错，但活动信息已保存', 'warning')
            elif ai_poster_url:
                try:
                    _attach_ai_poster_from_url(activity, ai_poster_url)
                    logger.info(f"活动海报已由AI链接写入: activity_id={activity.id}")
                except Exception as e:
                    logger.error(f"AI海报写入失败: {e}", exc_info=True)
                    flash('AI海报生成结果无法写入，活动信息已保存，可手动上传海报', 'warning')
            
            # 保存到数据库
            db.session.commit()
            _invalidate_home_page_caches()
            
            # 记录操作
            log_action(
                user_id=current_user.id,
                action="create_activity",
                details=f"创建了活动 {activity.id}: {activity.title}"
            )
            
            flash('草稿已保存' if is_draft_save else '活动发布成功', 'success')
            return redirect(url_for('admin.activities'))
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error in create_activity: {str(e)}")
            flash(f'创建活动失败: {str(e)}', 'danger')
    
    if request.method == 'POST' and not form.validate_on_submit() and not is_draft_save:
        _flash_form_errors(form)
        if _is_ajax_request():
            action = (request.form.get('submit_action') or request.form.get('action') or 'publish').strip().lower()
            action_text = '发布' if action == 'publish' else '保存'
            return jsonify({
                'success': False,
                'message': f'{action_text}失败，请修正表单后重试',
                'errors': _collect_form_error_messages(form)
            }), 422

    # GET请求或表单验证失败
    return render_template('admin/activity_form.html', form=form, activity=None, existing_documents=[], document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)

@admin_bp.route('/activity/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
@limiter.limit('30 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def edit_activity(id):
    try:
        # 获取活动对象
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能管理所属社团的活动', 'danger')
            return redirect(url_for('admin.activities'))
        form = ActivityForm(obj=activity)
        
        # 加载所有标签并设置选项
        tags_stmt = db.select(Tag).order_by(Tag.name)
        tags = db.session.execute(tags_stmt).scalars().all()
        form.tags.choices = [(tag.id, tag.name) for tag in tags]
        
        # 设置当前已有的标签
        if request.method == 'GET':
            try:
                form.tags.data = [tag.id for tag in activity.tags]
                logger.info(f"已设置活动 {id} 的当前标签: {form.tags.data}")
            except Exception as e:
                logger.error(f"设置当前标签时出错: {e}")
                form.tags.data = []
        
        def _load_activity_documents():
            return db.session.execute(
                db.select(ActivityDocument)
                .filter(ActivityDocument.activity_id == activity.id)
                .order_by(ActivityDocument.created_at.desc())
            ).scalars().all()

        action = (request.form.get('submit_action') or request.form.get('action') or 'publish').strip().lower() if request.method == 'POST' else 'publish'
        is_draft_save = request.method == 'POST' and action == 'save_draft'

        if form.validate_on_submit() or is_draft_save:
            try:
                # 更新活动信息，但先保存标签引用
                selected_tag_ids = request.form.getlist('tags')
                logger.info(f"选中的标签IDs: {selected_tag_ids}")
                
                # 使用form填充对象，但先处理poster字段
                # 防止文件字段被意外设置为字符串
                poster_data = form.poster.data
                form.poster.data = None
                
                # 保存当前签到设置和创建者ID，因为表单中没有这些字段
                checkin_enabled = activity.checkin_enabled
                checkin_key = activity.checkin_key
                checkin_key_expires = activity.checkin_key_expires
                created_by_id = activity.created_by  # 保存创建者ID
                
                # 统一写库：北京时间输入 -> UTC naive（数据库）
                start_time = _to_utc_naive_datetime(form.start_time.data)
                end_time = _to_utc_naive_datetime(form.end_time.data)
                registration_start_time = _to_utc_naive_datetime(form.registration_start_time.data)
                registration_deadline = _to_utc_naive_datetime(form.registration_deadline.data)

                if registration_start_time and registration_deadline and registration_start_time > registration_deadline:
                    flash('报名开始时间不能晚于报名截止时间', 'warning')
                    return render_template('admin/activity_form.html', form=form, title='编辑活动', activity=activity, existing_documents=_load_activity_documents(), document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)
                
                # 使用form填充对象
                # 手动填充对象字段，避免标签处理错误
                activity.title = sanitize_plain_text(form.title.data, max_length=120)
                activity.description = sanitize_plain_text(form.description.data, allow_multiline=True, max_length=8000)
                activity.location = sanitize_plain_text(form.location.data, max_length=200)
                activity.max_participants = form.max_participants.data if form.max_participants.data is not None else 0
                activity.points = form.points.data
                activity.status = 'draft' if is_draft_save else 'active'
                activity.is_featured = False
                activity.registration_mode = (form.registration_mode.data or 'individual').strip().lower()
                activity.team_max_members = form.team_max_members.data if form.team_max_members.data is not None else 1
                activity.team_max_count = form.team_max_count.data if form.team_max_count.data is not None else 0
                activity.registration_success_message = sanitize_plain_text(
                    form.registration_success_message.data,
                    allow_multiline=True,
                    max_length=1000
                )
                activity.activity_type = form.activity_type.data if hasattr(form, 'activity_type') else None
                # 不处理tags字段，它会在后面单独处理

                if is_draft_save:
                    if not activity.title:
                        activity.title = '未命名草稿'
                    if not activity.location:
                        activity.location = '待定'
                elif not activity.title or not activity.description or not activity.location:
                    flash('标题、活动描述、活动地点不能为空（不支持HTML脚本内容）', 'warning')
                    return render_template('admin/activity_form.html', form=form, title='编辑活动', activity=activity, existing_documents=_load_activity_documents(), document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)

                if activity.registration_mode not in ('individual', 'team'):
                    activity.registration_mode = 'individual'
                if activity.registration_mode == 'individual':
                    activity.team_max_members = 1
                    activity.team_max_count = 0
                else:
                    activity.team_max_members = max(1, int(activity.team_max_members or 1))
                    activity.team_max_count = max(0, int(activity.team_max_count or 0))
                
                # 使用转换后的时间覆盖填充的时间字段
                activity.start_time = start_time
                activity.end_time = end_time
                activity.registration_start_time = registration_start_time
                activity.registration_deadline = registration_deadline
                
                # 恢复保存的值
                activity.checkin_enabled = checkin_enabled
                activity.checkin_key = checkin_key
                activity.checkin_key_expires = checkin_key_expires
                
                # 恢复创建者ID
                activity.created_by = created_by_id
                
                # 恢复poster数据以便后续处理
                form.poster.data = poster_data
                
                # 处理标签 - 使用更直接的方式处理标签关系
                try:
                    # 将选中的标签ID转换为整数
                    new_tag_ids = []
                    for tag_id_str in selected_tag_ids:
                        try:
                            tag_id = int(tag_id_str.strip())
                            new_tag_ids.append(tag_id)
                        except (ValueError, TypeError) as e:
                            logger.warning(f"无效的标签ID: {tag_id_str}, 错误: {e}")
                    
                    logger.info(f"新选中的标签IDs: {new_tag_ids}")
                    
                    # 直接查询所有需要的标签对象
                    if new_tag_ids:
                        # 一次性查询所有标签
                        tags = db.session.execute(
                            db.select(Tag).filter(Tag.id.in_(new_tag_ids))
                        ).scalars().all()
                        
                        # 创建ID到标签对象的映射
                        tag_map = {tag.id: tag for tag in tags}
                        logger.info(f"找到{len(tags)}个标签对象")
                        
                        # 完全重置标签关系
                        # 先获取当前关联的所有标签
                        current_tags = list(activity.tags)
                        
                        # 移除所有当前标签
                        for tag in current_tags:
                            activity.tags.remove(tag)
                        
                        logger.info("已移除所有现有标签")
                        
                        # 添加新标签
                        for tag_id in new_tag_ids:
                            if tag_id in tag_map:
                                activity.tags.append(tag_map[tag_id])
                                logger.info(f"添加标签: {tag_id}")
                            else:
                                logger.warning(f"找不到标签ID: {tag_id}")
                    else:
                        # 如果没有选择标签，则移除所有标签
                        current_tags = list(activity.tags)
                        for tag in current_tags:
                            activity.tags.remove(tag)
                        logger.info("没有选择标签，已移除所有现有标签")
                    
                    logger.info(f"标签处理完成，共添加{len(activity.tags)}个标签")
                
                except Exception as e:
                    logger.error(f"处理标签时出错: {e}", exc_info=True)
                    flash('处理活动标签时出错，其他信息已尝试保存', 'warning')

                # 保存已有资料的标题/类型/公开状态
                existing_docs = db.session.execute(
                    db.select(ActivityDocument).filter(ActivityDocument.activity_id == activity.id)
                ).scalars().all()
                for doc in existing_docs:
                    new_title = sanitize_plain_text(request.form.get(f'doc_title_{doc.id}', doc.title), max_length=128)
                    new_category = (request.form.get(f'doc_category_{doc.id}', doc.category) or 'other').strip().lower()
                    doc.title = new_title or doc.title
                    doc.category = new_category if new_category in DOCUMENT_CATEGORY_LABELS else 'other'
                    doc.is_public = bool(request.form.get(f'doc_is_public_{doc.id}'))

                # 处理新增活动资料（仅支持PDF）
                upload_files = request.files.getlist('activity_documents')
                new_doc_category = (request.form.get('new_document_category') or 'certificate').strip().lower()
                new_doc_public = bool(request.form.get('new_document_is_public'))
                new_doc_prefix = request.form.get('new_document_title_prefix', '')

                # 解析前端按文件单独配置的元数据
                per_file_meta = {}
                raw_meta = request.form.get('activity_documents_meta', '')
                if raw_meta:
                    try:
                        meta_list = json.loads(raw_meta)
                        if isinstance(meta_list, list):
                            for item in meta_list:
                                if not isinstance(item, dict):
                                    continue
                                index_value = item.get('index')
                                if not isinstance(index_value, int):
                                    try:
                                        index_value = int(index_value)
                                    except Exception:
                                        continue
                                if index_value < 0:
                                    continue
                                per_file_meta[index_value] = {
                                    'title': item.get('title', ''),
                                    'category': item.get('category', ''),
                                    'is_public': item.get('is_public', False)
                                }
                    except Exception as e:
                        logger.warning(f"活动资料元数据解析失败，回退默认设置: {e}")

                new_docs = _save_activity_documents(
                    activity=activity,
                    files=upload_files,
                    category=new_doc_category,
                    is_public=new_doc_public,
                    title_prefix=new_doc_prefix,
                    per_file_meta=per_file_meta
                )
                if upload_files and not new_docs:
                    flash('未检测到可上传文件，或文件超过80MB，请检查格式与大小', 'warning')

                if new_docs:
                    _notify_students_for_new_documents(activity, new_docs)
                
                # 更新积分，确保重点活动有足够积分
                if activity.is_featured and (activity.points is None or activity.points < 20):
                    activity.points = 20
                
                # 处理上传的图片
                if form.poster.data and hasattr(form.poster.data, 'filename') and form.poster.data.filename:
                    try:
                        logger.info(f"编辑活动: 准备上传海报，活动ID={activity.id}, 文件名={form.poster.data.filename}")
                        
                        # 使用handle_poster_upload函数处理文件上传，确保传递活动ID（整数）而不是整个活动对象
                        poster_info = handle_poster_upload(form.poster.data, activity.id)
                        
                        if poster_info:
                            # 记录旧海报文件名，以便稍后删除
                            old_poster = activity.poster_image
                            
                            # 更新海报信息
                            activity.poster_image = poster_info['filename']
                            activity.poster_data = poster_info['data']
                            activity.poster_mimetype = poster_info['mimetype']
                            logger.info(f"编辑活动: 海报信息已更新: {poster_info['filename']}")
                            
                            # 尝试删除旧海报文件（如果存在且不是默认banner）
                            if old_poster and 'banner' not in old_poster:
                                try:
                                    old_poster_path = os.path.join(current_app.static_folder or 'src/static', 'uploads', 'posters', old_poster)
                                    if os.path.exists(old_poster_path):
                                        os.remove(old_poster_path)
                                        logger.info(f"编辑活动: 已删除旧海报文件: {old_poster_path}")
                                except Exception as e:
                                    logger.warning(f"编辑活动: 删除旧海报文件时出错: {e}")
                        else:
                            logger.error("编辑活动: 上传海报失败，未获得有效的文件信息")
                            flash('上传海报时出错，但其他活动信息已保存', 'warning')
                    except Exception as e:
                        logger.error(f"编辑活动: 上传海报时出错: {e}", exc_info=True)
                        flash('上传海报时出错，但其他活动信息已保存', 'warning')
                else:
                    ai_poster_url = (request.form.get('ai_poster_url') or '').strip()
                    if ai_poster_url:
                        try:
                            _attach_ai_poster_from_url(activity, ai_poster_url)
                            logger.info(f"编辑活动: AI海报已写入 activity_id={activity.id}")
                        except Exception as e:
                            logger.error(f"编辑活动: AI海报写入失败: {e}", exc_info=True)
                            flash('AI海报写入失败，已保留原海报', 'warning')
                
                # 记录更新时间，使用UTC时间
                activity.updated_at = datetime.now(pytz.utc)
                
                # 如果状态变为已完成，记录完成时间
                if activity.status == 'completed' and not activity.completed_at:
                    activity.completed_at = datetime.now(pytz.utc)
                
                # 提交前记录详细信息，帮助诊断问题
                logger.info(f"准备提交活动更新 - ID: {activity.id}, 标题: {activity.title}, 海报: {activity.poster_image}")
                logger.info(f"标签数量: {len(activity.tags)}")
                
                try:
                    db.session.commit()
                    _invalidate_home_page_caches()
                    logger.info("活动更新成功提交到数据库")
                    
                    # 记录日志
                    log_action('edit_activity', f'编辑活动: {activity.title}')

                    if new_docs:
                        flash(f'新增 {len(new_docs)} 份活动资料并已通知相关学生', 'success')
                    
                    flash('草稿已保存' if is_draft_save else '活动发布成功', 'success')
                    return redirect(url_for('admin.activities'))
                except Exception as e:
                    db.session.rollback()
                    logger.error(f"提交活动更新时出错: {e}", exc_info=True)
                    flash(f'保存活动时出错: {str(e)}', 'danger')
                    return render_template('admin/activity_form.html', form=form, title='编辑活动', activity=activity, existing_documents=_load_activity_documents(), document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)
            except Exception as e:
                db.session.rollback()
                logger.error(f"编辑活动时出错: {e}", exc_info=True)
                flash(f'编辑活动时出错: {str(e)}', 'danger')
                return render_template('admin/activity_form.html', form=form, title='编辑活动', activity=activity, existing_documents=_load_activity_documents(), document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)
        
        if request.method == 'POST' and not form.validate_on_submit() and not is_draft_save:
            _flash_form_errors(form)
            if _is_ajax_request():
                action = (request.form.get('submit_action') or request.form.get('action') or 'publish').strip().lower()
                action_text = '发布' if action == 'publish' else '保存'
                return jsonify({
                    'success': False,
                    'message': f'{action_text}失败，请修正表单后重试',
                    'errors': _collect_form_error_messages(form)
                }), 422

        return render_template('admin/activity_form.html', form=form, title='编辑活动', activity=activity, existing_documents=_load_activity_documents(), document_categories=DOCUMENT_CATEGORY_LABELS, display_datetime=display_datetime)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in edit_activity: {e}", exc_info=True)
        flash('编辑活动时出错', 'danger')
        return redirect(url_for('admin.activities'))


@admin_bp.route('/activity/<int:activity_id>/documents/<int:doc_id>/delete', methods=['POST'])
@admin_required
def delete_activity_document(activity_id, doc_id):
    activity = db.get_or_404(Activity, activity_id)
    if not _scope_guard_activity(activity):
        flash('您只能管理所属社团的活动资料', 'danger')
        return redirect(url_for('admin.activities'))

    doc = db.session.execute(
        db.select(ActivityDocument).filter(
            ActivityDocument.id == doc_id,
            ActivityDocument.activity_id == activity_id
        )
    ).scalar_one_or_none()

    if not doc:
        flash('资料不存在或已删除', 'warning')
        return redirect(url_for('admin.edit_activity', id=activity_id))

    file_path = _resolve_activity_document_file_path(doc)
    db.session.delete(doc)
    db.session.commit()

    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            logger.warning(f"删除活动资料文件失败: {file_path}, error={e}")

    flash('活动资料已删除', 'success')
    return redirect(url_for('admin.edit_activity', id=activity_id))


@admin_bp.route('/activity/<int:activity_id>/documents/<int:doc_id>/download')
@admin_required
@limiter.limit('60 per minute')
def download_activity_document_admin(activity_id, doc_id):
    activity = db.get_or_404(Activity, activity_id)
    if not _scope_guard_activity(activity):
        flash('您只能下载所属社团的活动资料', 'danger')
        return redirect(url_for('admin.activities'))

    doc = db.session.execute(
        db.select(ActivityDocument).filter(
            ActivityDocument.id == doc_id,
            ActivityDocument.activity_id == activity_id
        )
    ).scalar_one_or_none()
    if not doc:
        flash('资料不存在', 'warning')
        return redirect(url_for('admin.edit_activity', id=activity_id))

    resolved_path = _resolve_activity_document_file_path(doc)
    if not resolved_path:
        flash('资料文件不存在，可能已被清理', 'warning')
        return redirect(url_for('admin.edit_activity', id=activity_id))

    download_name = os.path.basename(str(doc.file_name or f'activity_{activity_id}_document')).replace('\x00', '').strip()
    if not download_name:
        download_name = f"activity_{activity_id}_document"

    response = send_file(
        resolved_path,
        mimetype=doc.mime_type or 'application/pdf',
        as_attachment=True,
        download_name=download_name,
        conditional=True
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'private, max-age=600, must-revalidate'
    response.headers['CDN-Cache-Control'] = 'no-store'
    response.headers['Pragma'] = 'private'
    response.headers['Vary'] = 'Accept-Encoding, Cookie, Authorization'
    return response

@admin_bp.route('/students')
@admin_required
def students():
    try:
        from src.utils import get_compatible_paginate

        per_page_options = [10, 20, 50, 100]
        requested_per_page = request.args.get('per_page', 20, type=int)
        per_page = requested_per_page if requested_per_page in per_page_options else 20

        jump_page = request.args.get('jump_page', type=int)
        page = jump_page if jump_page and jump_page > 0 else request.args.get('page', 1, type=int)
        page = page if page and page > 0 else 1

        search = (request.args.get('search', '') or '').strip()
        selected_society_id = request.args.get('society_id', type=int)
        scope_society_id = _current_scope_society_id()
        
        # 使用SQLAlchemy 2.0风格查询
        query = _apply_student_scope(db.select(StudentInfo).join(User, StudentInfo.user_id == User.id))
        
        if search:
            query = query.filter(
                db.or_(
                    StudentInfo.real_name.ilike(f'%{search}%'),
                    StudentInfo.student_id.ilike(f'%{search}%'),
                    StudentInfo.college.ilike(f'%{search}%'),
                    StudentInfo.major.ilike(f'%{search}%'),
                    User.username.ilike(f'%{search}%')
                )
            )

        if scope_society_id:
            selected_society_id = scope_society_id
        elif selected_society_id:
            query = query.filter(
                db.or_(
                    StudentInfo.society_id == selected_society_id,
                    StudentInfo.joined_societies.any(Society.id == selected_society_id)
                )
            )
        
        # 使用兼容性分页
        query = query.order_by(StudentInfo.id.desc())
        students = get_compatible_paginate(db, query, page=page, per_page=per_page, error_out=False)

        if students.pages > 0 and page > students.pages:
            page = students.pages
            students = get_compatible_paginate(db, query, page=page, per_page=per_page, error_out=False)
        
        # 确保所有学生记录都有qq和has_selected_tags字段的值，并标记是否为管理员
        for student in students.items:
            user = db.session.get(User, student.user_id)
            if not hasattr(student, 'qq'):
                student.qq = ''
            if not hasattr(student, 'has_selected_tags'):
                student.has_selected_tags = False
            student.is_admin = bool(user and user.role and (user.role.name or '').strip().lower() == 'admin')
        
        if scope_society_id:
            scope_society = db.session.get(Society, scope_society_id)
            societies = [scope_society] if scope_society else []
        else:
            societies = db.session.execute(
                db.select(Society).filter(Society.is_active == True).order_by(Society.name.asc())
            ).scalars().all()

        return render_template(
            'admin/students.html',
            students=students,
            search=search,
            societies=societies,
            selected_society_id=selected_society_id,
            per_page=per_page,
            per_page_options=per_page_options
        )
    except Exception as e:
        logger.error(f"Error in students: {e}")
        flash('加载学生列表时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/student/<int:id>/delete', methods=['POST'])
@admin_required
def delete_student(id):
    try:
        return_back = request.referrer or url_for('admin.students')
        user = db.get_or_404(User, id)
        user_role = (user.role.name or '').strip().lower() if user.role else ''
        if user_role != 'student':
            flash('只能删除学生账号', 'danger')
            return redirect(return_back)

        if not is_super_admin(current_user):
            student = user.student_info
            if not student:
                flash('该用户不是学生账号', 'warning')
                return redirect(return_back)
            if not _scope_guard_student(student):
                flash('您只能管理所属社团学生', 'danger')
                return redirect(return_back)

            changed = _remove_student_from_scope_society(student)
            db.session.commit()
            if changed:
                log_action('remove_student_from_society', f'将学生移出社团名单: user_id={user.id}, scope_society_id={_current_scope_society_id()}')
                flash('已将该学生移出当前社团名单（账号保留）', 'success')
            else:
                flash('该学生不在当前社团名单中，无需移除', 'info')
            return redirect(return_back)

        # 清理外键依赖，避免删除失败
        db.session.execute(db.text("UPDATE system_logs SET user_id = NULL WHERE user_id = :uid"), {'uid': user.id})
        db.session.execute(db.text("UPDATE announcements SET created_by = NULL WHERE created_by = :uid"), {'uid': user.id})

        # 显式清理与用户直接关联的数据
        NotificationRead.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        Notification.query.filter_by(created_by=user.id).delete(synchronize_session=False)
        Message.query.filter(or_(Message.sender_id == user.id, Message.receiver_id == user.id)).delete(synchronize_session=False)
        Registration.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        ActivityReview.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        ActivityCheckin.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        AIChatHistory.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        AIChatSession.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        AIUserPreferences.query.filter_by(user_id=user.id).delete(synchronize_session=False)

        if user.student_info:
            student_info_id = user.student_info.id
            db.session.execute(student_tags.delete().where(student_tags.c.student_id == student_info_id))
            PointsHistory.query.filter_by(student_id=student_info_id).delete(synchronize_session=False)
            StudentInfo.query.filter_by(user_id=user.id).delete(synchronize_session=False)

        db.session.delete(user)
        db.session.commit()

        log_action('delete_student', f'删除学生账号: {user.username}')
        flash('学生账号已成功删除', 'success')
        return redirect(return_back)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting student: {e}")
        flash('删除学生账号时出错', 'danger')
        return redirect(request.referrer or url_for('admin.students'))

@admin_bp.route('/student/<int:user_id>/promote-admin', methods=['POST'])
@admin_required
def promote_student_to_admin(user_id):
    if not is_super_admin(current_user):
        flash('仅总管理员可设置管理员账号', 'danger')
        return redirect(request.referrer or url_for('admin.students'))

    try:
        csrf_token = request.form.get('csrf_token', '')
        validate_csrf(csrf_token)
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(request.referrer or url_for('admin.students'))

    try:
        user = db.get_or_404(User, user_id)

        user_role = (user.role.name or '').strip().lower() if user.role else ''
        if user_role != 'student':
            flash('仅可将学生账号设置为管理员', 'warning')
            return redirect(request.referrer or url_for('admin.students'))

        admin_role = db.session.execute(
            db.select(Role).filter(func.lower(Role.name) == 'admin')
        ).scalar_one_or_none()
        if not admin_role:
            flash('系统角色异常：未找到管理员角色', 'danger')
            return redirect(request.referrer or url_for('admin.students'))

        user.role_id = admin_role.id
        selected_society_id = request.form.get('society_id', type=int)
        if selected_society_id:
            society = db.session.get(Society, selected_society_id)
            if society and society.is_active:
                user.managed_society_id = society.id
        db.session.commit()

        log_action('promote_student_to_admin', f'将用户 {user.username}(ID:{user.id}) 设置为管理员')
        if not user.managed_society_id:
            flash('已设置为管理员，但尚未绑定社团。该管理员首次进入管理端需先选择社团。', 'warning')
        else:
            flash('已成功将该学生设置为管理员并绑定社团', 'success')
        return redirect(request.referrer or url_for('admin.students'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error promoting student to admin: {e}")
        flash('设置管理员时出错', 'danger')
        return redirect(request.referrer or url_for('admin.students'))

@admin_bp.route('/student/<int:user_id>/demote-admin', methods=['POST'])
@admin_required
def demote_admin_to_student(user_id):
    if not is_super_admin(current_user):
        flash('仅总管理员可取消管理员身份', 'danger')
        return redirect(request.referrer or url_for('admin.students'))

    try:
        csrf_token = request.form.get('csrf_token', '')
        validate_csrf(csrf_token)
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(request.referrer or url_for('admin.students'))

    try:
        user = db.get_or_404(User, user_id)

        user_role = (user.role.name or '').strip().lower() if user.role else ''
        if user_role != 'admin':
            flash('仅可取消管理员账号的管理员身份', 'warning')
            return redirect(request.referrer or url_for('admin.students'))

        if user.id == current_user.id:
            flash('不能取消自己的管理员身份', 'warning')
            return redirect(request.referrer or url_for('admin.students'))

        admin_role = db.session.execute(
            db.select(Role).filter(func.lower(Role.name) == 'admin')
        ).scalar_one_or_none()
        student_role = db.session.execute(
            db.select(Role).filter(func.lower(Role.name) == 'student')
        ).scalar_one_or_none()

        if not admin_role or not student_role:
            flash('系统角色异常，请联系系统管理员', 'danger')
            return redirect(request.referrer or url_for('admin.students'))

        admin_count = db.session.execute(
            db.select(func.count()).select_from(User).filter(User.role_id == admin_role.id)
        ).scalar() or 0

        if admin_count <= 1:
            flash('系统至少需要保留一名管理员，无法继续操作', 'warning')
            return redirect(request.referrer or url_for('admin.students'))

        user.role_id = student_role.id
        user.managed_society_id = None
        user.is_super_admin = False
        db.session.commit()

        log_action('demote_admin_to_student', f'取消用户 {user.username}(ID:{user.id}) 的管理员身份')
        flash('已成功取消该用户管理员身份', 'success')
        return redirect(request.referrer or url_for('admin.students'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error demoting admin to student: {e}")
        flash('取消管理员身份时出错', 'danger')
        return redirect(request.referrer or url_for('admin.students'))

@admin_bp.route('/student/<int:user_id>')
@admin_required
def student_view(user_id):
    # 导入display_datetime函数
    from src.utils.time_helpers import display_datetime
    
    user = db.get_or_404(User, user_id)
    student = db.session.execute(db.select(StudentInfo).filter_by(user_id=user_id)).scalar_one_or_none()
    if not student:
        flash('未找到该学生的详细信息', 'warning')
        return redirect(url_for('admin.students'))
    if not _scope_guard_student(student):
        flash('您只能查看所属社团学生信息', 'danger')
        return redirect(url_for('admin.students'))
    
    # 使用SQLAlchemy 2.0风格查询
    points_stmt = db.select(PointsHistory).filter_by(student_id=student.id).order_by(PointsHistory.created_at.desc())
    points_history = db.session.execute(points_stmt).scalars().all()
    
    reg_stmt = db.select(Registration).filter_by(user_id=user.id).options(joinedload(Registration.activity))
    registrations = db.session.execute(reg_stmt).scalars().all()
    
    # 获取学生的标签
    selected_tag_ids = [tag.id for tag in student.tags] if student.tags else []
    
    # 获取所有标签
    tags_stmt = db.select(Tag)
    all_tags = db.session.execute(tags_stmt).scalars().all()
    all_societies = db.session.execute(db.select(Society).filter_by(is_active=True).order_by(Society.name.asc())).scalars().all()
    selected_society_ids = [s.id for s in (student.joined_societies or [])]
    if student.society_id and student.society_id not in selected_society_ids:
        selected_society_ids.append(student.society_id)

    # 学生详情页注册时间展示：兼容历史北京时间 naive 数据，避免重复 +8h
    created_at_display = _format_review_time_for_display(user.created_at)
    return render_template('admin/student_view.html', student=student, user=user, 
                           points_history=points_history, registrations=registrations,
                           selected_tag_ids=selected_tag_ids, all_tags=all_tags,
                           all_societies=all_societies, selected_society_ids=selected_society_ids,
                           display_datetime=display_datetime,
                           created_at_display=created_at_display)

@admin_bp.route('/student/<int:user_id>/edit-profile', methods=['POST'])
@admin_required
def edit_student_profile(user_id):
    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(url_for('admin.student_view', user_id=user_id))

    user = db.get_or_404(User, user_id)
    student = db.session.execute(db.select(StudentInfo).filter_by(user_id=user_id)).scalar_one_or_none()
    if not student:
        flash('未找到该学生资料', 'warning')
        return redirect(url_for('admin.students'))
    if not _scope_guard_student(student):
        flash('您只能修改所属社团学生信息', 'danger')
        return redirect(url_for('admin.students'))

    try:
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        real_name = (request.form.get('real_name') or '').strip()
        student_id = (request.form.get('student_id') or '').strip()
        grade = (request.form.get('grade') or '').strip()
        college = (request.form.get('college') or '').strip()
        major = (request.form.get('major') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        qq = (request.form.get('qq') or '').strip()
        selected_society_ids = [int(sid) for sid in request.form.getlist('societies') if sid and str(sid).isdigit()]

        if not username:
            flash('用户名不能为空', 'warning')
            return redirect(url_for('admin.student_view', user_id=user_id))
        if not real_name:
            flash('姓名不能为空', 'warning')
            return redirect(url_for('admin.student_view', user_id=user_id))
        if not student_id:
            flash('学号不能为空', 'warning')
            return redirect(url_for('admin.student_view', user_id=user_id))

        username_exists = db.session.execute(
            db.select(User).filter(User.username == username, User.id != user.id)
        ).scalar_one_or_none()
        if username_exists:
            flash('用户名已存在，请换一个', 'warning')
            return redirect(url_for('admin.student_view', user_id=user_id))

        if email:
            email_exists = db.session.execute(
                db.select(User).filter(User.email == email, User.id != user.id)
            ).scalar_one_or_none()
            if email_exists:
                flash('邮箱已被占用，请更换', 'warning')
                return redirect(url_for('admin.student_view', user_id=user_id))

        student_id_exists = db.session.execute(
            db.select(StudentInfo).filter(StudentInfo.student_id == student_id, StudentInfo.user_id != user.id)
        ).scalar_one_or_none()
        if student_id_exists:
            flash('学号已存在，请检查后重试', 'warning')
            return redirect(url_for('admin.student_view', user_id=user_id))

        if phone:
            phone_exists = db.session.execute(
                db.select(StudentInfo).filter(StudentInfo.phone == phone, StudentInfo.user_id != user.id)
            ).scalar_one_or_none()
            if phone_exists:
                flash('手机号已被占用，请更换', 'warning')
                return redirect(url_for('admin.student_view', user_id=user_id))

        user.username = username
        user.email = email or None

        student.real_name = real_name
        student.student_id = student_id
        student.grade = grade
        student.college = college
        student.major = major
        student.phone = phone
        student.qq = qq

        # 仅总管理员可修改学生社团归属，且直接生效（后台操作不走邮箱验证流程）
        if is_super_admin(current_user):
            selected_societies = db.session.execute(
                db.select(Society).filter(Society.id.in_(selected_society_ids), Society.is_active == True)
            ).scalars().all() if selected_society_ids else []
            student.joined_societies = selected_societies
            if selected_societies:
                selected_id_set = {s.id for s in selected_societies}
                if student.society_id not in selected_id_set:
                    student.society_id = selected_societies[0].id
            else:
                student.society_id = None

        db.session.commit()
        log_action('edit_student_profile', f'管理员编辑学生资料: user_id={user.id}, student_id={student.student_id}')
        flash('学生资料已更新', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"编辑学生资料失败 user_id={user_id}: {e}", exc_info=True)
        flash('更新学生资料时出错', 'danger')

    return redirect(url_for('admin.student_view', user_id=user_id))

@admin_bp.route('/student/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_student_password(user_id):
    flash('管理员手动生成重置链接功能已停用，请引导用户在登录页使用“忘记密码”通过邮箱重置。', 'info')
    return redirect(url_for('admin.student_view', user_id=user_id))

@admin_bp.route('/student/<int:id>/update-tags', methods=['POST'])
@admin_required
def update_student_tags(id):
    student = db.get_or_404(StudentInfo, id)
    
    try:
        # 获取提交的标签ID
        tag_ids = request.form.getlist('tags')
        selected_society_ids = [int(sid) for sid in request.form.getlist('societies') if sid and str(sid).isdigit()]
        
        # 清除原有标签关联
        student.tags = []
        
        # 添加新的标签关联
        for tag_id in tag_ids:
            tag_stmt = db.select(Tag).filter_by(id=int(tag_id))
            tag = db.session.execute(tag_stmt).scalar_one_or_none()
            if tag:
                student.tags.append(tag)
        
        # 更新学生标签选择状态
        if hasattr(student, 'has_selected_tags'):
            student.has_selected_tags = True if tag_ids else False

        if is_super_admin(current_user):
            selected_societies = db.session.execute(
                db.select(Society).filter(Society.id.in_(selected_society_ids), Society.is_active == True)
            ).scalars().all() if selected_society_ids else []
            student.joined_societies = selected_societies
            if selected_societies:
                selected_id_set = {s.id for s in selected_societies}
                if student.society_id not in selected_id_set:
                    student.society_id = selected_societies[0].id
            else:
                student.society_id = None

        db.session.commit()
        
        flash('学生标签信息更新成功！', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"更新学生标签时出错: {e}")
        flash('更新学生标签时出错', 'danger')
    
    return redirect(url_for('admin.student_view', user_id=student.user_id))

@admin_bp.route('/student/<int:id>/adjust_points', methods=['POST'])
@admin_required
def adjust_student_points(id):
    try:
        student_info = db.get_or_404(StudentInfo, id)
        if not _scope_guard_student(student_info):
            flash('您只能调整所属社团学生积分', 'danger')
            return redirect(url_for('admin.students'))
        points = request.form.get('points', type=int)
        reason = request.form.get('reason', '').strip()
        
        if not points:
            flash('请输入有效的积分值', 'warning')
            return redirect(url_for('admin.student_view', user_id=student_info.user_id))
        
        if not reason:
            flash('请输入积分调整原因', 'warning')
            return redirect(url_for('admin.student_view', user_id=student_info.user_id))
        
        # 更新学生积分
        student_info.points = (student_info.points or 0) + points
        
        scope_society_id = _current_scope_society_id()

        # 创建积分历史记录
        points_history = PointsHistory(
            student_id=id,
            points=points,
            reason=f"管理员调整: {reason}",
            activity_id=None,
            society_id=scope_society_id or student_info.society_id
        )
        
        db.session.add(points_history)
        db.session.commit()
        
        log_action('adjust_points', f'调整学生 {student_info.real_name} (ID: {id}) 的积分: {points}分, 原因: {reason}')
        flash(f'积分调整成功，当前积分: {student_info.points}', 'success')
        
        return redirect(url_for('admin.student_view', user_id=student_info.user_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in adjust_student_points: {e}")
        flash('调整积分时出错', 'danger')
        return redirect(url_for('admin.student_view', user_id=student_info.user_id))

@admin_bp.route('/statistics')
@admin_required
def statistics():
    try:
        # 获取当前时间
        now = get_localized_now()
        
        # 获取最近7天的日期范围
        end_date = now
        start_date = end_date - timedelta(days=6)
        
        # 确保时间是规范化的
        start_date = normalize_datetime_for_db(start_date)
        end_date = normalize_datetime_for_db(end_date)
        
        scope_id = _current_scope_society_id()

        # 获取最近7天的活动数据
        daily_activities_stmt = db.select(
            func.date(Activity.created_at).label('date'),
            func.count(Activity.id).label('count')
        ).filter(
            Activity.created_at.between(start_date, end_date)
        ).group_by(
            func.date(Activity.created_at)
        )
        if scope_id:
            daily_activities_stmt = daily_activities_stmt.filter(Activity.society_id == scope_id)
        daily_activities = db.session.execute(daily_activities_stmt).all()
        
        # 获取最近7天的注册数据
        daily_registrations_stmt = db.select(
            func.date(Registration.register_time).label('date'),
            func.count(Registration.id).label('count')
        ).filter(
            Registration.register_time.between(start_date, end_date)
        )
        if scope_id:
            daily_registrations_stmt = daily_registrations_stmt.join(Activity, Registration.activity_id == Activity.id).filter(Activity.society_id == scope_id)
        daily_registrations_stmt = daily_registrations_stmt.group_by(
            func.date(Registration.register_time)
        )
        daily_registrations = db.session.execute(daily_registrations_stmt).all()
        
        # 获取最近7天的用户注册数据
        daily_users_stmt = db.select(
            func.date(User.created_at).label('date'),
            func.count(User.id).label('count')
        ).join(StudentInfo, StudentInfo.user_id == User.id).filter(
            User.created_at.between(start_date, end_date)
        )
        if scope_id:
            daily_users_stmt = daily_users_stmt.filter(
                or_(
                    StudentInfo.society_id == scope_id,
                    StudentInfo.joined_societies.any(Society.id == scope_id)
                )
            )
        daily_users_stmt = daily_users_stmt.group_by(
            func.date(User.created_at)
        )
        daily_users = db.session.execute(daily_users_stmt).all()
        
        # 将查询结果转换为字典格式，方便前端使用
        date_format = '%Y-%m-%d'
        
        # 创建包含所有日期的字典
        date_range = [(start_date + timedelta(days=i)).strftime(date_format) for i in range(7)]
        
        activities_data = {date: 0 for date in date_range}
        for item in daily_activities:
            date_str = item.date.strftime(date_format) if hasattr(item.date, 'strftime') else str(item.date)
            activities_data[date_str] = item.count
            
        registrations_data = {date: 0 for date in date_range}
        for item in daily_registrations:
            date_str = item.date.strftime(date_format) if hasattr(item.date, 'strftime') else str(item.date)
            registrations_data[date_str] = item.count
            
        users_data = {date: 0 for date in date_range}
        for item in daily_users:
            date_str = item.date.strftime(date_format) if hasattr(item.date, 'strftime') else str(item.date)
            users_data[date_str] = item.count
        
        # 准备图表数据
        chart_data = {
            'labels': date_range,
            'activities': [activities_data[date] for date in date_range],
            'registrations': [registrations_data[date] for date in date_range],
            'users': [users_data[date] for date in date_range]
        }
        
        # 获取活动类型分布
        activity_types_stmt = db.select(
            Activity.type,
            func.count(Activity.id).label('count')
        ).group_by(Activity.type)
        if scope_id:
            activity_types_stmt = activity_types_stmt.filter(Activity.society_id == scope_id)
        activity_types = db.session.execute(activity_types_stmt).all()
        
        # 转换为前端可用的格式
        type_labels = [t.type for t in activity_types]
        type_data = [t.count for t in activity_types]
        
        # 获取标签统计
        try:
            tag_stats_stmt = db.select(
                Tag.name,
                func.count(Activity.id).label('count')
            ).join(
                activity_tags, Tag.id == activity_tags.c.tag_id
            ).join(
                Activity, Activity.id == activity_tags.c.activity_id
            ).group_by(Tag.name).order_by(desc('count')).limit(10)
            if scope_id:
                tag_stats_stmt = tag_stats_stmt.filter(Activity.society_id == scope_id)
            
            tag_stats = db.session.execute(tag_stats_stmt).all()
            
            # 转换为前端可用的格式
            tag_labels = [t.name for t in tag_stats]
            tag_data = [t.count for t in tag_stats]
        except Exception as e:
            logger.error(f"获取标签统计失败: {e}")
            tag_labels = []
            tag_data = []
        
        return render_template(
            'admin/statistics.html',
            chart_data=chart_data,
            type_labels=type_labels,
            type_data=type_data,
            tag_labels=tag_labels,
            tag_data=tag_data,
            scope_label=_scope_display_label()
        )
    except Exception as e:
        logger.error(f"Error in statistics: {e}")
        flash('加载统计数据时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/api/statistics')
@admin_bp.route('/admin/api/statistics')  # 添加一个包含admin前缀的路由
@admin_required
def api_statistics():
    try:
        scope_id = _current_scope_society_id()

        # 活动状态统计
        active_count_stmt = db.select(func.count()).select_from(Activity).filter_by(status='active')
        if scope_id:
            active_count_stmt = active_count_stmt.filter(Activity.society_id == scope_id)
        active_count = db.session.execute(active_count_stmt).scalar()
        
        completed_count_stmt = db.select(func.count()).select_from(Activity).filter_by(status='completed')
        if scope_id:
            completed_count_stmt = completed_count_stmt.filter(Activity.society_id == scope_id)
        completed_count = db.session.execute(completed_count_stmt).scalar()
        
        cancelled_count_stmt = db.select(func.count()).select_from(Activity).filter_by(status='cancelled')
        if scope_id:
            cancelled_count_stmt = cancelled_count_stmt.filter(Activity.society_id == scope_id)
        cancelled_count = db.session.execute(cancelled_count_stmt).scalar()
        
        registration_stats = {
            'labels': ['进行中', '已结束', '已取消'],
            'data': [active_count, completed_count, cancelled_count]
        }
        
        # 学生参与度统计
        student_role_stmt = db.select(Role.id).filter_by(name='Student')
        student_role_id = db.session.execute(student_role_stmt).scalar()
        
        total_students_stmt = db.select(func.count()).select_from(User).join(StudentInfo, StudentInfo.user_id == User.id).filter(User.role_id == student_role_id)
        if scope_id:
            total_students_stmt = total_students_stmt.filter(
                or_(
                    StudentInfo.society_id == scope_id,
                    StudentInfo.joined_societies.any(Society.id == scope_id)
                )
            )
        total_students = db.session.execute(total_students_stmt).scalar()
        
        active_students_stmt = db.select(func.count(Registration.user_id.distinct())).select_from(Registration)
        if scope_id:
            active_students_stmt = active_students_stmt.join(Activity, Registration.activity_id == Activity.id).filter(Activity.society_id == scope_id)
        active_students = db.session.execute(active_students_stmt).scalar()
        
        inactive_students = total_students - active_students if total_students > active_students else 0
        
        participation_stats = {
            'labels': ['已参与活动', '未参与活动'],
            'data': [active_students, inactive_students]
        }
        
        # 月度活动和报名统计
        months = []
        activities_count = []
        registrations_count = []
        
        for i in range(5, -1, -1):
            # 获取过去6个月的数据
            current_month = normalize_datetime_for_db(datetime.now()).replace(day=1) - timedelta(days=i*30)
            month_start = current_month.replace(day=1)
            if current_month.month == 12:
                month_end = current_month.replace(year=current_month.year+1, month=1, day=1)
            else:
                month_end = current_month.replace(month=current_month.month+1, day=1)
            
            # 月份标签
            month_label = current_month.strftime('%Y-%m')
            months.append(month_label)
            
            # 活动数量
            monthly_activities_stmt = db.select(func.count()).select_from(Activity).filter(
                Activity.created_at.between(month_start, month_end)
            )
            if scope_id:
                monthly_activities_stmt = monthly_activities_stmt.filter(Activity.society_id == scope_id)
            monthly_activities = db.session.execute(monthly_activities_stmt).scalar() or 0
            activities_count.append(monthly_activities)
            
            # 报名数量
            monthly_registrations_stmt = db.select(func.count()).select_from(Registration).filter(
                Registration.register_time.between(month_start, month_end)
            )
            if scope_id:
                monthly_registrations_stmt = monthly_registrations_stmt.join(Activity, Registration.activity_id == Activity.id).filter(Activity.society_id == scope_id)
            monthly_registrations = db.session.execute(monthly_registrations_stmt).scalar() or 0
            registrations_count.append(monthly_registrations)
        
        monthly_stats = {
            'labels': months,
            'activities': activities_count,
            'registrations': registrations_count
        }
        
        return jsonify({
            'registration_stats': registration_stats,
            'participation_stats': participation_stats,
            'monthly_stats': monthly_stats
        })
    except Exception as e:
        logger.error(f"Error in api_statistics: {e}")
        return jsonify({'error': '获取统计数据失败'}), 500

@admin_bp.route('/activity/<int:id>/registrations')
@admin_required
def activity_registrations(id):
    try:
        # 导入display_datetime函数供模板使用
        from src.utils.time_helpers import display_datetime
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能管理所属社团活动', 'danger')
            return redirect(url_for('admin.activities'))
        
        # 获取报名学生列表 - 修复报名详情查看问题
        # 使用SQLAlchemy查询，确保包含registration_id
        registrations = Registration.query.filter_by(
            activity_id=id
        ).join(
            User, Registration.user_id == User.id
        ).join(
            StudentInfo, User.id == StudentInfo.user_id
        ).outerjoin(
            ActivityTeam, Registration.team_id == ActivityTeam.id
        ).add_columns(
            Registration.id.label('registration_id'),
            Registration.user_id,
            Registration.register_time,
            Registration.check_in_time,
            Registration.status,
            Registration.remark,
            Registration.team_id,
            ActivityTeam.name.label('team_name'),
            ActivityTeam.team_code.label('team_code'),
            ActivityTeam.leader_user_id,
            StudentInfo.real_name,
            StudentInfo.student_id,
            StudentInfo.grade,
            StudentInfo.college,
            StudentInfo.major,
            StudentInfo.phone,
            StudentInfo.points
        ).all()

        team_rows = db.session.execute(
            db.select(
                ActivityTeam.id,
                ActivityTeam.name,
                ActivityTeam.team_code,
                ActivityTeam.join_token,
                ActivityTeam.leader_user_id,
                ActivityTeam.created_at,
                func.count(Registration.id).label('member_count'),
                User.username.label('leader_username'),
                StudentInfo.real_name.label('leader_real_name')
            )
            .filter(ActivityTeam.activity_id == id)
            .outerjoin(
                Registration,
                and_(
                    Registration.team_id == ActivityTeam.id,
                    Registration.status.in_(['registered', 'attended'])
                )
            )
            .outerjoin(User, User.id == ActivityTeam.leader_user_id)
            .outerjoin(StudentInfo, StudentInfo.user_id == ActivityTeam.leader_user_id)
            .group_by(
                ActivityTeam.id,
                ActivityTeam.name,
                ActivityTeam.team_code,
                ActivityTeam.join_token,
                ActivityTeam.leader_user_id,
                ActivityTeam.created_at,
                User.username,
                StudentInfo.real_name
            )
            .order_by(ActivityTeam.created_at.asc())
        ).all()

        team_ids = [row.id for row in team_rows]
        team_members_map = {team_id: [] for team_id in team_ids}
        if team_ids:
            member_rows = db.session.execute(
                db.select(
                    Registration.id.label('registration_id'),
                    Registration.team_id,
                    Registration.user_id,
                    Registration.status,
                    Registration.register_time,
                    StudentInfo.real_name,
                    StudentInfo.student_id,
                    User.username
                )
                .join(User, Registration.user_id == User.id)
                .join(StudentInfo, StudentInfo.user_id == User.id)
                .filter(
                    Registration.activity_id == id,
                    Registration.team_id.in_(team_ids),
                    Registration.status.in_(['registered', 'attended'])
                )
                .order_by(Registration.register_time.asc())
            ).all()
            for member in member_rows:
                team_members_map.setdefault(member.team_id, []).append(member)

        team_cards = []
        for row in team_rows:
            members = team_members_map.get(row.id, [])
            team_cards.append({
                'id': row.id,
                'name': row.name,
                'team_code': row.team_code,
                'join_token': row.join_token,
                'leader_user_id': row.leader_user_id,
                'leader_name': row.leader_real_name or row.leader_username or f'用户{row.leader_user_id}',
                'member_count': int(row.member_count or 0),
                'created_at': row.created_at,
                'members': members,
            })
        
        # 统计报名状态
        registered_count = db.session.execute(db.select(func.count()).select_from(Registration).filter_by(activity_id=id, status='registered')).scalar()
        cancelled_count = db.session.execute(db.select(func.count()).select_from(Registration).filter_by(activity_id=id, status='cancelled')).scalar()
        attended_count = db.session.execute(db.select(func.count()).select_from(Registration).filter_by(activity_id=id, status='attended')).scalar()
        
        # 修复签到状态统计 - 确保报名统计准确性
        # 这里处理签到后的状态计数，让前端能正确显示
        
        # 创建CSRF表单对象
        from flask_wtf import FlaskForm
        form = FlaskForm()
        
        return render_template('admin/activity_registrations.html',
                              activity=activity,
                              registrations=registrations,
                              team_cards=team_cards,
                              registered_count=registered_count,
                              cancelled_count=cancelled_count,
                              attended_count=attended_count,
                              display_datetime=display_datetime,
                              form=form)
    except Exception as e:
        logger.error(f"Error in activity_registrations: {e}")
        flash('查看报名情况时出错', 'danger')
        return redirect(url_for('admin.activities'))

@admin_bp.route('/activity/<int:id>/export_excel')
@admin_required
def export_activity_registrations(id):
    try:
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能导出所属社团活动报名', 'danger')
            return redirect(url_for('admin.activities'))
        is_team_mode = (getattr(activity, 'registration_mode', 'individual') or 'individual') == 'team'
        
        # 获取报名学生列表
        registrations = Registration.query.filter_by(
            activity_id=id
        ).join(
            User, Registration.user_id == User.id
        ).join(
            StudentInfo, User.id == StudentInfo.user_id
        ).outerjoin(
            ActivityTeam, Registration.team_id == ActivityTeam.id
        ).add_columns(
            Registration.id.label('registration_id'),
            Registration.user_id,
            Registration.register_time,
            Registration.check_in_time,
            Registration.status,
            Registration.remark,
            Registration.team_id,
            ActivityTeam.name.label('team_name'),
            ActivityTeam.team_code.label('team_code'),
            ActivityTeam.leader_user_id,
            StudentInfo.real_name,
            StudentInfo.student_id,
            StudentInfo.grade,
            StudentInfo.college,
            StudentInfo.major,
            StudentInfo.phone,
            StudentInfo.points
        ).all()

        # 以队伍为单位排序：先队伍，再队员；无队伍记录放在最后
        registrations = sorted(
            registrations,
            key=lambda reg: (
                1 if not reg.team_id else 0,
                str(reg.team_name or ''),
                str(reg.team_code or ''),
                reg.register_time or datetime.min,
                str(reg.real_name or ''),
                str(reg.student_id or '')
            )
        )
        
        # 创建Excel文件
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl')
        
        # 转换为DataFrame
        data = []
        for reg in registrations:
            # 将UTC时间转换为北京时间
            register_time_bj = localize_time(reg.register_time)
            check_in_time_bj = localize_time(reg.check_in_time) if reg.check_in_time else None
            remark_text = (reg.remark or '').strip()
            if reg.team_id and reg.leader_user_id and reg.user_id == reg.leader_user_id:
                remark_text = f"{remark_text}；队长" if remark_text else '队长'
            
            row = {
                '报名ID': reg.registration_id,
                '姓名': reg.real_name,
                '学号': reg.student_id,
                '年级': reg.grade,
                '学院': reg.college,
                '专业': reg.major,
                '手机号': reg.phone,
                '报名时间': register_time_bj.strftime('%Y-%m-%d %H:%M:%S') if register_time_bj else '',
                '状态': '已报名' if reg.status == 'registered' else '已取消' if reg.status == 'cancelled' else '已参加',
                '积分': reg.points or 0,
                '备注': remark_text,
                '签到状态': '已签到' if reg.check_in_time else '未签到',
                '签到时间': check_in_time_bj.strftime('%Y-%m-%d %H:%M:%S') if check_in_time_bj else ''
            }
            if is_team_mode:
                row['队伍名称'] = reg.team_name or ''
                row['团队码'] = reg.team_code or ''
            data.append(row)
        
        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name='报名信息', index=False)
        
        # 保存Excel
        writer.close()
        output.seek(0)
        
        # 记录操作日志
        log_action('export_registrations', f'导出活动({activity.title})的报名信息')
        
        # 使用北京时间作为文件名
        beijing_now = get_localized_now()
        
        # 返回Excel文件
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{activity.title}_报名信息_{beijing_now.strftime('%Y%m%d%H%M%S')}.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(f"Error exporting activity registrations: {e}")
        flash('导出报名信息时出错', 'danger')
        return redirect(url_for('admin.activity_registrations', id=id))


@admin_bp.route('/activity/<int:activity_id>/team/<int:team_id>/rename', methods=['POST'])
@admin_required
def rename_activity_team(activity_id, team_id):
    activity = db.get_or_404(Activity, activity_id)
    if not _scope_guard_activity(activity):
        flash('您只能管理所属社团活动队伍', 'danger')
        return redirect(url_for('admin.activities'))

    team = db.session.execute(
        db.select(ActivityTeam).filter(
            ActivityTeam.id == team_id,
            ActivityTeam.activity_id == activity_id
        )
    ).scalar_one_or_none()
    if not team:
        flash('队伍不存在', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    new_name = sanitize_plain_text(request.form.get('team_name', ''), max_length=120)
    if not new_name:
        flash('队伍名称不能为空', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    team.name = new_name
    db.session.commit()
    log_action('rename_activity_team', f'活动{activity_id} 队伍{team_id}重命名为 {new_name}')
    flash('队伍名称已更新', 'success')
    return redirect(url_for('admin.activity_registrations', id=activity_id))


@admin_bp.route('/activity/<int:activity_id>/team/<int:team_id>/transfer_leader', methods=['POST'])
@admin_required
def transfer_activity_team_leader(activity_id, team_id):
    activity = db.get_or_404(Activity, activity_id)
    if not _scope_guard_activity(activity):
        flash('您只能管理所属社团活动队伍', 'danger')
        return redirect(url_for('admin.activities'))

    team = db.session.execute(
        db.select(ActivityTeam).filter(
            ActivityTeam.id == team_id,
            ActivityTeam.activity_id == activity_id
        )
    ).scalar_one_or_none()
    if not team:
        flash('队伍不存在', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    target_registration_id = request.form.get('leader_registration_id', type=int)
    if not target_registration_id:
        flash('请选择新队长', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    target_registration = db.session.execute(
        db.select(Registration).filter(
            Registration.id == target_registration_id,
            Registration.activity_id == activity_id,
            Registration.team_id == team_id,
            Registration.status.in_(['registered', 'attended'])
        )
    ).scalar_one_or_none()

    if not target_registration:
        flash('新队长必须是该队当前有效成员', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    team.leader_user_id = target_registration.user_id
    db.session.commit()
    log_action('transfer_activity_team_leader', f'活动{activity_id} 队伍{team_id}转移队长为用户{target_registration.user_id}')
    flash('队长已转移', 'success')
    return redirect(url_for('admin.activity_registrations', id=activity_id))


@admin_bp.route('/activity/<int:activity_id>/team/<int:team_id>/remove_member', methods=['POST'])
@admin_required
def remove_activity_team_member(activity_id, team_id):
    activity = db.get_or_404(Activity, activity_id)
    if not _scope_guard_activity(activity):
        flash('您只能管理所属社团活动队伍', 'danger')
        return redirect(url_for('admin.activities'))

    team = db.session.execute(
        db.select(ActivityTeam).filter(
            ActivityTeam.id == team_id,
            ActivityTeam.activity_id == activity_id
        )
    ).scalar_one_or_none()
    if not team:
        flash('队伍不存在', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    registration_id = request.form.get('registration_id', type=int)
    member_registration = db.session.execute(
        db.select(Registration).filter(
            Registration.id == registration_id,
            Registration.activity_id == activity_id,
            Registration.team_id == team_id,
            Registration.status.in_(['registered', 'attended'])
        )
    ).scalar_one_or_none()
    if not member_registration:
        flash('成员不存在或状态无效', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    if member_registration.user_id == team.leader_user_id:
        next_leader = db.session.execute(
            db.select(Registration).filter(
                Registration.activity_id == activity_id,
                Registration.team_id == team_id,
                Registration.status.in_(['registered', 'attended']),
                Registration.user_id != team.leader_user_id
            ).order_by(Registration.register_time.asc())
        ).scalar_one_or_none()
        if not next_leader:
            flash('该队仅剩队长本人，请直接解散队伍', 'warning')
            return redirect(url_for('admin.activity_registrations', id=activity_id))
        team.leader_user_id = next_leader.user_id

    member_registration.team_id = None
    db.session.commit()
    log_action('remove_activity_team_member', f'活动{activity_id} 从队伍{team_id}移除报名{registration_id}')
    flash('已移除成员，成员仍保留活动报名状态', 'success')
    return redirect(url_for('admin.activity_registrations', id=activity_id))


@admin_bp.route('/activity/<int:activity_id>/team/<int:team_id>/disband', methods=['POST'])
@admin_required
def disband_activity_team(activity_id, team_id):
    activity = db.get_or_404(Activity, activity_id)
    if not _scope_guard_activity(activity):
        flash('您只能管理所属社团活动队伍', 'danger')
        return redirect(url_for('admin.activities'))

    team = db.session.execute(
        db.select(ActivityTeam).filter(
            ActivityTeam.id == team_id,
            ActivityTeam.activity_id == activity_id
        )
    ).scalar_one_or_none()
    if not team:
        flash('队伍不存在', 'warning')
        return redirect(url_for('admin.activity_registrations', id=activity_id))

    member_regs = db.session.execute(
        db.select(Registration).filter(
            Registration.activity_id == activity_id,
            Registration.team_id == team_id
        )
    ).scalars().all()

    affected_count = 0
    for reg in member_regs:
        # 管理员解散队伍时，队员报名一并取消，避免“无队伍但仍占用名额”。
        reg.status = 'cancelled'
        reg.check_in_time = None
        reg.team_id = None
        affected_count += 1

    db.session.delete(team)
    db.session.commit()
    log_action('disband_activity_team', f'活动{activity_id} 解散队伍{team_id}，并取消{affected_count}名成员报名')
    flash(f'队伍已解散，并已取消 {affected_count} 名队员报名', 'success')
    return redirect(url_for('admin.activity_registrations', id=activity_id))

@admin_bp.route('/students/export_excel')
@admin_required
def export_students():
    try:
        # 获取所有学生信息
        students_query = User.query.join(Role).filter(Role.name == 'Student').join(
            StudentInfo, User.id == StudentInfo.user_id
        )
        if _current_scope_society_id():
            scope_id = _current_scope_society_id()
            students_query = students_query.filter(
                or_(
                    StudentInfo.society_id == scope_id,
                    StudentInfo.joined_societies.any(Society.id == scope_id)
                )
            )

        students = students_query.add_columns(
            User.id,
            User.username,
            User.email,
            User.created_at,
            StudentInfo.real_name,
            StudentInfo.student_id,
            StudentInfo.grade,
            StudentInfo.college,
            StudentInfo.major,
            StudentInfo.phone,
            StudentInfo.qq,
            StudentInfo.points
        ).all()
        
        # 创建Excel文件
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl')
        
        # 转换为DataFrame
        data = []
        for student in students:
            # 将UTC时间转换为北京时间
            beijing_created_at = localize_time(student.created_at)
            scoped_points = student.points or 0
            if _current_scope_society_id():
                scoped_points = db.session.execute(
                    db.select(func.coalesce(func.sum(PointsHistory.points), 0)).filter(
                        PointsHistory.student_id == student.id,
                        PointsHistory.society_id == _current_scope_society_id()
                    )
                ).scalar() or 0
            
            data.append({
                '用户ID': student.id,
                '用户名': student.username,
                '邮箱': student.email,
                '姓名': student.real_name,
                '学号': student.student_id,
                '年级': student.grade,
                '学院': student.college,
                '专业': student.major,
                '手机号': student.phone,
                'QQ': student.qq,
                '积分': scoped_points,
                '注册时间': beijing_created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        
        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name='学生信息', index=False)
        
        # 保存Excel
        writer.close()
        output.seek(0)
        
        # 记录操作日志
        log_action('export_students', '导出所有学生信息')
        
        # 使用北京时间作为文件名
        beijing_now = get_localized_now()
        
        # 返回Excel文件
        return send_file(
            output,
            as_attachment=True,
            download_name=f"学生信息_{beijing_now.strftime('%Y%m%d%H%M%S')}.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(f"Error exporting students: {e}")
        flash('导出学生信息时出错', 'danger')
        return redirect(url_for('admin.students'))


@admin_bp.route('/admins/export_excel')
@admin_required
def export_society_admins():
    if not is_super_admin(current_user):
        flash('仅总管理员可导出社团管理员信息', 'danger')
        return redirect(url_for('admin.students'))

    try:
        admin_role = db.session.execute(
            db.select(Role).filter(func.lower(Role.name) == 'admin')
        ).scalar_one_or_none()
        if not admin_role:
            flash('未找到管理员角色数据', 'warning')
            return redirect(url_for('admin.students'))

        admins = db.session.execute(
            db.select(User).filter(User.role_id == admin_role.id).order_by(User.id.asc())
        ).scalars().all()

        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='openpyxl')

        summary_rows = []
        activity_rows = []
        beijing_tz = pytz.timezone('Asia/Shanghai')

        def format_system_time_for_export(dt):
            """将系统时间字段统一格式化为北京时间字符串。"""
            if not dt:
                return ''
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt.astimezone(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')

        for admin_user in admins:
            managed_society = db.session.get(Society, admin_user.managed_society_id) if admin_user.managed_society_id else None

            created_activities = db.session.execute(
                db.select(Activity).filter(Activity.created_by == admin_user.id).order_by(Activity.created_at.desc())
            ).scalars().all()

            activity_names = [a.title for a in created_activities if getattr(a, 'title', None)]
            latest_activity_at = created_activities[0].created_at if created_activities else None

            summary_rows.append({
                '管理员用户ID': admin_user.id,
                '用户名': admin_user.username,
                '邮箱': admin_user.email,
                '是否总管理员': '是' if bool(getattr(admin_user, 'is_super_admin', False)) else '否',
                '账号状态': '启用' if bool(getattr(admin_user, 'active', False)) else '禁用',
                '管理社团ID': getattr(admin_user, 'managed_society_id', None) or '',
                '管理社团名称': managed_society.name if managed_society else '',
                '管理社团编码': managed_society.code if managed_society else '',
                '管理社团状态': ('启用' if managed_society and managed_society.is_active else ('停用' if managed_society else '未绑定')),
                '发布活动数量': len(created_activities),
                '最近发布活动时间': format_system_time_for_export(latest_activity_at),
                '发布活动名称列表': '\n'.join(activity_names),
                '最近登录时间': format_system_time_for_export(admin_user.last_login),
                '注册时间': format_system_time_for_export(admin_user.created_at)
            })

            for activity in created_activities:
                activity_society = db.session.get(Society, getattr(activity, 'society_id', None)) if getattr(activity, 'society_id', None) else None
                activity_rows.append({
                    '管理员用户ID': admin_user.id,
                    '管理员用户名': admin_user.username,
                    '管理员邮箱': admin_user.email,
                    '活动ID': activity.id,
                    '活动名称': activity.title,
                    '活动状态': activity.status,
                    '所属社团': activity_society.name if activity_society else '',
                    '活动开始时间': localize_time(activity.start_time).strftime('%Y-%m-%d %H:%M:%S') if activity.start_time else '',
                    '活动结束时间': localize_time(activity.end_time).strftime('%Y-%m-%d %H:%M:%S') if activity.end_time else '',
                    '活动创建时间': format_system_time_for_export(activity.created_at)
                })

        pd.DataFrame(summary_rows).to_excel(writer, sheet_name='社团管理员概览', index=False)
        pd.DataFrame(activity_rows).to_excel(writer, sheet_name='管理员发布活动明细', index=False)

        writer.close()
        output.seek(0)

        log_action('export_society_admins', '导出社团管理员信息与发布活动明细')

        beijing_now = get_beijing_time()
        return send_file(
            output,
            as_attachment=True,
            download_name=f"社团管理员信息_{beijing_now.strftime('%Y%m%d%H%M%S')}.xlsx",
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(f"Error exporting society admins: {e}", exc_info=True)
        flash('导出社团管理员信息时出错', 'danger')
        return redirect(url_for('admin.students'))

def _sync_published_announcements_to_notifications():
    """将已发布公告同步为公开通知，确保首页/学生头部可见。"""
    try:
        published_announcements = db.session.execute(
            db.select(Announcement).filter_by(status='published').order_by(Announcement.updated_at.desc())
        ).scalars().all()

        created_count = 0
        for ann in published_announcements:
            exists = db.session.execute(
                db.select(Notification).filter(
                    Notification.title == ann.title,
                    Notification.content == ann.content,
                    Notification.created_by == ann.created_by,
                    Notification.is_public == True
                )
            ).scalar_one_or_none()

            if exists:
                continue

            notification = Notification(
                title=ann.title,
                content=ann.content,
                is_important=False,
                created_at=ann.updated_at or ann.created_at or datetime.now(pytz.utc),
                created_by=ann.created_by,
                expiry_date=None,
                is_public=True
            )
            db.session.add(notification)
            created_count += 1

        if created_count > 0:
            db.session.commit()
            logger.info(f"公告同步通知完成，新增 {created_count} 条")
    except Exception as e:
        db.session.rollback()
        logger.error(f"同步公告到通知失败: {e}")

@admin_bp.route('/backup', methods=['GET'])
@admin_required
def backup_system():
    try:
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        backups = []
        for filename in os.listdir(backup_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(backup_dir, filename)
                backup_time = datetime.fromtimestamp(os.path.getctime(filepath))
                
                # 获取文件大小
                file_size = os.path.getsize(filepath)
                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"
                
                # 尝试读取备份内容摘要
                content_summary = "未知内容"
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        content_parts = []
                        if 'data' in data:
                            if 'users' in data['data']:
                                content_parts.append(f"用户({len(data['data']['users'])})")
                            if 'activities' in data['data']:
                                content_parts.append(f"活动({len(data['data']['activities'])})")
                            if 'registrations' in data['data']:
                                content_parts.append(f"报名({len(data['data']['registrations'])})")
                            if 'tags' in data['data']:
                                content_parts.append(f"标签({len(data['data']['tags'])})")
                        
                        if content_parts:
                            content_summary = "、".join(content_parts)
                except:
                    pass
                
                backups.append({
                    'name': filename,
                    'created_at': backup_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'size': size_str,
                    'content': content_summary
                })
        
        backups.sort(key=lambda x: x['created_at'], reverse=True)
        
        return render_template('admin/backup.html',
                              backups=backups,
                              current_time=datetime.now().strftime('%Y%m%d_%H%M%S'))
    except Exception as e:
        logger.error(f"Error in backup system page: {e}")
        flash('加载备份系统页面时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/backup/create', methods=['POST'])
@admin_required
def create_backup():
    try:
        backup_name = request.form.get('backup_name', f"backup_{normalize_datetime_for_db(datetime.now()).strftime('%Y%m%d_%H%M%S')}")
        include_users = 'include_users' in request.form
        include_activities = 'include_activities' in request.form
        include_registrations = 'include_registrations' in request.form
        backup_format = request.form.get('backup_format', 'json')  # 新增：备份格式选择
        
        # 准备备份数据
        backup_data = {
            'version': '1.0',
            'created_at': normalize_datetime_for_db(datetime.now()).isoformat(),
            'created_by': current_user.username,
            'data': {}
        }
        
        # 用户数据
        if include_users:
            backup_data['data']['users'] = [
                {
                    'username': user.username,
                    'email': user.email,
                    'role_id': user.role_id,
                    'active': user.active
                } for user in db.session.execute(db.select(User)).scalars().all()
            ]
            
            backup_data['data']['student_info'] = [
                {
                    'user_id': info.user_id,
                    'student_id': info.student_id,
                    'real_name': info.real_name,
                    'gender': info.gender,
                    'grade': info.grade,
                    'college': info.college,
                    'major': info.major,
                    'phone': info.phone,
                    'qq': info.qq,
                    'points': info.points,
                    'has_selected_tags': info.has_selected_tags
                } for info in db.session.execute(db.select(StudentInfo)).scalars().all()
            ]
        
        # 活动数据
        if include_activities:
            backup_data['data']['activities'] = [
                {
                    'title': activity.title,
                    'description': activity.description,
                    'location': activity.location,
                    'start_time': activity.start_time.isoformat() if activity.start_time else None,
                    'end_time': activity.end_time.isoformat() if activity.end_time else None,
                    'registration_start_time': activity.registration_start_time.isoformat() if activity.registration_start_time else None,
                    'registration_deadline': activity.registration_deadline.isoformat() if activity.registration_deadline else None,
                    'max_participants': activity.max_participants,
                    'status': activity.status,
                    'type': activity.type,
                    'is_featured': activity.is_featured,
                    'points': activity.points,
                    'created_by': activity.created_by
                } for activity in db.session.execute(db.select(Activity)).scalars().all()
            ]
        
        # 报名数据
        if include_registrations:
            backup_data['data']['registrations'] = [
                {
                    'user_id': reg.user_id,
                    'activity_id': reg.activity_id,
                    'register_time': reg.register_time.isoformat() if reg.register_time else None,
                    'check_in_time': reg.check_in_time.isoformat() if reg.check_in_time else None,
                    'status': reg.status,
                    'remark': reg.remark
                } for reg in db.session.execute(db.select(Registration)).scalars().all()
            ]
        
        # 确保备份目录存在
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        if backup_format == 'zip':
            # 创建ZIP格式备份
            filename = secure_filename(f"{backup_name}.zip")
            filepath = os.path.join(backup_dir, filename)
            
            # 创建临时JSON文件
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as temp_json:
                json.dump(backup_data, temp_json, ensure_ascii=False, indent=2, default=str)
                temp_json_path = temp_json.name
            
            # 创建ZIP文件
            with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 添加JSON数据
                zipf.write(temp_json_path, arcname='backup_data.json')
                
                # 添加README文件
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as temp_readme:
                    temp_readme.write(f"智能社团+系统备份\n")
                    temp_readme.write(f"创建时间: {normalize_datetime_for_db(datetime.now()).strftime('%Y-%m-%d %H:%M:%S')}\n")
                    temp_readme.write(f"创建者: {current_user.username}\n\n")
                    temp_readme.write("备份内容:\n")
                    if include_users:
                        temp_readme.write(f"- 用户数据: {len(backup_data['data'].get('users', []))} 条记录\n")
                        temp_readme.write(f"- 学生信息: {len(backup_data['data'].get('student_info', []))} 条记录\n")
                    if include_activities:
                        temp_readme.write(f"- 活动数据: {len(backup_data['data'].get('activities', []))} 条记录\n")
                    if include_registrations:
                        temp_readme.write(f"- 报名数据: {len(backup_data['data'].get('registrations', []))} 条记录\n")
                    temp_readme_path = temp_readme.name
                
                zipf.write(temp_readme_path, arcname='README.txt')
                
                # 添加数据库文件副本
                db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'instance', 'cqnu_association.db')
                if os.path.exists(db_path):
                    zipf.write(db_path, arcname='database_backup.db')
            
            # 删除临时文件
            os.unlink(temp_json_path)
            os.unlink(temp_readme_path)
            
        else:
            # 创建JSON格式备份
            filename = secure_filename(f"{backup_name}.json")
            filepath = os.path.join(backup_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)
        
        # 记录操作日志
        log_action('create_backup', f'创建系统备份: {filename}')
        
        flash(f'备份已创建: {filename}', 'success')
        return redirect(url_for('admin.backup_system'))
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating backup: {e}")
        flash(f'创建备份时出错: {str(e)}', 'danger')
        return redirect(url_for('admin.backup_system'))

@admin_bp.route('/backup/import', methods=['POST'])
@admin_required
def import_backup():
    try:
        if 'backup_file' not in request.files:
            flash('请选择备份文件', 'warning')
            return redirect(url_for('admin.backup_system'))
        
        file = request.files['backup_file']
        if file.filename == '':
            flash('未选择文件', 'warning')
            return redirect(url_for('admin.backup_system'))
        
        if not file.filename.endswith('.json'):
            flash('请上传.json格式的备份文件', 'warning')
            return redirect(url_for('admin.backup_system'))
        
        # 读取备份数据
        backup_data = json.load(file)
        
        # 开始数据导入
        if 'data' in backup_data:
            # 显示全局加载动画
            flash('正在导入备份数据，请稍候...', 'info')
            
            # 设置事务隔离级别并延迟约束检查
            db.session.execute(db.text("BEGIN"))
            db.session.execute(db.text("SET CONSTRAINTS ALL DEFERRED"))
            
            try:
                # 清除所有中间表和关联表
                tables_to_clear = [
                    "activity_tags", "student_tags", "points_history", 
                    "activity_checkins", "activity_reviews", "registrations", 
                    "system_logs", "messages", "announcements", 
                    "ai_chat_history", "ai_user_preferences"
                ]
                
                # 检查notifications表是否存在
                try:
                    db.session.execute(db.text("SELECT 1 FROM notifications LIMIT 1"))
                    tables_to_clear.append("notifications")
                except Exception as e:
                    logger.info(f"notifications表不存在，跳过: {e}")
                
                # 按顺序删除表数据
                for table in tables_to_clear:
                    try:
                        db.session.execute(db.text(f"DELETE FROM {table}"))
                        logger.info(f"已清空表: {table}")
                    except Exception as e:
                        logger.info(f"清空表{table}时出错，可能不存在: {e}")
                
                # 然后删除主要表
                main_tables = ["activities", "student_info", "tags", "users"]
                for table in main_tables:
                    db.session.execute(db.text(f"DELETE FROM {table}"))
                    logger.info(f"已清空表: {table}")
                
                # 导入备份数据
                if 'users' in backup_data['data']:
                    for user_data in backup_data['data']['users']:
                        user = User()
                        for key, value in user_data.items():
                            setattr(user, key, value)
                        db.session.add(user)
                
                if 'student_info' in backup_data['data']:
                    for info_data in backup_data['data']['student_info']:
                        info = StudentInfo()
                        for key, value in info_data.items():
                            setattr(info, key, value)
                        db.session.add(info)
                
                if 'activities' in backup_data['data']:
                    for activity_data in backup_data['data']['activities']:
                        activity = Activity()
                        for key, value in activity_data.items():
                            setattr(activity, key, value)
                        db.session.add(activity)
                
                if 'registrations' in backup_data['data']:
                    for reg_data in backup_data['data']['registrations']:
                        reg = Registration()
                        for key, value in reg_data.items():
                            setattr(reg, key, value)
                        db.session.add(reg)
                
                # 提交所有更改
                db.session.commit()
                flash('备份数据导入成功！系统数据已恢复', 'success')
                log_action('import_backup', '导入系统备份数据')
            except Exception as e:
                db.session.rollback()
                logger.error(f"导入备份过程中出错: {e}")
                flash(f'导入备份失败: {str(e)}', 'danger')
        else:
            flash('无效的备份文件格式', 'danger')
        
        return redirect(url_for('admin.backup_system'))
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error importing backup: {e}")
        flash(f'导入备份失败: {str(e)}', 'danger')
        return redirect(url_for('admin.backup_system'))

# 添加更新报名状态的路由
@admin_bp.route('/registration/<int:id>/update_status', methods=['POST'])
@admin_required
def update_registration_status(id):
    try:
        registration = db.get_or_404(Registration, id)
        activity = db.session.get(Activity, registration.activity_id)
        if not _scope_guard_activity(activity):
            flash('您只能管理所属社团活动报名', 'danger')
            return redirect(url_for('admin.activities'))
        new_status = request.form.get('status')
        old_status = registration.status
        
        if new_status not in ['registered', 'cancelled', 'attended']:
            flash('无效的状态值', 'danger')
            return redirect(url_for('admin.activity_registrations', id=registration.activity_id))
        
        # 处理积分变更
        student_info = StudentInfo.query.join(User).filter(User.id == registration.user_id).first()
        
        if student_info and activity:
            points = activity.points or (20 if activity.is_featured else 10)
            
            # 已参加 → 取消参加/已报名：扣除积分
            if old_status == 'attended' and new_status in ['registered', 'cancelled']:
                add_points(student_info.id, -points, f"取消参加活动：{activity.title}", activity.id)
                
            # 已报名/已取消 → 已参加：添加积分
            elif old_status in ['registered', 'cancelled'] and new_status == 'attended':
                add_points(student_info.id, points, f"参与活动：{activity.title}", activity.id)
        
        # 更新状态
        registration.status = new_status
        
        # 如果状态改为已参加，设置签到时间
        if new_status == 'attended' and not registration.check_in_time:
            registration.check_in_time = get_localized_now()
        # 状态从已参加改为其他状态时清理签到时间，避免“已取消仍显示已签到/可下载”的误判
        elif new_status in ['registered', 'cancelled']:
            registration.check_in_time = None
        
        db.session.commit()
        
        log_action('update_registration', f'更新报名状态: ID {id} 从 {old_status} 到 {new_status}')
        flash('报名状态已更新', 'success')
        return redirect(url_for('admin.activity_registrations', id=registration.activity_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating registration status: {e}")
        flash('更新报名状态时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/activity/<int:id>/checkin', methods=['POST'])
@admin_required
def activity_checkin(id):
    try:
        student_id = request.form.get('student_id')
        if not student_id:
            return jsonify({'success': False, 'message': '学生ID不能为空'})
        
        # 查找学生
        student = db.session.execute(db.select(StudentInfo).filter_by(student_id=student_id)).scalar_one_or_none()
        if not student:
            return jsonify({'success': False, 'message': '学生不存在'})
        
        # 查找活动
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '您只能管理所属社团活动签到'}), 403
        
        # 查找报名记录
        registration = db.session.execute(db.select(Registration).filter_by(
            user_id=student.user_id,
            activity_id=id
        )).scalar_one_or_none()
        
        if not registration:
            return jsonify({'success': False, 'message': '该学生未报名此活动'})
        
        if registration.check_in_time:
            return jsonify({'success': False, 'message': '该学生已签到'})
        
        # 更新签到状态
        registration.status = 'attended'
        registration.check_in_time = get_localized_now()
        
        # 添加积分奖励
        points = activity.points or (20 if activity.is_featured else 10)  # 使用活动自定义积分或默认值
        student_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=student.user_id)).scalar_one_or_none()
        if student_info:
            if add_points(student_info.id, points, f"参与活动：{activity.title}", activity.id):
                db.session.commit()
                return jsonify({
                    'success': True, 
                    'message': f'签到成功！获得 {points} 积分',
                    'points': points
                })
        
        return jsonify({'success': False, 'message': '签到失败，请重试'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in activity checkin: {e}")
        return jsonify({'success': False, 'message': '签到时出错'})

@admin_bp.route('/tags')
@admin_required
def manage_tags():
    from src.utils.time_helpers import display_datetime
    
    tags_stmt = db.select(Tag).order_by(Tag.created_at.desc())
    tags = db.session.execute(tags_stmt).scalars().all()
    pending_requests = []
    if is_super_admin(current_user):
        pending_logs = db.session.execute(
            db.select(SystemLog)
            .filter(SystemLog.action == 'approval_request')
            .order_by(SystemLog.created_at.desc())
            .limit(200)
        ).scalars().all()
        for log in pending_logs:
            try:
                details = json.loads(log.details or '{}')
            except Exception:
                continue
            if details.get('status') == 'pending' and details.get('type') == 'tag':
                pending_requests.append({'log': log, 'details': details})

    return render_template('admin/tags.html', tags=tags, display_datetime=display_datetime, pending_requests=pending_requests)

@admin_bp.route('/tags/create', methods=['POST'])
@admin_required
def create_tag():
    try:
        name = request.form.get('name', '').strip()
        color = request.form.get('color', 'primary')
        
        if not name:
            flash('标签名称不能为空', 'danger')
            return redirect(url_for('admin.manage_tags'))
        
        # 检查是否已存在
        tag_stmt = db.select(Tag).filter_by(name=name)
        existing_tag = db.session.execute(tag_stmt).scalar_one_or_none()
        if existing_tag:
            flash('标签已存在', 'warning')
            return redirect(url_for('admin.manage_tags'))
        
        if not is_super_admin(current_user):
            _create_approval_request(
                'tag',
                'create',
                {'name': name, 'color': color}
            )
            flash('标签创建已提交审核，待总管理员批准后生效', 'info')
            return redirect(url_for('admin.manage_tags'))

        tag = Tag(name=name, color=color)
        db.session.add(tag)
        db.session.commit()
        
        flash('标签创建成功', 'success')
        log_action('create_tag', f'创建标签: {name}')
        return redirect(url_for('admin.manage_tags'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating tag: {e}")
        flash('创建标签失败', 'danger')
        return redirect(url_for('admin.manage_tags'))

@admin_bp.route('/tags/<int:id>/edit', methods=['POST'])
@admin_required
def edit_tag(id):
    try:
        tag = db.get_or_404(Tag, id)
        name = request.form.get('name', '').strip()
        color = request.form.get('color', 'primary')
        
        if not name:
            flash('标签名称不能为空', 'danger')
            return redirect(url_for('admin.manage_tags'))
        
        # 检查新名称是否与其他标签重复
        check_stmt = db.select(Tag).filter(Tag.name == name, Tag.id != id)
        existing_tag = db.session.execute(check_stmt).scalar_one_or_none()
        if existing_tag:
            flash('标签名称已存在', 'warning')
            return redirect(url_for('admin.manage_tags'))
        
        if not is_super_admin(current_user):
            _create_approval_request(
                'tag',
                'edit',
                {'id': id, 'name': name, 'color': color},
                target_id=id
            )
            flash('标签修改已提交审核，待总管理员批准后生效', 'info')
            return redirect(url_for('admin.manage_tags'))

        tag.name = name
        tag.color = color
        db.session.commit()
        
        flash('标签更新成功', 'success')
        log_action('edit_tag', f'编辑标签: {name}')
        return redirect(url_for('admin.manage_tags'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error editing tag: {e}")
        flash('更新标签失败', 'danger')
        return redirect(url_for('admin.manage_tags'))

@admin_bp.route('/tags/<int:id>/delete', methods=['POST'])
@admin_required
def delete_tag(id):
    try:
        validate_csrf(request.form.get('csrf_token'))
        tag = db.get_or_404(Tag, id)
        name = tag.name

        if not is_super_admin(current_user):
            _create_approval_request(
                'tag',
                'delete',
                {'id': id, 'name': name},
                target_id=id
            )
            flash('标签删除已提交审核，待总管理员批准后执行', 'info')
            return redirect(url_for('admin.manage_tags'))
        
        # 从所有相关活动中移除标签
        for activity in tag.activities:
            activity.tags.remove(tag)
        
        # 从所有相关学生中移除标签
        for student in tag.students:
            student.tags.remove(tag)
        
        db.session.delete(tag)
        db.session.commit()
        
        log_action('delete_tag', f'删除标签: {name}')
        flash('标签已成功删除', 'success')
        return redirect(url_for('admin.manage_tags'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting tag: {e}")
        flash('删除标签失败', 'danger')
        return redirect(url_for('admin.manage_tags'))

@admin_bp.route('/api/statistics_ext')
@admin_bp.route('/admin/api/statistics_ext')  # 添加一个包含admin前缀的路由
@admin_required
def api_statistics_ext():
    try:
        # 标签热度 - 改为统计学生选择的标签而非活动标签
        from src.models import Tag, StudentInfo, student_tags
        
        tag_stats_stmt = db.select(
            Tag.name, 
            func.count(student_tags.c.student_id).label('count')
        ).outerjoin(
            student_tags, Tag.id == student_tags.c.tag_id
        ).group_by(Tag.id)
        
        tag_stats = db.session.execute(tag_stats_stmt).all()
        
        tag_heat = {
            'labels': [t[0] for t in tag_stats],
            'data': [t[1] for t in tag_stats]
        }
        
        # 积分分布
        from src.models import StudentInfo
        points_bins = [0, 10, 30, 50, 100, 200, 500, 1000]
        bin_labels = [f'{points_bins[i]}-{points_bins[i+1]-1}' for i in range(len(points_bins)-1)] + [f'{points_bins[-1]}+']
        bin_counts = [0] * len(bin_labels)  # 修正：使用bin_labels的长度
        
        student_info_stmt = db.select(StudentInfo)
        students = db.session.execute(student_info_stmt).scalars().all()
        
        for stu in students:
            points = stu.points or 0  # 处理None值
            
            # 检查最后一个区间（特殊情况）
            if points >= points_bins[-1]:
                bin_counts[-1] += 1
                continue
                
            # 检查其他区间
            for i in range(len(points_bins) - 1):
                if points_bins[i] <= points < points_bins[i+1]:
                    bin_counts[i] += 1
                    break
        
        points_dist = {
            'labels': bin_labels,
            'data': bin_counts
        }
        
        # 添加注册趋势数据（每日新注册用户数）
        try:
            now = get_localized_now()
            days_ago_30 = now - timedelta(days=30)
            
            registration_trend_stmt = db.select(
                func.date(User.created_at).label('date'),
                func.count(User.id).label('count')
            ).filter(
                User.created_at >= days_ago_30
            ).group_by(
                func.date(User.created_at)
            )
            
            registration_trend = db.session.execute(registration_trend_stmt).all()
            
            # 将结果转换为前端可用的格式
            reg_dates = [(days_ago_30 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(31)]
            reg_counts = [0] * 31
            
            for item in registration_trend:
                date_str = item.date.strftime('%Y-%m-%d') if hasattr(item.date, 'strftime') else str(item.date)
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                    day_diff = (date_obj - days_ago_30).days
                    if 0 <= day_diff < 31:
                        reg_counts[day_diff] = item.count
                except:
                    pass
            
            registration_trend_data = {
                'labels': reg_dates,
                'data': reg_counts
            }
        except Exception as e:
            logger.error(f"获取注册趋势数据失败: {e}")
            registration_trend_data = {
                'labels': [],
                'data': []
            }
        
        return jsonify({
            'tag_heat': tag_heat, 
            'points_dist': points_dist,
            'registration_trend': registration_trend_data
        })
    except Exception as e:
        logger.error(f"Error in api_statistics_ext: {e}")
        return jsonify({'error': '获取扩展统计数据失败'}), 500

@admin_bp.route('/activity/<int:id>/reviews')
@admin_required
def activity_reviews(id):
    try:
        from src.models import Activity, ActivityReview
        from src.utils.time_helpers import display_datetime
        from flask_wtf.csrf import generate_csrf
        
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能管理所属社团活动评价', 'danger')
            return redirect(url_for('admin.activities'))
        reviews = ActivityReview.query.filter_by(activity_id=id).order_by(ActivityReview.created_at.desc()).all()

        # 预加载评价人信息，避免模板中姓名为空（非匿名时优先显示真实姓名）
        user_ids = {review.user_id for review in reviews if review.user_id}
        reviewer_name_map = {}
        if user_ids:
            reviewer_rows = db.session.execute(
                db.select(User.id, User.username, StudentInfo.real_name)
                .outerjoin(StudentInfo, StudentInfo.user_id == User.id)
                .where(User.id.in_(user_ids))
            ).all()
            reviewer_name_map = {
                row.id: {
                    'username': row.username,
                    'real_name': row.real_name
                }
                for row in reviewer_rows
            }

        for review in reviews:
            review.display_created_at = _format_review_time_for_display(review.created_at)
            if review.is_anonymous:
                review.reviewer_name = '匿名同学'
            else:
                reviewer_info = reviewer_name_map.get(review.user_id, {})
                review.reviewer_name = (
                    reviewer_info.get('real_name')
                    or reviewer_info.get('username')
                    or f'用户{review.user_id}'
                )

        if reviews:
            average_rating = sum(r.rating for r in reviews) / len(reviews)
        else:
            average_rating = 0
        
        # 创建CSRF表单对象
        from flask_wtf import FlaskForm
        form = FlaskForm()
        
        return render_template('admin/activity_reviews.html', 
                            activity=activity, 
                            reviews=reviews, 
                            average_rating=average_rating,
                            display_datetime=display_datetime,
                            form=form)
    except Exception as e:
        logger.error(f"Error in activity_reviews: {str(e)}")
        flash('查看活动评价时出错', 'danger')
        return redirect(url_for('admin.activities'))

@admin_bp.route('/activity/review/<int:review_id>/delete', methods=['POST'])
@admin_required
def delete_activity_review(review_id):
    try:
        review = db.get_or_404(ActivityReview, review_id)
        activity_id = review.activity_id
        activity = db.session.get(Activity, activity_id)
        if not _scope_guard_activity(activity):
            flash('您只能管理所属社团活动评价', 'danger')
            return redirect(url_for('admin.activities'))
        reclaim_points = request.form.get('reclaim_points') == '1'

        if reclaim_points:
            student_info = db.session.execute(
                db.select(StudentInfo).filter_by(user_id=review.user_id)
            ).scalar_one_or_none()
            if student_info:
                reclaim_amount = min(5, max(0, student_info.points or 0))
                if reclaim_amount > 0:
                    student_info.points -= reclaim_amount
                    db.session.add(PointsHistory(
                        student_id=student_info.id,
                        points=-reclaim_amount,
                        reason='管理员删除活动评价回收积分',
                        activity_id=activity_id,
                        society_id=student_info.society_id
                    ))

        db.session.delete(review)
        db.session.commit()

        log_action('delete_activity_review', f'删除活动评价: review_id={review_id}, activity_id={activity_id}, reclaim_points={reclaim_points}')
        flash('活动评价已删除', 'success')
        return redirect(url_for('admin.activity_reviews', id=activity_id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_activity_review: {e}")
        flash('删除活动评价时出错', 'danger')
        return redirect(url_for('admin.activities'))

@admin_bp.route('/activity/<int:id>/ai/review-cluster-summary', methods=['POST'])
@admin_required
def ai_review_cluster_summary(id):
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '仅可分析所属社团活动'}), 403
        reviews = ActivityReview.query.filter_by(activity_id=id).order_by(ActivityReview.created_at.desc()).all()

        if not reviews:
            return jsonify({'success': True, 'summary': '该活动暂无评价数据，暂无法生成聚类总结。'})

        review_lines = []
        for idx, review in enumerate(reviews[:120], start=1):
            review_text = (review.review or '').replace('\n', ' ').strip()
            if len(review_text) > 180:
                review_text = review_text[:180] + '…'
            review_lines.append(
                f"{idx}. 总评{review.rating}/5，内容{review.content_quality or '-'}，组织{review.organization or '-'}，设施{review.facility or '-'}，反馈：{review_text}"
            )

        system_prompt = "你是高校活动评价分析助手，擅长把大量反馈聚类并输出行动建议。"
        user_prompt = (
            f"活动标题：{activity.title}\n"
            f"评价总数：{len(reviews)}\n"
            f"评价样本：\n" + "\n".join(review_lines) + "\n\n"
            "请输出：\n"
            "1) 评价主题聚类（3-6类，每类含‘主题名、占比估计、典型反馈、优先级’）\n"
            "2) Top3 优点\n"
            "3) Top3 问题\n"
            "4) 可执行改进清单（按高/中/低优先级）\n"
            "要求：中文，结构清晰，直接可用于运营复盘。"
        )

        summary = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.3, max_tokens=1600)
        return jsonify({'success': True, 'summary': summary})
    except Exception as e:
        logger.error(f"AI聚类总结失败: {e}")
        return jsonify({'success': False, 'message': f'生成失败: {str(e)}'}), 500


@admin_bp.route('/activity/<int:id>/ai/review-cluster-summary-async', methods=['POST'])
@admin_required
def ai_review_cluster_summary_async(id):
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '仅可分析所属社团活动'}), 403

        job_id = _enqueue_text_job('review_cluster_summary', {'activity_id': id})
        return jsonify({'success': True, 'done': False, 'job_id': job_id, 'message': '任务已提交，正在分析评价'})
    except Exception as e:
        logger.error(f"提交AI聚类总结异步任务失败: {e}")
        return jsonify({'success': False, 'message': f'提交失败: {str(e)}'}), 500

@admin_bp.route('/activity/<int:id>/ai/retrospective-report', methods=['POST'])
@admin_required
def ai_activity_retrospective_report(id):
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '仅可分析所属社团活动'}), 403
        reviews = ActivityReview.query.filter_by(activity_id=id).all()
        registrations = Registration.query.filter_by(activity_id=id).all()

        total_registered = len(registrations)
        attended_count = sum(1 for r in registrations if r.status == 'attended')
        cancelled_count = sum(1 for r in registrations if r.status == 'cancelled')
        no_show_count = max(total_registered - attended_count - cancelled_count, 0)
        attendance_rate = (attended_count / total_registered * 100.0) if total_registered else 0.0

        avg_rating = (sum((r.rating or 0) for r in reviews) / len(reviews)) if reviews else 0.0
        avg_content = (sum((r.content_quality or 0) for r in reviews) / len(reviews)) if reviews else 0.0
        avg_organization = (sum((r.organization or 0) for r in reviews) / len(reviews)) if reviews else 0.0
        avg_facility = (sum((r.facility or 0) for r in reviews) / len(reviews)) if reviews else 0.0

        sample_reviews = []
        for idx, review in enumerate(reviews[:40], start=1):
            text_sample = (review.review or '').replace('\n', ' ').strip()
            if len(text_sample) > 160:
                text_sample = text_sample[:160] + '…'
            sample_reviews.append(f"{idx}. {text_sample}")

        system_prompt = "你是高校活动运营复盘顾问，擅长产出可执行复盘报告。"
        user_prompt = (
            f"活动：{activity.title}\n"
            f"状态：{activity.status}\n"
            f"时间：{display_datetime(activity.start_time, None, '%Y-%m-%d %H:%M')} - {display_datetime(activity.end_time, None, '%Y-%m-%d %H:%M')}\n"
            f"地点：{activity.location or '未设置'}\n"
            f"积分：{activity.points or 0}\n"
            f"报名人数：{total_registered}\n"
            f"到场人数：{attended_count}\n"
            f"取消人数：{cancelled_count}\n"
            f"疑似未到场人数：{no_show_count}\n"
            f"到场率：{attendance_rate:.1f}%\n"
            f"评价数：{len(reviews)}\n"
            f"平均总评分：{avg_rating:.2f}\n"
            f"内容均分：{avg_content:.2f}\n"
            f"组织均分：{avg_organization:.2f}\n"
            f"设施均分：{avg_facility:.2f}\n"
            f"评价样本：\n{chr(10).join(sample_reviews) if sample_reviews else '暂无评价样本'}\n\n"
            "请生成复盘报告，包含：\n"
            "1) 活动目标达成评估\n"
            "2) 数据结论（报名/到场/评分）\n"
            "3) 关键问题与根因\n"
            "4) 下一次活动优化方案（会前/会中/会后）\n"
            "5) 下次可量化KPI建议（3-5条）\n"
            "要求：中文、结构清晰、可执行、不要空泛。"
        )

        report = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.35, max_tokens=1900)
        return jsonify({'success': True, 'report': report})
    except Exception as e:
        logger.error(f"AI复盘报告生成失败: {e}")
        return jsonify({'success': False, 'message': f'生成失败: {str(e)}'}), 500


@admin_bp.route('/activity/<int:id>/ai/retrospective-report-async', methods=['POST'])
@admin_required
def ai_activity_retrospective_report_async(id):
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '仅可分析所属社团活动'}), 403

        job_id = _enqueue_text_job('retrospective_report', {'activity_id': id})
        return jsonify({'success': True, 'done': False, 'job_id': job_id, 'message': '任务已提交，正在生成复盘报告'})
    except Exception as e:
        logger.error(f"提交AI复盘报告异步任务失败: {e}")
        return jsonify({'success': False, 'message': f'提交失败: {str(e)}'}), 500


@admin_bp.route('/ai/text-job-status/<job_id>', methods=['GET'])
@admin_required
def ai_text_job_status(job_id):
    try:
        _cleanup_expired_text_jobs(current_app)
        payload = _read_text_job(current_app, job_id)
        if not payload:
            return jsonify({'success': False, 'message': '任务不存在或已过期'}), 404

        owner_id = payload.get('owner_id')
        if owner_id and int(owner_id) != current_user.id:
            return jsonify({'success': False, 'message': '无权查看该任务'}), 403

        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    except Exception as e:
        logger.error(f"查询AI文本任务状态失败: {e}")
        return jsonify({'success': False, 'message': f'查询失败: {str(e)}'}), 500

@admin_bp.route('/api/qrcode/checkin/<int:id>')
@admin_required
def generate_checkin_qrcode(id):
    try:
        # 检查活动是否存在
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '您只能管理所属社团活动签到'}), 403
        
        # 获取当前本地化时间
        now = get_localized_now()
        
        # 生成唯一签到密钥，确保时效性和安全性
        checkin_key = hashlib.sha256(f"{activity.id}:{now.timestamp()}:{current_app.config['SECRET_KEY']}".encode()).hexdigest()[:16]
        
        # 必须先成功写入数据库，再下发二维码
        try:
            activity.checkin_key = checkin_key
            activity.checkin_key_expires = now + timedelta(minutes=5)  # 5分钟有效期
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"无法存储签到密钥到数据库: {e}")
            return jsonify({'success': False, 'message': '签到密钥保存失败，请重试'}), 500
        
        # 生成带签到URL的二维码，使用完整域名
        base_url = request.host_url.rstrip('/')
        checkin_url = f"{base_url}/checkin/scan/{activity.id}/{checkin_key}"
        
        # 创建QR码实例 - 优化参数
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,  # 提高错误纠正级别
            box_size=10,
            border=4,
        )
        
        # 添加URL数据
        qr.add_data(checkin_url)
        qr.make(fit=True)
        
        # 创建图像
        qr_image = qr.make_image(fill_color="black", back_color="white")
        
        # 保存到内存并转为base64
        img_buffer = BytesIO()
        qr_image.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        qr_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
        
        # 返回JSON格式的二维码数据，包含data:image/png;base64前缀
        return jsonify({
            'success': True,
            'qrcode': f"data:image/png;base64,{qr_base64}",
            'expires_in': 300,  # 5分钟，单位秒
            'generated_at': now.strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        logger.error(f"生成签到二维码时出错: {e}")
        return jsonify({'success': False, 'message': '生成二维码失败'}), 500

@admin_bp.route('/checkin-modal/<int:id>')
@login_required
@admin_required
def checkin_modal(id):
    """签到管理界面"""
    try:
        # 记录开始调试信息
        logger.info(f"进入checkin_modal函数: activity_id={id}")
        
        # 生成CSRF令牌
        from flask_wtf.csrf import generate_csrf
        csrf_token = generate_csrf()
        logger.info(f"生成CSRF令牌: {csrf_token[:10]}...")
        
        # 导入display_datetime函数
        from src.utils.time_helpers import display_datetime
        logger.info(f"导入display_datetime函数: 类型={type(display_datetime)}")
        
        # 添加调试日志
        logger.info(f"display_datetime类型: {type(display_datetime)}, 值: {display_datetime}")
        
        # 获取活动信息
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能管理所属社团活动签到', 'danger')
            return redirect(url_for('admin.activities'))
        logger.info(f"获取活动信息: id={activity.id}, 标题={activity.title}")
        
        # 获取当前时间
        now = get_localized_now()
        logger.info(f"获取当前北京时间: {now}")
        
        # 获取报名人数
        registration_count = Registration.query.filter(
            Registration.activity_id == id,
            db.or_(
                Registration.status == 'registered',
                Registration.status == 'attended'
            )
        ).count()
        logger.info(f"获取报名人数: {registration_count}")
        
        # 获取签到人数
        checkin_count = Registration.query.filter(
            Registration.activity_id == id,
            Registration.check_in_time.isnot(None)
        ).count()
        logger.info(f"获取签到人数: {checkin_count}")
        
        # 获取签到记录
        checkins = db.session.query(
            Registration.id,
            StudentInfo.student_id,
            StudentInfo.real_name,
            StudentInfo.college,
            StudentInfo.major,
            Registration.check_in_time
        ).join(
            StudentInfo, Registration.user_id == StudentInfo.user_id
        ).filter(
            Registration.activity_id == id,
            Registration.check_in_time.isnot(None)
        ).all()
        logger.info(f"获取签到记录: {len(checkins)}条")
        
        # 日志记录
        logger.info(f"管理员访问签到模态框: 活动ID={id}, 报名人数={registration_count}, 签到人数={checkin_count}")
        
        
        return render_template(
            'admin/checkin_modal.html',
            activity=activity,
            registration_count=registration_count,
            checkin_count=checkin_count,
            checkins=checkins,
            now=now,
            display_datetime=display_datetime
        )
        
    except Exception as e:
        logger.error(f"签到模态框加载失败: {str(e)}", exc_info=True)
        flash('加载签到管理界面失败', 'danger')
        return redirect(url_for('admin.activities'))

@admin_bp.route('/admin/checkin-modal/<int:id>')
@login_required
@admin_required
def checkin_modal_admin(id):
    """兼容带admin前缀的路由，重定向到新版签到模态框"""
    return redirect(url_for('admin.checkin_modal', id=id))

# 切换活动签到状态
@admin_bp.route('/activity/<int:id>/toggle-checkin', methods=['POST'])
@admin_required
def toggle_checkin(id):
    try:
        csrf_token = request.form.get('csrf_token') or request.headers.get('X-CSRFToken')
        if not csrf_token:
            logger.warning("toggle_checkin 缺少CSRF令牌")
            flash('操作失败，缺少安全验证令牌', 'danger')
            return redirect(url_for('admin.activity_view', id=id))
        try:
            validate_csrf(csrf_token)
        except Exception as csrf_error:
            logger.warning(f"toggle_checkin CSRF验证失败: {csrf_error}")
            flash('安全验证失败，请刷新页面后重试', 'danger')
            return redirect(url_for('admin.activity_view', id=id))
        
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能管理所属社团活动签到', 'danger')
            return redirect(url_for('admin.activities'))
        
        # 获取当前状态
        current_status = getattr(activity, 'checkin_enabled', False)
        
        # 切换状态（取反）
        new_status = not current_status
        activity.checkin_enabled = new_status
        
        # 如果开启签到，生成或更新签到密钥
        if new_status:
            now = get_localized_now()
            checkin_key = hashlib.sha256(f"{activity.id}:{now.timestamp()}:{current_app.config['SECRET_KEY']}".encode()).hexdigest()[:16]
            activity.checkin_key = checkin_key
            activity.checkin_key_expires = now + timedelta(hours=24)  # 24小时有效期
            status_text = "开启"
        else:
            status_text = "关闭"
        
        db.session.commit()
        
        # 记录新状态
        flash(f'已{status_text}活动签到', 'success')
        
        # 记录操作日志
        log_action(f'toggle_checkin_{status_text}', f'管理员{status_text}了活动 {activity.title} 的签到')
        
        # 重定向回原页面
        referrer = request.referrer
        if referrer:
            # 修复：检查是否在checkin_modal页面
            if 'checkin-modal' in referrer:
                return redirect(url_for('admin.checkin_modal', id=id))
            # 检查是否有其他特殊页面
            elif '/admin/activity/' in referrer and '/view' in referrer:
                return redirect(url_for('admin.activity_view', id=id))
            # 否则返回到原始页面
            return redirect(referrer)
        
        # 如果没有referrer，默认回到活动详情页
        return redirect(url_for('admin.activity_view', id=id))
    except Exception as e:
        db.session.rollback()
        logger.error(f"切换签到状态失败: {e}")
        flash('操作失败，请重试', 'danger')
        return redirect(url_for('admin.activity_view', id=id))

# 系统日志页面
@admin_bp.route('/download_logs', methods=['GET'])
@admin_required
def download_logs():
    try:
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'cqnu_association.log')
        
        if not os.path.exists(log_file):
            flash('日志文件不存在', 'warning')
            return redirect(url_for('admin.system_logs'))
        
        # 记录操作日志
        log_action('download_logs', '下载系统日志文件')
        
        # 返回文件下载
        return send_file(
            log_file,
            mimetype='text/plain',
            as_attachment=True,
            download_name=f'system_logs_{normalize_datetime_for_db(datetime.now()).strftime("%Y%m%d_%H%M%S")}.log'
        )
    except Exception as e:
        logger.error(f"Error downloading logs: {e}")
        flash('下载日志文件时出错', 'danger')
        return redirect(url_for('admin.system_logs'))

# 清空日志
@admin_bp.route('/clear_logs', methods=['POST'])
@admin_required
def clear_logs():
    try:
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'cqnu_association.log')
        
        if os.path.exists(log_file):
            # 清空日志文件内容
            with open(log_file, 'w') as f:
                f.write(f"日志已于 {normalize_datetime_for_db(datetime.now()).strftime('%Y-%m-%d %H:%M:%S')} 被管理员清空\n")
        
        # 记录操作日志
        log_action('clear_logs', '清空系统日志')
        
        flash('日志已清空', 'success')
        return redirect(url_for('admin.system_logs'))
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        flash('清空日志时出错', 'danger')
        return redirect(url_for('admin.system_logs'))

# 下载备份文件
@admin_bp.route('/backup/download/<path:filename>', methods=['GET'])
@admin_required
def download_backup(filename):
    try:
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
        
        # 安全检查：确保文件名不包含路径遍历
        if '..' in filename or filename.startswith('/'):
            flash('无效的文件名', 'danger')
            return redirect(url_for('admin.backup_system'))
        
        filepath = os.path.join(backup_dir, filename)
        
        if not os.path.exists(filepath):
            flash('备份文件不存在', 'warning')
            return redirect(url_for('admin.backup_system'))
        
        # 记录操作日志
        log_action('download_backup', f'下载备份文件: {filename}')
        
        # 返回文件下载
        return send_file(
            filepath,
            mimetype='application/json',
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        logger.error(f"Error downloading backup: {e}")
        flash('下载备份文件时出错', 'danger')
        return redirect(url_for('admin.backup_system'))

# 删除备份文件
@admin_bp.route('/backup/delete/<path:filename>', methods=['POST'])
@admin_required
def delete_backup(filename):
    try:
        try:
            validate_csrf(request.form.get('csrf_token', ''))
        except Exception:
            flash('请求校验失败，请刷新页面后重试', 'danger')
            return redirect(url_for('admin.backup_system'))

        backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
        
        # 安全检查：确保文件名不包含路径遍历
        if '..' in filename or filename.startswith('/'):
            flash('无效的文件名', 'danger')
            return redirect(url_for('admin.backup_system'))
        
        filepath = os.path.join(backup_dir, filename)
        
        if not os.path.exists(filepath):
            flash('备份文件不存在', 'warning')
            return redirect(url_for('admin.backup_system'))
        
        # 删除文件
        os.remove(filepath)
        
        # 记录操作日志
        log_action('delete_backup', f'删除备份文件: {filename}')
        
        flash('备份文件已删除', 'success')
        return redirect(url_for('admin.backup_system'))
    except Exception as e:
        logger.error(f"Error deleting backup: {e}")
        flash('删除备份文件时出错', 'danger')
        return redirect(url_for('admin.backup_system'))

# 重置系统数据
@admin_bp.route('/reset_system', methods=['GET'])
@admin_required
def reset_system_page():
    try:
        return render_template('admin/reset_system.html')
    except Exception as e:
        logger.error(f"Error in reset system page: {e}")
        flash('加载重置系统页面时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

# 执行系统重置
@admin_bp.route('/reset_system', methods=['POST'])
@admin_required
def reset_system():
    try:
        # 验证管理员密码
        password = request.form.get('admin_password')
        if not current_user.check_password(password):
            flash('管理员密码错误，无法执行重置操作', 'danger')
            return redirect(url_for('admin.reset_system_page'))
        
        # 获取重置选项
        reset_users = 'reset_users' in request.form
        reset_activities = 'reset_activities' in request.form
        reset_registrations = 'reset_registrations' in request.form
        reset_tags = 'reset_tags' in request.form
        reset_logs = 'reset_logs' in request.form
        
        # 创建备份
        backup_name = f"pre_reset_{normalize_datetime_for_db(datetime.now()).strftime('%Y%m%d_%H%M%S')}"
        backup_data = {'data': {}}
        
        # 备份用户数据
        if reset_users:
            backup_data['data']['users'] = [
                {
                    'username': user.username,
                    'email': user.email,
                    'role_id': user.role_id,
                    'active': user.active
                } for user in db.session.execute(db.select(User)).scalars().all()
            ]
            backup_data['data']['student_info'] = [
                {
                    'user_id': info.user_id,
                    'student_id': info.student_id,
                    'real_name': info.real_name,
                    'gender': info.gender,
                    'grade': info.grade,
                    'college': info.college,
                    'major': info.major,
                    'phone': info.phone,
                    'qq': info.qq,
                    'points': info.points,
                    'has_selected_tags': info.has_selected_tags
                } for info in db.session.execute(db.select(StudentInfo)).scalars().all()
            ]
        
        # 备份活动数据
        if reset_activities:
            backup_data['data']['activities'] = [
                {
                    'title': activity.title,
                    'description': activity.description,
                    'location': activity.location,
                    'start_time': activity.start_time.isoformat() if activity.start_time else None,
                    'end_time': activity.end_time.isoformat() if activity.end_time else None,
                    'registration_start_time': activity.registration_start_time.isoformat() if activity.registration_start_time else None,
                    'registration_deadline': activity.registration_deadline.isoformat() if activity.registration_deadline else None,
                    'max_participants': activity.max_participants,
                    'status': activity.status,
                    'type': activity.type,
                    'is_featured': activity.is_featured,
                    'points': activity.points,
                    'created_by': activity.created_by
                } for activity in db.session.execute(db.select(Activity)).scalars().all()
            ]
        
        # 备份报名数据
        if reset_registrations:
            backup_data['data']['registrations'] = [
                {
                    'user_id': reg.user_id,
                    'activity_id': reg.activity_id,
                    'register_time': reg.register_time.isoformat() if reg.register_time else None,
                    'check_in_time': reg.check_in_time.isoformat() if reg.check_in_time else None,
                    'status': reg.status,
                    'remark': reg.remark
                } for reg in db.session.execute(db.select(Registration)).scalars().all()
            ]
        
        # 备份标签数据
        if reset_tags:
            backup_data['data']['tags'] = [
                {
                    'name': tag.name,
                    'description': tag.description,
                    'color': tag.color
                } for tag in db.session.execute(db.select(Tag)).scalars().all()
            ]
        
        # 保存备份文件
        backup_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backups')
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        filename = secure_filename(f"{backup_name}.json")
        filepath = os.path.join(backup_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)
        
        # 执行重置操作 - 按照正确的顺序处理外键依赖
        
        # 1. 首先处理报名记录（依赖于活动和用户）
        if reset_registrations:
            logger.info("删除报名记录")
            Registration.query.delete()
            db.session.commit()
            flash('所有报名记录已重置', 'success')
        
        # 2. 处理活动相关数据（依赖于标签）
        if reset_activities:
            logger.info("删除活动相关数据")
            # 先清除活动标签关联
            db.session.execute(db.text("DELETE FROM activity_tags"))
            db.session.commit()
            
            # 清除积分历史中对活动的引用
            db.session.execute(db.text("UPDATE points_history SET activity_id = NULL WHERE activity_id IS NOT NULL"))
            db.session.commit()
            
            # 删除活动评价
            db.session.execute(db.text("DELETE FROM activity_reviews"))
            db.session.commit()
            
            # 删除活动
            db.session.execute(db.text("DELETE FROM activities"))
            db.session.commit()
            flash('所有活动已重置', 'success')
        
        # 3. 处理标签数据
        if reset_tags:
            logger.info("删除标签数据")
            # 清除标签关联
            db.session.execute(db.text("DELETE FROM student_tags"))
            db.session.execute(db.text("DELETE FROM activity_tags"))
            db.session.commit()
            
            # 删除标签
            db.session.execute(db.text("DELETE FROM tags"))
            db.session.commit()
            flash('所有标签已重置', 'success')
            
            # 重新创建默认标签
            default_tags = [
                {'name': '讲座', 'color': 'primary', 'description': '各类学术讲座'},
                {'name': '研讨会', 'color': 'info', 'description': '小组研讨活动'},
                {'name': '实践活动', 'color': 'success', 'description': '校内外实践活动'},
                {'name': '志愿服务', 'color': 'danger', 'description': '志愿者服务活动'},
                {'name': '文体活动', 'color': 'warning', 'description': '文化体育类活动'},
                {'name': '竞赛', 'color': 'secondary', 'description': '各类竞赛活动'}
            ]
            
            for tag_data in default_tags:
                tag = Tag(name=tag_data['name'], color=tag_data['color'], description=tag_data['description'])
                db.session.add(tag)
            
            db.session.commit()
            flash('默认标签已重新创建', 'success')
        
        # 4. 处理用户数据（最复杂的部分）
        if reset_users:
            # 保留当前管理员账号
            admin_username = current_user.username
            admin_email = current_user.email
            admin_password = current_user.password_hash
            
            try:
                logger.info("删除用户相关数据")
                # 删除所有用户相关数据 - 按照正确的顺序处理外键依赖
                
                # 首先删除通知阅读记录
                db.session.execute(db.text("DELETE FROM notification_reads WHERE user_id != :admin_id").bindparams(admin_id=current_user.id))
                db.session.commit()
                
                # 删除消息
                db.session.execute(db.text("DELETE FROM messages WHERE sender_id != :admin_id AND receiver_id != :admin_id").bindparams(admin_id=current_user.id))
                db.session.commit()
                
                # 删除积分历史记录
                db.session.execute(db.text("DELETE FROM points_history WHERE user_id != :admin_id").bindparams(admin_id=current_user.id))
                db.session.commit()
                
                # 删除学生标签关联
                db.session.execute(db.text("DELETE FROM student_tags WHERE student_id IN (SELECT id FROM users WHERE id != :admin_id)").bindparams(admin_id=current_user.id))
                db.session.commit()
                
                # 删除学生信息
                db.session.execute(db.text("DELETE FROM student_info WHERE user_id != :admin_id").bindparams(admin_id=current_user.id))
                db.session.commit()
                
                # 最后删除用户账号（除了当前管理员）
                db.session.execute(db.text("DELETE FROM users WHERE id != :admin_id").bindparams(admin_id=current_user.id))
                db.session.commit()
                
                # 重新创建角色
                admin_role = db.session.execute(db.select(Role).filter_by(name='Admin')).scalar_one_or_none()
                if not admin_role:
                    admin_role = Role(name='Admin', description='管理员')
                    db.session.add(admin_role)
                
                student_role = db.session.execute(db.select(Role).filter_by(name='Student')).scalar_one_or_none()
                if not student_role:
                    student_role = Role(name='Student', description='学生')
                    db.session.add(student_role)
                
                db.session.commit()
                
                flash('用户数据已重置，管理员账号已保留', 'success')
            except Exception as e:
                db.session.rollback()
                logger.error(f"重置用户数据时出错: {str(e)}")
                flash(f'重置用户数据时出错: {str(e)}', 'danger')
        
        # 5. 最后处理日志
        if reset_logs:
            logger.info("重置系统日志")
            # 清空日志文件
            log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'cqnu_association.log')
            if os.path.exists(log_file):
                with open(log_file, 'w') as f:
                    f.write(f"日志已于 {normalize_datetime_for_db(datetime.now()).strftime('%Y-%m-%d %H:%M:%S')} 被管理员重置\n")
            
            # 清空系统日志表
            db.session.execute(db.text("DELETE FROM system_logs"))
            db.session.commit()
            
            flash('系统日志已重置', 'success')
        
        # 记录操作日志
        log_action('reset_system', f'系统重置，选项：用户={reset_users}，活动={reset_activities}，报名={reset_registrations}，标签={reset_tags}，日志={reset_logs}')
        
        flash(f'系统重置已完成，备份已保存为 {filename}', 'success')
        return redirect(url_for('admin.dashboard'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error resetting system: {e}")
        flash(f'重置系统时出错: {str(e)}', 'danger')
        return redirect(url_for('admin.reset_system_page'))

@admin_bp.route('/notifications')
@admin_required
def notifications():
    try:
        page = request.args.get('page', 1, type=int)
        notifications = Notification.query.order_by(Notification.created_at.desc()).paginate(page=page, per_page=10)

        pending_requests = []
        if is_super_admin(current_user):
            pending_logs = db.session.execute(
                db.select(SystemLog)
                .filter(SystemLog.action == 'approval_request')
                .order_by(SystemLog.created_at.desc())
                .limit(200)
            ).scalars().all()
            for log in pending_logs:
                try:
                    details = json.loads(log.details or '{}')
                except Exception:
                    continue
                if details.get('status') == 'pending' and details.get('type') == 'notification':
                    pending_requests.append({'log': log, 'details': details})
        
        # 确保display_datetime函数在模板中可用
        return render_template('admin/notifications.html', 
                              notifications=notifications,
                              pending_requests=pending_requests,
                              display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in notifications page: {e}")
        flash('加载通知列表时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/notification/create', methods=['GET', 'POST'])
@admin_required
@limiter.limit('15 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def create_notification():
    try:
        # 创建Flask-WTF表单对象
        from flask_wtf import FlaskForm
        
        form = FlaskForm()
        
        if request.method == 'POST':
            title = sanitize_plain_text(request.form.get('title'), max_length=120)
            content = sanitize_rich_html(request.form.get('content'), max_length=6000)
            is_important = 'is_important' in request.form
            expiry_date_str = request.form.get('expiry_date')
            
            if not title or not content:
                flash('标题和内容不能为空', 'danger')
                return redirect(url_for('admin.create_notification'))
            
            if not is_super_admin(current_user):
                _create_approval_request(
                    'notification',
                    'create',
                    {
                        'title': title,
                        'content': content,
                        'is_important': bool(is_important),
                        'expiry_date': expiry_date_str or ''
                    }
                )
                flash('通知已提交审核，待总管理员批准后发布', 'info')
                return redirect(url_for('admin.notifications'))

            # 处理过期日期
            expiry_date = None
            if expiry_date_str:
                try:
                    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d')
                    # 确保时区信息正确
                    expiry_date = pytz.utc.localize(expiry_date)
                except ValueError:
                    flash('日期格式无效', 'danger')
                    return redirect(url_for('admin.create_notification'))
            
            # 创建通知 - 使用UTC时间
            now = pytz.utc.localize(datetime.utcnow())
            
            notification = Notification(
                title=title,
                content=content,
                is_important=is_important,
                created_at=now,
                created_by=current_user.id,
                expiry_date=expiry_date,
                is_public=True  # 默认为公开通知
            )
            
            db.session.add(notification)
            db.session.commit()
            _invalidate_home_page_caches()
            
            log_action('create_notification', f'创建通知: {title}')
            flash('通知创建成功', 'success')
            return redirect(url_for('admin.notifications'))
        
        return render_template('admin/notification_form.html', title='创建通知', form=form)
    except Exception as e:
        logger.error(f"Error in create_notification: {e}")
        flash('创建通知时出错', 'danger')
        return redirect(url_for('admin.notifications'))

@admin_bp.route('/notification/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
@limiter.limit('20 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def edit_notification(id):
    try:
        notification = db.get_or_404(Notification, id)
        
        # 创建Flask-WTF表单对象
        from flask_wtf import FlaskForm
        
        form = FlaskForm()
        
        if request.method == 'POST':
            title = sanitize_plain_text(request.form.get('title'), max_length=120)
            content = sanitize_rich_html(request.form.get('content'), max_length=6000)
            is_important = 'is_important' in request.form
            expiry_date_str = request.form.get('expiry_date')
            
            if not title or not content:
                flash('标题和内容不能为空', 'danger')
                return redirect(url_for('admin.edit_notification', id=id))
            
            if not is_super_admin(current_user):
                _create_approval_request(
                    'notification',
                    'edit',
                    {
                        'id': id,
                        'title': title,
                        'content': content,
                        'is_important': bool(is_important),
                        'expiry_date': expiry_date_str or ''
                    },
                    target_id=id
                )
                flash('通知修改已提交审核，待总管理员批准后生效', 'info')
                return redirect(url_for('admin.notifications'))

            # 处理过期日期
            if expiry_date_str:
                try:
                    expiry_date = datetime.strptime(expiry_date_str, '%Y-%m-%d')
                    expiry_date = ensure_timezone_aware(expiry_date)
                    notification.expiry_date = expiry_date
                except ValueError:
                    flash('日期格式无效', 'danger')
                    return redirect(url_for('admin.edit_notification', id=id))
            else:
                notification.expiry_date = None
            
            # 更新通知
            notification.title = title
            notification.content = content
            notification.is_important = is_important
            
            db.session.commit()
            _invalidate_home_page_caches()
            
            log_action('edit_notification', f'编辑通知: {title}')
            flash('通知更新成功', 'success')
            return redirect(url_for('admin.notifications'))
        
        # 格式化日期用于表单显示
        expiry_date = ''
        if notification.expiry_date:
            expiry_date = notification.expiry_date.strftime('%Y-%m-%d')
        
        return render_template('admin/notification_form.html', 
                              notification=notification,
                              expiry_date=expiry_date,
                              title='编辑通知',
                              form=form)
    except Exception as e:
        logger.error(f"Error in edit_notification: {e}")
        flash('编辑通知时出错', 'danger')
        return redirect(url_for('admin.notifications'))

@admin_bp.route('/notification/<int:id>/delete', methods=['POST'])
@admin_required
def delete_notification(id):
    try:
        notification = db.get_or_404(Notification, id)

        if not is_super_admin(current_user):
            _create_approval_request(
                'notification',
                'delete',
                {
                    'id': id,
                    'title': notification.title,
                    'content': notification.content
                },
                target_id=id
            )
            flash('通知删除已提交审核，待总管理员批准后执行', 'info')
            return redirect(url_for('admin.notifications'))

        # 批量删除同源重复通知（同标题+同内容+同创建者+同公开属性）
        duplicate_ids = [row[0] for row in db.session.execute(
            db.select(Notification.id).filter(
                Notification.title == notification.title,
                Notification.content == notification.content,
                Notification.created_by == notification.created_by,
                Notification.is_public == notification.is_public
            )
        ).all()]

        if not duplicate_ids:
            duplicate_ids = [id]

        # 删除所有关联的已读记录
        db.session.execute(
            db.delete(NotificationRead).where(NotificationRead.notification_id.in_(duplicate_ids))
        )

        # 删除通知
        db.session.execute(
            db.delete(Notification).where(Notification.id.in_(duplicate_ids))
        )
        db.session.commit()
        _invalidate_home_page_caches()
        
        log_action(
            action='delete_notification', 
            details=f'删除通知: {notification.title}（共{len(duplicate_ids)}条）'
        )
        flash(f'通知已删除（共清理 {len(duplicate_ids)} 条）', 'success')
        return redirect(url_for('admin.notifications'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_notification: {e}")
        flash('删除通知时出错', 'danger')
        return redirect(url_for('admin.notifications'))

@admin_bp.route('/messages')
@admin_required
def messages():
    try:
        # 记录日志
        logger.info("开始加载管理员站内信页面")
        logger.info(f"当前用户ID: {current_user.id}, 用户名: {current_user.username}")
        
        page = request.args.get('page', 1, type=int)
        filter_type = request.args.get('filter', 'all')
        
        logger.info(f"过滤类型: {filter_type}, 页码: {page}")
        
        # 检查数据库中是否存在消息
        total_messages = db.session.execute(db.select(func.count()).select_from(Message)).scalar()
        logger.info(f"数据库中总消息数: {total_messages}")
        
        # 检查当前用户的消息
        sent_count = db.session.execute(db.select(func.count()).select_from(Message).filter_by(sender_id=current_user.id)).scalar()
        received_count = db.session.execute(db.select(func.count()).select_from(Message).filter_by(receiver_id=current_user.id)).scalar()
        logger.info(f"当前用户发送的消息: {sent_count}, 接收的消息: {received_count}")
        
        # 检查是否有可用的接收者
        available_receivers = db.session.execute(db.select(func.count()).select_from(User).filter(User.id != current_user.id)).scalar()
        if available_receivers == 0:
            flash('系统中没有其他用户，无法发送消息', 'warning')
            logger.warning("系统中没有可用的消息接收者")
        
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

        # 根据过滤类型查询消息
        if filter_type == 'sent':
            logger.info("查询已发送消息")
            query = Message.query.filter_by(sender_id=current_user.id)
        elif filter_type == 'received':
            logger.info("查询已接收消息")
            query = Message.query.filter_by(receiver_id=current_user.id)
        else:  # 'all'
            logger.info("查询所有消息")
            query = Message.query.filter(or_(
                Message.sender_id == current_user.id,
                Message.receiver_id == current_user.id
            ))
        
        logger.info("执行分页查询")
        messages = query.order_by(Message.created_at.desc()).paginate(page=page, per_page=10)
        logger.info(f"查询到消息数量: {len(messages.items) if messages else 0}")
        
        # 检查每条消息的详细信息
        if messages and messages.items:
            for i, msg in enumerate(messages.items):
                logger.info(f"消息 {i+1}: ID={msg.id}, 主题={msg.subject}, 发送者ID={msg.sender_id}, 接收者ID={msg.receiver_id}, 时间={msg.created_at}")
        
        logger.info("渲染站内信模板")
        # 导入display_datetime函数供模板使用
        from src.utils.time_helpers import display_datetime
        
        return render_template('admin/messages.html', 
                              messages=messages, 
                              filter_type=filter_type,
                              no_receivers=(available_receivers == 0),
                              display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in messages page: {str(e)}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")
        flash('加载消息列表时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/message/create', methods=['GET', 'POST'])
@admin_required
@limiter.limit('20 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def create_message():
    try:
        logger.info("开始创建站内信")
        
        # 创建一个空表单对象用于CSRF保护
        from flask_wtf import FlaskForm
        form = FlaskForm()
        
        if request.method == 'POST':
            logger.info("收到站内信创建POST请求")
            if form.validate_on_submit():
                logger.info("CSRF验证通过")
                receiver_id = request.form.get('receiver_id')
                subject = sanitize_plain_text(request.form.get('subject'), max_length=120)
                content = sanitize_plain_text(request.form.get('content'), allow_multiline=True, max_length=5000)
                
                if not receiver_id or not subject or not content:
                    flash('收件人、主题和内容不能为空', 'danger')
                    return redirect(url_for('admin.create_message'))

                try:
                    receiver_id = int(receiver_id)
                except (TypeError, ValueError):
                    flash('收件人参数无效', 'danger')
                    return redirect(url_for('admin.create_message'))
                
                # 验证接收者是否存在
                receiver = db.session.get(User, receiver_id)
                if not receiver:
                    flash('收件人不存在', 'danger')
                    return redirect(url_for('admin.create_message'))
                
                # 创建消息
                message = Message(
                    sender_id=current_user.id,
                    receiver_id=receiver_id,
                    subject=subject,
                    content=content,
                    created_at=get_localized_now()
                )
                
                db.session.add(message)
                db.session.commit()
                
                log_action('send_message', f'发送消息给 {receiver.username}: {subject}')
                flash('消息发送成功', 'success')
                return redirect(url_for('admin.messages'))
            else:
                logger.error(f"CSRF验证失败，表单错误: {form.errors}")
                flash('表单验证失败，请重试', 'danger')
        
        # 获取所有学生用户
        students_stmt = db.select(User).join(Role).filter(Role.name == 'Student')
        students = db.session.execute(students_stmt).scalars().all()
        
        prefill_receiver_id = request.args.get('receiver_id', type=int)
        prefill_subject = sanitize_plain_text(request.args.get('subject', '', type=str), max_length=120)
        prefill_content = sanitize_plain_text(request.args.get('content', '', type=str), allow_multiline=True, max_length=5000)

        return render_template('admin/message_form.html', 
                      students=students,
                      title='发送消息',
                      form=form,
                      prefill_receiver_id=prefill_receiver_id,
                      prefill_subject=prefill_subject,
                      prefill_content=prefill_content)
    except Exception as e:
        logger.error(f"Error in create_message: {e}")
        flash('发送消息时出错', 'danger')
        return redirect(url_for('admin.messages'))

@admin_bp.route('/messages/mark_all_read', methods=['POST'])
@admin_required
def mark_all_messages_read_admin():
    try:
        updated = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).update({Message.is_read: True}, synchronize_session=False)
        db.session.commit()
        flash(f'已标记 {updated} 条未读消息', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in mark_all_messages_read_admin: {e}")
        flash('一键已读失败，请稍后重试', 'danger')
    return redirect(url_for('admin.messages', filter=request.args.get('filter', 'all')))

@admin_bp.route('/messages/delete_read', methods=['POST'])
@admin_required
def delete_read_messages_admin():
    try:
        deleted = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == True
        ).delete(synchronize_session=False)
        db.session.commit()
        flash(f'已删除 {deleted} 条已读消息', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_read_messages_admin: {e}")
        flash('删除已读消息失败，请稍后重试', 'danger')
    return redirect(url_for('admin.messages', filter=request.args.get('filter', 'all')))

@admin_bp.route('/message/<int:id>/ai-reply-draft', methods=['POST'])
@admin_required
def ai_generate_message_reply_draft(id):
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        message = db.get_or_404(Message, id)

        if message.receiver_id != current_user.id:
            return jsonify({'success': False, 'message': '仅可为收到的消息生成回复草稿'}), 403

        sender = db.session.get(User, message.sender_id) if message.sender_id else None
        sender_info = None
        if sender:
            sender_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=sender.id)).scalar_one_or_none()

        sender_name = (
            sender_info.real_name if sender_info and sender_info.real_name
            else (sender.username if sender else '同学')
        )
        sender_student_id = sender_info.student_id if sender_info else ''

        system_prompt = "你是高校社团管理后台助手，请生成专业、友好、可直接发送的中文回复。"
        user_prompt = (
            f"收到的消息主题：{message.subject or ''}\n"
            f"发件人：{sender_name}"
            f"{f'（学号：{sender_student_id}）' if sender_student_id else ''}\n"
            f"消息内容：\n{(message.content or '').strip()}\n\n"
            "请输出一段回复正文，要求：\n"
            "1) 先表示已收到并理解问题\n"
            "2) 给出明确处理建议或下一步\n"
            "3) 语气简洁礼貌，不要空话\n"
            "4) 120-220字\n"
            "5) 不要使用Markdown标题"
        )
        reply_content = _call_ark_chat_completion(system_prompt, user_prompt, temperature=0.5, max_tokens=700)
        reply_subject = f"回复：{message.subject}" if message.subject else "回复：你的反馈"

        return jsonify({
            'success': True,
            'reply_subject': reply_subject,
            'reply_content': reply_content,
            'receiver_id': message.sender_id
        })
    except Exception as e:
        logger.error(f"AI生成回复草稿失败: {e}")
        return jsonify({'success': False, 'message': f'生成失败: {str(e)}'}), 500


@admin_bp.route('/message/<int:id>/ai-reply-draft-async', methods=['POST'])
@admin_required
def ai_generate_message_reply_draft_async(id):
    try:
        validate_csrf(request.headers.get('X-CSRFToken', '') or request.form.get('csrf_token', ''))
        message = db.get_or_404(Message, id)
        if message.receiver_id != current_user.id:
            return jsonify({'success': False, 'message': '仅可为收到的消息生成回复草稿'}), 403

        job_id = _enqueue_text_job('message_reply_draft', {'message_id': id})
        return jsonify({'success': True, 'done': False, 'job_id': job_id, 'message': '任务已提交，正在生成回复草稿'})
    except Exception as e:
        logger.error(f"提交AI回复草稿异步任务失败: {e}")
        return jsonify({'success': False, 'message': f'提交失败: {str(e)}'}), 500

@admin_bp.route('/message/<int:id>')
@admin_required
def view_message(id):
    try:
        # 查询消息
        message = db.get_or_404(Message, id)
        
        # 预加载发送者和接收者信息，避免在模板中引发懒加载
        sender = db.session.get(User, message.sender_id) if message.sender_id else None
        receiver = db.session.get(User, message.receiver_id) if message.receiver_id else None
        
        sender_info = None
        receiver_info = None
        
        if sender:
            sender_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=sender.id)).scalar_one_or_none()
        
        if receiver:
            receiver_info = db.session.execute(db.select(StudentInfo).filter_by(user_id=receiver.id)).scalar_one_or_none()
        
        # 如果当前管理员是接收者且消息未读，则标记为已读
        if message.receiver_id == current_user.id and not message.is_read:
            message.is_read = True
            db.session.commit()
            
        # 导入display_datetime
        from src.utils.time_helpers import display_datetime
            
        return render_template('admin/message_view.html',
                             message=message,
                             sender=sender,
                             receiver=receiver,
                             sender_info=sender_info,
                             receiver_info=receiver_info,
                             display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in view_message: {e}")
        flash('查看消息时出错', 'danger')
        return redirect(url_for('admin.messages'))

@admin_bp.route('/message/<int:id>/delete', methods=['POST'])
@admin_required
def delete_message(id):
    try:
        message = db.get_or_404(Message, id)
        
        # 验证当前用户是否是消息的发送者或接收者
        if message.sender_id != current_user.id and message.receiver_id != current_user.id:
            flash('您无权删除此消息', 'danger')
            return redirect(url_for('admin.messages'))
        
        # 删除消息
        db.session.delete(message)
        db.session.commit()
        
        log_action('delete_message', f'删除消息: {message.subject}')
        flash('消息已删除', 'success')
        return redirect(url_for('admin.messages'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_message: {e}")
        flash('删除消息时出错', 'danger')
        return redirect(url_for('admin.messages'))

@admin_bp.route('/system/fix_timezone', methods=['GET', 'POST'])
@admin_required
def fix_timezone():
    try:
        messages = []
        
        if request.method == 'POST':
            if 'confirm' in request.form:
                # 检查要修复的项目
                fix_activities = 'fix_activities' in request.form
                fix_posters = 'fix_posters' in request.form
                fix_notifications = 'fix_notifications' in request.form
                fix_other_dates = 'fix_other_dates' in request.form
                
                # 获取数据库连接
                conn = None
                cursor = None
                try:
                    # 使用应用配置的数据库URI
                    db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
                    
                    # 如果是PostgreSQL数据库
                    if db_uri.startswith('postgresql'):
                        import psycopg2
                        conn = psycopg2.connect(db_uri)
                        cursor = conn.cursor()
                        
                        # 设置数据库时区为UTC
                        cursor.execute("SET timezone TO 'UTC';")
                        messages.append("数据库时区已设置为UTC")
                        
                        # 修复活动表中的时间字段
                        if fix_activities:
                            logger.info("修复活动表中的时间字段...")
                            
                            # 1. 修复活动开始时间
                            cursor.execute("""
                            UPDATE activities
                            SET start_time = start_time AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE start_time IS NOT NULL;
                            """)
                            
                            # 2. 修复活动结束时间
                            cursor.execute("""
                            UPDATE activities
                            SET end_time = end_time AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE end_time IS NOT NULL;
                            """)
                            
                            # 3. 修复活动报名截止时间
                            cursor.execute("""
                            UPDATE activities
                            SET registration_deadline = registration_deadline AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE registration_deadline IS NOT NULL;
                            """)
                            
                            messages.append("活动时间字段已修复")
                        
                        # 修复海报路径问题
                        if fix_posters:
                            logger.info("修复活动海报路径问题...")
                            
                            # 获取所有活动的海报信息
                            cursor.execute("""
                            SELECT id, poster_image FROM activities
                            WHERE poster_image IS NOT NULL;
                            """)
                            activities_with_posters = cursor.fetchall()
                            
                            fixed_posters = 0
                            for activity_id, poster_path in activities_with_posters:
                                # 检查海报文件是否存在
                                if poster_path and 'None' in poster_path:
                                    # 修正海报路径：替换None为activity_id
                                    new_path = poster_path.replace('None', str(activity_id))
                                    
                                    # 更新数据库中的路径
                                    cursor.execute("""
                                    UPDATE activities
                                    SET poster_image = %s
                                    WHERE id = %s;
                                    """, (new_path, activity_id))
                                    
                                    fixed_posters += 1
                            
                            if fixed_posters > 0:
                                messages.append(f"已修复 {fixed_posters} 个活动海报路径")
                            else:
                                messages.append("未发现需要修复的海报路径")
                        
                        # 修复通知表中的时间字段
                        if fix_notifications:
                            logger.info("修复通知表中的时间字段...")
                            
                            # 1. 修复通知创建时间
                            cursor.execute("""
                            UPDATE notification
                            SET created_at = created_at AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE created_at IS NOT NULL;
                            """)
                            
                            # 2. 修复通知过期时间
                            cursor.execute("""
                            UPDATE notification
                            SET expiry_date = expiry_date AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE expiry_date IS NOT NULL;
                            """)
                            
                            # 修复通知已读表中的时间字段
                            cursor.execute("""
                            UPDATE notification_read
                            SET read_at = read_at AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE read_at IS NOT NULL;
                            """)
                            
                            messages.append("通知时间字段已修复")
                        
                        # 修复其他日期时间字段
                        if fix_other_dates:
                            logger.info("修复其他日期时间字段...")
                            
                            # 修复站内信表中的时间字段
                            cursor.execute("""
                            UPDATE message
                            SET created_at = created_at AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE created_at IS NOT NULL;
                            """)
                            
                            # 修复报名表中的时间字段
                            logger.info("修复报名表中的时间字段...")
                            
                            # 1. 修复报名时间
                            cursor.execute("""
                            UPDATE registrations
                            SET register_time = register_time AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE register_time IS NOT NULL;
                            """)
                            
                            # 2. 修复签到时间
                            cursor.execute("""
                            UPDATE registrations
                            SET check_in_time = check_in_time AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE check_in_time IS NOT NULL;
                            """)
                            
                            # 修复系统日志表中的时间字段
                            cursor.execute("""
                            UPDATE system_logs
                            SET created_at = created_at AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE created_at IS NOT NULL;
                            """)
                            
                            # 修复积分历史表中的时间字段
                            cursor.execute("""
                            UPDATE points_history
                            SET created_at = created_at AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE created_at IS NOT NULL;
                            """)
                            
                            # 修复活动评价表中的时间字段
                            cursor.execute("""
                            UPDATE activity_reviews
                            SET created_at = created_at AT TIME ZONE 'Asia/Shanghai' AT TIME ZONE 'UTC'
                            WHERE created_at IS NOT NULL;
                            """)
                            
                            messages.append("其他日期时间字段已修复")
                        
                        # 提交所有更改
                        conn.commit()
                        
                        # 记录日志
                        log_action('fix_timezone', '修复数据库时区问题')
                        messages.append("所有修复操作已完成")
                    else:
                        messages.append("当前数据库不是PostgreSQL，无需修复时区问题。")
                
                except Exception as e:
                    if conn:
                        conn.rollback()
                    logger.error(f"时区修复失败: {e}")
                    messages.append(f"修复失败: {str(e)}")
                finally:
                    if cursor:
                        cursor.close()
                    if conn:
                        conn.close()
        
        return render_template('admin/fix_timezone.html', messages=messages)
    except Exception as e:
        logger.error(f"Error in fix_timezone: {e}")
        flash('访问时区修复页面时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/activity/<int:id>/change_status', methods=['POST'])
@admin_required
def change_activity_status(id):
    try:
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '您只能管理所属社团活动状态'}), 403

        try:
            validate_csrf(request.form.get('csrf_token') or request.headers.get('X-CSRFToken') or '')
        except Exception:
            return jsonify({'success': False, 'message': '请求校验失败，请刷新后重试'}), 400

        new_status = request.form.get('status')
        
        if new_status not in ['draft', 'pending', 'approved', 'active', 'completed', 'cancelled']:
            return jsonify({'success': False, 'message': '无效的状态'}), 400
        
        old_status = activity.status
        activity.status = new_status
        
        # 如果状态变为已完成，记录完成时间
        if new_status == 'completed' and not activity.completed_at:
            activity.completed_at = datetime.now(pytz.utc)
            
        db.session.commit()
        _invalidate_home_page_caches()
        
        # 获取状态的中文名称
        status_names = {
            'draft': '草稿',
            'pending': '待审核',
            'approved': '已批准',
            'active': '进行中',
            'completed': '已完成',
            'cancelled': '已取消'
        }
        
        old_status_name = status_names.get(old_status, old_status)
        new_status_name = status_names.get(new_status, new_status)
        
        log_action('change_activity_status', f'更改活动状态: {activity.title}, 从 {old_status_name} 到 {new_status_name}')
        return jsonify({
            'success': True,
            'message': f'活动状态已从"{old_status_name}"更新为"{new_status_name}"',
            'old_status': old_status,
            'new_status': new_status
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"更改活动状态出错: {e}")
        return jsonify({'success': False, 'message': '更改活动状态时出错'}), 500

@admin_bp.route('/activity/<int:activity_id>/manual_checkin', methods=['POST'])
@admin_required
def manual_checkin(activity_id):
    try:
        registration_id = request.form.get('registration_id')
        registration = db.get_or_404(Registration, registration_id)
        
        # 确保登记与活动匹配
        if registration.activity_id != activity_id:
            return jsonify({'success': False, 'message': '登记记录与活动不匹配'}), 400
        
        # 获取活动和学生信息
        activity = db.session.get(Activity, activity_id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '您只能管理所属社团活动签到'}), 403
        student_info = StudentInfo.query.join(User).filter(User.id == registration.user_id).first()
        
        # 检查是否之前已经签到过（可能是被取消的签到）
        was_previously_checked_in = False
        
        # 查询积分历史记录，检查是否有取消参与的记录
        if student_info and activity:
            points = activity.points or (20 if activity.is_featured else 10)
            
            # 查找是否有取消参与该活动的积分记录
            cancel_record = PointsHistory.query.filter(
                PointsHistory.student_id == student_info.id,
                PointsHistory.activity_id == activity_id,
                PointsHistory.points == -points,
                PointsHistory.reason.like(f"取消参与活动：{activity.title}")
            ).first()
            
            was_previously_checked_in = cancel_record is not None
        
        # 记录原始状态
        original_status = registration.status
        
        # 设置签到时间
        registration.check_in_time = get_localized_now()
        
        # 更新状态为已参加
        registration.status = 'attended'
        
        # 添加积分
        if student_info and activity:
            points = activity.points or (20 if activity.is_featured else 10)
            
            # 如果之前取消过签到并扣除了积分，则需要加回积分
            if was_previously_checked_in:
                add_points(student_info.id, points, f"重新参与活动：{activity.title}", activity.id)
            # 如果是首次签到，也添加积分
            elif original_status != 'attended':
                add_points(student_info.id, points, f"参与活动：{activity.title}", activity.id)
        
        db.session.commit()
        
        log_action('manual_checkin', f'管理员手动签到: 活动={activity.title}, 学生={student_info.real_name if student_info else "未知"}')
        return jsonify({'success': True, 'message': '签到成功'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"手动签到出错: {e}")
        return jsonify({'success': False, 'message': '签到失败'}), 500

@admin_bp.route('/activity/<int:activity_id>/cancel_checkin', methods=['POST'])
@admin_required
def cancel_checkin(activity_id):
    try:
        registration_id = request.form.get('registration_id')
        registration = db.get_or_404(Registration, registration_id)
        
        # 确保登记与活动匹配
        if registration.activity_id != activity_id:
            return jsonify({'success': False, 'message': '登记记录与活动不匹配'}), 400

        activity = db.session.get(Activity, activity_id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'message': '您只能管理所属社团活动签到'}), 403
        
        # 判断原来是否已签到
        was_checked_in = registration.check_in_time is not None
        
        # 清除签到时间
        registration.check_in_time = None
        
        # 如果状态是已参与，改回已报名
        if registration.status == 'attended':
            registration.status = 'registered'
            
            # 扣除积分
            student_info = StudentInfo.query.join(User).filter(User.id == registration.user_id).first()
            
            if student_info and activity and was_checked_in:
                points = activity.points or (20 if activity.is_featured else 10)
                add_points(student_info.id, -points, f"取消参与活动：{activity.title}", activity.id)
        
        db.session.commit()
        
        log_action('cancel_checkin', f'取消签到: 活动ID={activity_id}, 登记ID={registration_id}')
        return jsonify({'success': True, 'message': '已取消签到'})
    except Exception as e:
        db.session.rollback()
        logger.error(f"取消签到出错: {e}")
        return jsonify({'success': False, 'message': '取消签到失败'}), 500

# 添加积分辅助函数
def add_points(student_id, points, reason, activity_id=None):
    """为学生添加或扣除积分
    
    Args:
        student_id: 学生信息ID
        points: 积分变化，正数为增加，负数为减少
        reason: 积分变化原因
        activity_id: 相关活动ID，可选
        
    Returns:
        bool: 操作是否成功
    """
    try:
        # 获取学生信息
        student_info = db.session.get(StudentInfo, student_id)
        if not student_info:
            logger.error(f"添加积分失败: 学生ID {student_id} 不存在")
            return False
        
        # 更新积分
        student_info.points = (student_info.points or 0) + points

        society_id = student_info.society_id
        if activity_id:
            activity = db.session.get(Activity, activity_id)
            if activity and activity.society_id:
                society_id = activity.society_id
        
        # 创建积分历史记录
        points_history = PointsHistory(
            student_id=student_id,
            points=points,
            reason=reason,
            activity_id=activity_id,
            society_id=society_id
        )
        
        db.session.add(points_history)
        db.session.commit()
        
        logger.info(f"积分更新成功: 学生ID {student_id}, 变化 {points}, 原因: {reason}")
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"添加积分失败: {e}")
        return False

# 添加时间本地化辅助函数
def localize_time(dt):
    """将UTC时间转换为北京时间
    
    Args:
        dt: 日期时间对象
        
    Returns:
        datetime: 北京时间
    """
    if dt is None:
        return None
    
    # 确保时间是UTC时区
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.UTC)
    
    # 转换为北京时间
    beijing_tz = pytz.timezone('Asia/Shanghai')
    return dt.astimezone(beijing_tz)

# 公告管理路由
@admin_bp.route('/announcements')
@admin_required
def announcements():
    try:
        _sync_published_announcements_to_notifications()
        page = request.args.get('page', 1, type=int)
        announcements = Announcement.query.order_by(Announcement.created_at.desc()).paginate(page=page, per_page=10)

        pending_requests = []
        if is_super_admin(current_user):
            pending_logs = db.session.execute(
                db.select(SystemLog)
                .filter(SystemLog.action == 'approval_request')
                .order_by(SystemLog.created_at.desc())
                .limit(200)
            ).scalars().all()
            for log in pending_logs:
                try:
                    details = json.loads(log.details or '{}')
                except Exception:
                    continue
                if details.get('status') == 'pending' and details.get('type') == 'announcement':
                    pending_requests.append({'log': log, 'details': details})
        
        # 确保display_datetime函数在模板中可用
        return render_template('admin/announcements.html', 
                              announcements=announcements,
                              pending_requests=pending_requests,
                              display_datetime=display_datetime)
    except Exception as e:
        logger.error(f"Error in announcements page: {e}")
        flash('加载公告列表时出错', 'danger')
        return redirect(url_for('admin.dashboard'))

@admin_bp.route('/announcement/create', methods=['GET', 'POST'])
@admin_required
@limiter.limit('12 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def create_announcement():
    try:
        # 创建Flask-WTF表单对象
        from flask_wtf import FlaskForm
        form = FlaskForm()
        
        if request.method == 'POST':
            logger.info("收到公告创建POST请求")
            if form.validate_on_submit():
                logger.info("CSRF验证通过")
                title = sanitize_plain_text(request.form.get('title'), max_length=120)
                content = sanitize_rich_html(request.form.get('content'), max_length=10000)
                status = request.form.get('status', 'published')
                
                if not title or not content:
                    flash('标题和内容不能为空', 'danger')
                    return redirect(url_for('admin.create_announcement'))

                if not is_super_admin(current_user):
                    _create_approval_request(
                        'announcement',
                        'create',
                        {
                            'title': title,
                            'content': content,
                            'status': status
                        }
                    )
                    flash('公告已提交审核，待总管理员批准后发布', 'info')
                    return redirect(url_for('admin.announcements'))
                
                # 创建公告
                announcement = Announcement(
                    title=title,
                    content=content,
                    status=status,
                    created_by=current_user.id,
                    created_at=get_localized_now(),
                    updated_at=get_localized_now()
                )
                
                db.session.add(announcement)
                db.session.commit()
                _invalidate_home_page_caches()

                _sync_published_announcements_to_notifications()
                
                log_action('create_announcement', f'创建公告: {title}')
                flash('公告创建成功', 'success')
                return redirect(url_for('admin.announcements'))
            else:
                logger.error(f"CSRF验证失败，表单错误: {form.errors}")
                flash('表单验证失败，请重试', 'danger')
        
        return render_template('admin/announcement_form.html', title='创建公告', form=form)
    except Exception as e:
        logger.error(f"Error in create_announcement: {e}")
        flash('创建公告时出错', 'danger')
        return redirect(url_for('admin.announcements'))

@admin_bp.route('/announcement/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
@limiter.limit('15 per minute', methods=['POST'], error_message='提交过于频繁，请稍后再试')
def edit_announcement(id):
    try:
        announcement = db.get_or_404(Announcement, id)
        
        # 创建Flask-WTF表单对象
        from flask_wtf import FlaskForm
        form = FlaskForm()
        
        if request.method == 'POST':
            logger.info("收到公告编辑POST请求")
            if form.validate_on_submit():
                logger.info("CSRF验证通过")
                title = sanitize_plain_text(request.form.get('title'), max_length=120)
                content = sanitize_rich_html(request.form.get('content'), max_length=10000)
                status = request.form.get('status', 'published')
                
                if not title or not content:
                    flash('标题和内容不能为空', 'danger')
                    return redirect(url_for('admin.edit_announcement', id=id))

                if not is_super_admin(current_user):
                    _create_approval_request(
                        'announcement',
                        'edit',
                        {
                            'id': id,
                            'title': title,
                            'content': content,
                            'status': status
                        },
                        target_id=id
                    )
                    flash('公告修改已提交审核，待总管理员批准后生效', 'info')
                    return redirect(url_for('admin.announcements'))
                
                # 更新公告
                old_title = announcement.title
                old_content = announcement.content

                announcement.title = title
                announcement.content = content
                announcement.status = status
                announcement.updated_at = get_localized_now()

                # 清理旧的同步通知，避免首页显示历史公告内容
                old_notification_ids = db.session.execute(
                    db.select(Notification.id).filter(
                        Notification.is_public == True,
                        Notification.created_by == announcement.created_by,
                        or_(
                            Notification.title == old_title,
                            Notification.content == old_content
                        )
                    )
                ).scalars().all()

                if old_notification_ids:
                    db.session.execute(
                        db.delete(NotificationRead).where(NotificationRead.notification_id.in_(old_notification_ids))
                    )

                Notification.query.filter(
                    Notification.is_public == True,
                    Notification.created_by == announcement.created_by,
                    or_(
                        Notification.title == old_title,
                        Notification.content == old_content
                    )
                ).delete(synchronize_session=False)
                
                db.session.commit()
                _invalidate_home_page_caches()

                _sync_published_announcements_to_notifications()
                
                log_action('edit_announcement', f'编辑公告: {title}')
                flash('公告更新成功', 'success')
                return redirect(url_for('admin.announcements'))
            else:
                logger.error(f"CSRF验证失败，表单错误: {form.errors}")
                flash('表单验证失败，请重试', 'danger')
        
        return render_template('admin/announcement_form.html', 
                              announcement=announcement,
                              title='编辑公告',
                              form=form)
    except Exception as e:
        logger.error(f"Error in edit_announcement: {e}")
        flash('编辑公告时出错', 'danger')
        return redirect(url_for('admin.announcements'))

@admin_bp.route('/announcement/<int:id>/delete', methods=['POST'])
@admin_required
def delete_announcement(id):
    try:
        announcement = db.get_or_404(Announcement, id)

        if not is_super_admin(current_user):
            _create_approval_request(
                'announcement',
                'delete',
                {
                    'id': id,
                    'title': announcement.title,
                    'content': announcement.content
                },
                target_id=id
            )
            flash('公告删除已提交审核，待总管理员批准后执行', 'info')
            return redirect(url_for('admin.announcements'))

        # 删除由该公告同步生成的公开通知，避免首页残留
        notification_ids = db.session.execute(
            db.select(Notification.id).filter(
                Notification.is_public == True,
                Notification.created_by == announcement.created_by,
                or_(
                    Notification.title == announcement.title,
                    Notification.content == announcement.content
                )
            )
        ).scalars().all()

        if notification_ids:
            db.session.execute(
                db.delete(NotificationRead).where(NotificationRead.notification_id.in_(notification_ids))
            )

        Notification.query.filter(
            Notification.is_public == True,
            Notification.created_by == announcement.created_by,
            or_(
                Notification.title == announcement.title,
                Notification.content == announcement.content
            )
        ).delete(synchronize_session=False)
        
        # 删除公告
        db.session.delete(announcement)
        db.session.commit()
        _invalidate_home_page_caches()
        
        log_action('delete_announcement', f'删除公告: {announcement.title}')
        flash('公告已删除', 'success')
        return redirect(url_for('admin.announcements'))
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error in delete_announcement: {e}")
        flash('删除公告时出错', 'danger')
        return redirect(url_for('admin.announcements'))

@admin_bp.route('/activity/<int:id>/notify_subs', methods=['POST'])
@admin_required
def notify_new_activity_subs(id):
    if request.headers.get('X-Requested-With') != 'XMLHttpRequest':
        return redirect(url_for('admin.activity_view', id=id))
        
    try:
        import subprocess, sys, os
        from threading import Thread
        
        # 权限校验
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            return jsonify({'success': False, 'msg': '无权限操作该社团的活动'})
            
        script_path = os.path.abspath(os.path.join(current_app.root_path, '..', 'scripts', 'publish_activity_notice.py'))
        
        # 异步调用之前写的提醒脚本
        def run_script():
            subprocess.Popen([sys.executable, script_path, str(id)])
            
        Thread(target=run_script).start()
        
        return jsonify({'success': True, 'msg': '已加入后台群发队列'})
    except Exception as e:
        return jsonify({'success': False, 'msg': str(e)})

@admin_bp.route('/activity/<int:id>/view')
@admin_required
def activity_view(id):
    try:
        # 获取活动详情
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能查看所属社团活动详情', 'danger')
            return redirect(url_for('admin.activities'))

        active_statuses = ['registered', 'attended']
        
        # 获取报名统计
        registrations_count = db.session.execute(
            db.select(func.count()).select_from(Registration).filter(
                Registration.activity_id == id,
                Registration.status.in_(active_statuses)
            )
        ).scalar()
        
        # 获取签到统计
        checkins_count = db.session.execute(
            db.select(func.count()).select_from(Registration).filter(
                Registration.activity_id == id,
                Registration.status.in_(active_statuses),
                or_(
                    Registration.status == 'attended',
                    Registration.check_in_time.is_not(None)
                )
            )
        ).scalar()
        
        # 获取报名学生列表
        registrations = Registration.query.filter(
            Registration.activity_id == id,
            Registration.status.in_(active_statuses)
        ).join(
            User, Registration.user_id == User.id
        ).join(
            StudentInfo, User.id == StudentInfo.user_id
        ).add_columns(
            Registration.id.label('id'),
            Registration.register_time.label('registration_time'),
            Registration.check_in_time,
            StudentInfo.real_name.label('student_name'),
            StudentInfo.student_id.label('student_id'),
            StudentInfo.college.label('college'),
            StudentInfo.major.label('major')
        ).all()
        
        # 导入display_datetime函数供模板使用
        from src.utils.time_helpers import display_datetime
        
        # 创建CSRF表单对象
        from flask_wtf import FlaskForm
        form = FlaskForm()
        
        return render_template('admin/activity_view.html',
                              activity=activity,
                              registrations_count=registrations_count,
                              checkins_count=checkins_count,
                              registrations=registrations,
                              display_datetime=display_datetime,
                              form=form)
    except Exception as e:
        logger.error(f"Error in activity_view: {e}")
        flash('查看活动详情时出错', 'danger')
        return redirect(url_for('admin.activities'))

@admin_bp.route('/activity/<int:id>/delete', methods=['POST'])
@admin_required
def delete_activity(id):
    try:
        # 获取活动
        activity = db.get_or_404(Activity, id)
        if not _scope_guard_activity(activity):
            flash('您只能删除所属社团活动', 'danger')
            return redirect(url_for('admin.activities'))
        
        # 检查是否强制删除
        force_delete = request.args.get('force', 'false').lower() == 'true'
        
        if force_delete:
            # 永久删除活动
            # 先清理所有依赖活动ID的关联数据，避免外键约束失败
            ActivityReview.query.filter_by(activity_id=id).delete(synchronize_session=False)
            ActivityCheckin.query.filter_by(activity_id=id).delete(synchronize_session=False)
            Registration.query.filter_by(activity_id=id).delete(synchronize_session=False)

            # 历史积分记录保留，但解除与活动的关联
            PointsHistory.query.filter_by(activity_id=id).update(
                {'activity_id': None},
                synchronize_session=False
            )

            # 清理活动-标签中间表
            db.session.execute(
                activity_tags.delete().where(activity_tags.c.activity_id == id)
            )
            
            # 删除活动
            db.session.delete(activity)
            db.session.commit()
            _invalidate_home_page_caches()
            
            # 记录操作
            log_action('force_delete_activity', f'永久删除活动: {activity.title}')
            
            flash(f'活动"{activity.title}"已永久删除', 'success')
        else:
            # 软删除（标记为已取消）
            activity.status = 'cancelled'
            db.session.commit()
            _invalidate_home_page_caches()
            
            # 记录操作
            log_action('cancel_activity', f'取消活动: {activity.title}')
            
            flash(f'活动"{activity.title}"已标记为已取消', 'success')
        
        return redirect(url_for('admin.activities'))
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error deleting activity: {e}")
        flash('删除活动时出错', 'danger')
        return redirect(url_for('admin.activities'))


@admin_bp.route('/approval-requests')
@admin_required
def approval_requests():
    if not is_super_admin(current_user):
        flash('仅总管理员可审核请求', 'danger')
        return redirect(url_for('admin.dashboard'))

    rows = db.session.execute(
        db.select(SystemLog)
        .filter(SystemLog.action == 'approval_request')
        .order_by(SystemLog.created_at.desc())
        .limit(500)
    ).scalars().all()

    requests_data = []
    for row in rows:
        try:
            details = json.loads(row.details or '{}')
        except Exception:
            continue
        requests_data.append({'log': row, 'details': details})

    return render_template('admin/approval_requests.html', requests_data=requests_data, display_datetime=display_datetime)


@admin_bp.route('/approval-request/<int:log_id>/approve', methods=['POST'])
@admin_required
def approve_request(log_id):
    if not is_super_admin(current_user):
        flash('仅总管理员可审核请求', 'danger')
        return redirect(url_for('admin.dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(url_for('admin.approval_requests'))

    log_row = db.get_or_404(SystemLog, log_id)
    try:
        details = json.loads(log_row.details or '{}')
    except Exception:
        details = {}

    if details.get('status') != 'pending':
        flash('该请求已处理，无需重复审核', 'warning')
        return redirect(url_for('admin.approval_requests'))

    req_type = details.get('type')
    req_action = details.get('action')
    payload = details.get('payload') or {}

    try:
        if req_type == 'notification':
            if req_action == 'create':
                expiry_date = None
                expiry_date_str = (payload.get('expiry_date') or '').strip()
                if expiry_date_str:
                    try:
                        expiry_date = pytz.utc.localize(datetime.strptime(expiry_date_str, '%Y-%m-%d'))
                    except Exception:
                        expiry_date = None
                db.session.add(Notification(
                    title=sanitize_plain_text(payload.get('title'), max_length=120),
                    content=sanitize_rich_html(payload.get('content'), max_length=6000),
                    is_important=bool(payload.get('is_important')),
                    created_at=datetime.now(pytz.utc),
                    created_by=details.get('requester_id'),
                    expiry_date=expiry_date,
                    is_public=True
                ))
            elif req_action == 'edit':
                nid = payload.get('id')
                notice = db.session.get(Notification, nid)
                if notice:
                    notice.title = sanitize_plain_text(payload.get('title'), max_length=120)
                    notice.content = sanitize_rich_html(payload.get('content'), max_length=6000)
                    notice.is_important = bool(payload.get('is_important'))
                    expiry_date_str = (payload.get('expiry_date') or '').strip()
                    if expiry_date_str:
                        try:
                            notice.expiry_date = pytz.utc.localize(datetime.strptime(expiry_date_str, '%Y-%m-%d'))
                        except Exception:
                            notice.expiry_date = None
                    else:
                        notice.expiry_date = None
            elif req_action == 'delete':
                nid = payload.get('id')
                notice = db.session.get(Notification, nid)
                if notice:
                    db.session.execute(db.delete(NotificationRead).where(NotificationRead.notification_id == notice.id))
                    db.session.delete(notice)

        elif req_type == 'tag':
            if req_action == 'create':
                name = (payload.get('name') or '').strip()
                if name and not db.session.execute(db.select(Tag).filter_by(name=name)).scalar_one_or_none():
                    db.session.add(Tag(name=name, color=(payload.get('color') or 'primary')))
            elif req_action == 'edit':
                tag_id = payload.get('id')
                tag = db.session.get(Tag, tag_id)
                if tag:
                    new_name = (payload.get('name') or '').strip()
                    if new_name:
                        dup = db.session.execute(db.select(Tag).filter(Tag.name == new_name, Tag.id != tag.id)).scalar_one_or_none()
                        if not dup:
                            tag.name = new_name
                    tag.color = (payload.get('color') or tag.color or 'primary')
            elif req_action == 'delete':
                tag_id = payload.get('id')
                tag = db.session.get(Tag, tag_id)
                if tag:
                    for activity in tag.activities:
                        activity.tags.remove(tag)
                    for student in tag.students:
                        student.tags.remove(tag)
                    db.session.delete(tag)

        elif req_type == 'announcement':
            if req_action == 'create':
                ann = Announcement(
                    title=sanitize_plain_text(payload.get('title'), max_length=120),
                    content=sanitize_rich_html(payload.get('content'), max_length=10000),
                    status=(payload.get('status') or 'published').strip() or 'published',
                    created_by=details.get('requester_id'),
                    created_at=get_localized_now(),
                    updated_at=get_localized_now()
                )
                db.session.add(ann)
                db.session.flush()
                _sync_published_announcements_to_notifications()
            elif req_action == 'edit':
                ann_id = payload.get('id')
                ann = db.session.get(Announcement, ann_id)
                if ann:
                    old_title = ann.title
                    old_content = ann.content

                    ann.title = sanitize_plain_text(payload.get('title'), max_length=120)
                    ann.content = sanitize_rich_html(payload.get('content'), max_length=10000)
                    ann.status = (payload.get('status') or ann.status or 'published').strip()
                    ann.updated_at = get_localized_now()

                    old_notification_ids = db.session.execute(
                        db.select(Notification.id).filter(
                            Notification.is_public == True,
                            Notification.created_by == ann.created_by,
                            or_(
                                Notification.title == old_title,
                                Notification.content == old_content
                            )
                        )
                    ).scalars().all()

                    if old_notification_ids:
                        db.session.execute(
                            db.delete(NotificationRead).where(NotificationRead.notification_id.in_(old_notification_ids))
                        )
                    Notification.query.filter(
                        Notification.is_public == True,
                        Notification.created_by == ann.created_by,
                        or_(
                            Notification.title == old_title,
                            Notification.content == old_content
                        )
                    ).delete(synchronize_session=False)

                    _sync_published_announcements_to_notifications()
            elif req_action == 'delete':
                ann_id = payload.get('id')
                ann = db.session.get(Announcement, ann_id)
                if ann:
                    notification_ids = db.session.execute(
                        db.select(Notification.id).filter(
                            Notification.is_public == True,
                            Notification.created_by == ann.created_by,
                            or_(
                                Notification.title == ann.title,
                                Notification.content == ann.content
                            )
                        )
                    ).scalars().all()
                    if notification_ids:
                        db.session.execute(
                            db.delete(NotificationRead).where(NotificationRead.notification_id.in_(notification_ids))
                        )
                    Notification.query.filter(
                        Notification.is_public == True,
                        Notification.created_by == ann.created_by,
                        or_(
                            Notification.title == ann.title,
                            Notification.content == ann.content
                        )
                    ).delete(synchronize_session=False)
                    db.session.delete(ann)

        details['status'] = 'approved'
        details['reviewed_by'] = current_user.id
        details['reviewed_at'] = datetime.now(pytz.utc).isoformat()
        log_row.details = json.dumps(details, ensure_ascii=False)
        _notify_approval_result(details.get('requester_id'), req_type, req_action, True)
        db.session.commit()
        flash('审核通过并已执行', 'success')
    except Exception as e:
        db.session.rollback()
        logger.error(f"审批执行失败 log_id={log_id}: {e}", exc_info=True)
        flash('审核执行失败，请稍后重试', 'danger')

    return redirect(url_for('admin.approval_requests'))


@admin_bp.route('/approval-request/<int:log_id>/reject', methods=['POST'])
@admin_required
def reject_request(log_id):
    if not is_super_admin(current_user):
        flash('仅总管理员可审核请求', 'danger')
        return redirect(url_for('admin.dashboard'))

    try:
        validate_csrf(request.form.get('csrf_token', ''))
    except Exception:
        flash('请求校验失败，请刷新页面后重试', 'danger')
        return redirect(url_for('admin.approval_requests'))

    log_row = db.get_or_404(SystemLog, log_id)
    try:
        details = json.loads(log_row.details or '{}')
    except Exception:
        details = {}

    if details.get('status') != 'pending':
        flash('该请求已处理，无需重复审核', 'warning')
        return redirect(url_for('admin.approval_requests'))

    details['status'] = 'rejected'
    details['reviewed_by'] = current_user.id
    details['reviewed_at'] = datetime.now(pytz.utc).isoformat()
    details['reject_reason'] = (request.form.get('reject_reason') or '').strip()
    log_row.details = json.dumps(details, ensure_ascii=False)
    _notify_approval_result(
        details.get('requester_id'),
        details.get('type'),
        details.get('action'),
        False,
        details.get('reject_reason', '')
    )
    db.session.commit()
    flash('已驳回该审核请求', 'info')
    return redirect(url_for('admin.approval_requests'))
