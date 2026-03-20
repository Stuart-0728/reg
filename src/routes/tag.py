from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from src.models import db, Tag, Activity, activity_tags
from src.routes.utils import admin_required, is_super_admin

tag_bp = Blueprint('tag', __name__, url_prefix='/tags')

# 标签管理页面
@tag_bp.route('/', methods=['GET'])
@admin_required
def tag_list():
    return redirect(url_for('admin.manage_tags'))

# 新建标签
@tag_bp.route('/create', methods=['POST'])
@admin_required
def create_tag():
    if not is_super_admin(current_user):
        flash('该入口已停用，请使用管理后台审核流程', 'warning')
        return redirect(url_for('admin.manage_tags'))
    name = request.form.get('name')
    desc = request.form.get('description')
    if not name:
        flash('标签名不能为空', 'danger')
        return redirect(url_for('tag.tag_list'))
    if db.session.execute(db.select(Tag).filter_by(name=name)).scalar_one_or_none():
        flash('标签已存在', 'warning')
        return redirect(url_for('tag.tag_list'))
    tag = Tag(name=name, description=desc)
    db.session.add(tag)
    db.session.commit()
    flash('标签创建成功', 'success')
    return redirect(url_for('tag.tag_list'))

# 删除标签
@tag_bp.route('/delete/<int:tag_id>', methods=['POST'])
@admin_required
def delete_tag(tag_id):
    if not is_super_admin(current_user):
        flash('该入口已停用，请使用管理后台审核流程', 'warning')
        return redirect(url_for('admin.manage_tags'))
    tag = db.get_or_404(Tag, tag_id)
    db.session.delete(tag)
    db.session.commit()
    flash('标签已删除', 'success')
    return redirect(url_for('tag.tag_list'))

# 活动打标签（AJAX接口）
@tag_bp.route('/assign', methods=['POST'])
@admin_required
def assign_tag():
    if not is_super_admin(current_user):
        return jsonify({'success': False, 'msg': '该入口已停用，请使用管理后台审核流程'}), 403
    activity_id = request.form.get('activity_id')
    tag_ids = request.form.getlist('tag_ids')
    activity = db.session.get(Activity, activity_id)
    if not activity:
        return jsonify({'success': False, 'msg': '活动不存在'})
    # 清空原有标签
    activity.tags = []
    # 添加新标签
    if tag_ids:
        tags = db.session.execute(db.select(Tag).filter(Tag.id.in_(tag_ids))).scalars().all()
        activity.tags = tags
    db.session.commit()
    return jsonify({'success': True})
