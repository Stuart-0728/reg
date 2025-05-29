from flask import Blueprint, render_template, redirect, url_for, request
from datetime import datetime

from src.models import db, Activity, Registration

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    # 获取最新活动
    latest_activities = (
        Activity.query
        .filter_by(status='active')
        .order_by(Activity.created_at.desc())
        .limit(6)
        .all()
    )
    
    # 获取热门活动（报名人数最多的，且未过报名截止）
    popular_query = (
        db.session.query(
            Activity,
            db.func.count(Registration.id).label('reg_count')
        )
        .join(Registration, Registration.activity_id == Activity.id)
        .filter(
            Activity.status == 'active',
            Activity.registration_deadline >= datetime.now()
        )
        .group_by(Activity.id)
        .order_by(db.desc('reg_count'))
        .limit(3)
    )
    popular_activities = [act for act, count in popular_query.all()]
    
    # 获取即将截止的活动
    closing_soon = (
        Activity.query
        .filter(
            Activity.status == 'active',
            Activity.registration_deadline >= datetime.now()
        )
        .order_by(Activity.registration_deadline)
        .limit(3)
        .all()
    )
    
    return render_template(
        'main/index.html',
        latest_activities=latest_activities,
        popular_activities=popular_activities,
        closing_soon=closing_soon
    )

@main_bp.route('/about')
def about():
    return render_template('main/about.html')

@main_bp.route('/search')
def search():
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    
    if not query:
        return redirect(url_for('main.index'))
    
    # 搜索活动（分页）
    activities = (
        Activity.query
        .filter(
            (Activity.title.contains(query)) |
            (Activity.description.contains(query)) |
            (Activity.location.contains(query))
        )
        .order_by(Activity.created_at.desc())
        .paginate(page=page, per_page=10)
    )
    
    return render_template(
        'main/search.html',
        activities=activities,
        query=query
    )
