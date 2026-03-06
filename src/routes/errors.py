from flask import Blueprint, render_template, current_app, request, jsonify
import logging

logger = logging.getLogger(__name__)

# 创建错误处理蓝图
errors_bp = Blueprint('errors', __name__)

@errors_bp.app_errorhandler(404)
def page_not_found(e):
    logger.warning(f"404 错误: {request.path}")

    # 如果是API请求，返回JSON
    if request.path.startswith('/api/') or request.path.startswith('/admin/api/') or request.path.startswith('/utils/'):
        return jsonify({
            'success': False,
            'error': 'API端点不存在',
            'message': '请求的API端点不存在'
        }), 404

    return render_template('404.html'), 404

@errors_bp.app_errorhandler(500)
def internal_server_error(e):
    logger.error(f"500 错误: {e}")

    # 如果是API请求，返回JSON
    if request.path.startswith('/api/') or request.path.startswith('/admin/api/') or request.path.startswith('/utils/'):
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'message': '服务器处理请求时发生错误'
        }), 500

    return render_template('500.html'), 500

@errors_bp.app_errorhandler(403)
def forbidden(e):
    logger.warning(f"403 错误: {request.path}")

    # 如果是API请求，返回JSON
    if request.path.startswith('/api/') or request.path.startswith('/admin/api/') or request.path.startswith('/utils/'):
        return jsonify({
            'success': False,
            'error': '权限不足',
            'message': '您没有权限访问此资源'
        }), 403

    return render_template('404.html'), 403

@errors_bp.app_errorhandler(400)
def bad_request(e):
    logger.warning(f"400 错误: {request.path}")

    # 如果是API请求，返回JSON
    if request.path.startswith('/api/') or request.path.startswith('/admin/api/') or request.path.startswith('/utils/'):
        return jsonify({
            'success': False,
            'error': '请求格式错误',
            'message': '请求参数格式不正确'
        }), 400

    return render_template('404.html'), 400

# 保留原来的函数以兼容旧代码
def register_error_handlers(app):
    app.register_blueprint(errors_bp) 