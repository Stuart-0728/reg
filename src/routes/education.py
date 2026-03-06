import sys
import os
import json
import uuid
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import current_user, login_required
from flask_wtf.csrf import CSRFProtect, generate_csrf
from src.models import db, User, Role
from src.routes.utils import log_action
from src.utils.time_helpers import get_localized_now
import logging

# 配置日志
logger = logging.getLogger(__name__)

# 创建蓝图
education_bp = Blueprint('education', __name__)

@education_bp.route('/resources')
def resources():
    """显示教育资源页面"""
    try:
        # 网络教育资源列表
        online_resources = [
            {
                "name": "国家中小学智慧教育平台",
                "url": "https://www.zxx.edu.cn/",
                "icon": "fa-school",
                "description": "国家级中小学教育平台，提供丰富的教学资源和教育服务"
            },
            {
                "name": "重庆师范大学官网",
                "url": "https://www.cqnu.edu.cn/",
                "icon": "fa-university",
                "description": "重庆师范大学官方网站，提供学校新闻、通知和资源"
            },
            {
                "name": "中国教育资源网",
                "url": "http://www.cersp.com/",
                "icon": "fa-book",
                "description": "综合性教育资源门户，提供各学科教学资源和教育新闻"
            },
            {
                "name": "学科网",
                "url": "https://www.zxxk.com/",
                "icon": "fa-pencil-alt",
                "description": "提供中小学各学科教案、试卷、课件等教学资源"
            },
            {
                "name": "全国教师管理信息系统",
                "url": "https://www.jszg.edu.cn/",
                "icon": "fa-id-card",
                "description": "教师资格证查询和管理的官方平台"
            },
            {
                "name": "中国知网",
                "url": "https://www.cnki.net/",
                "icon": "fa-file-alt",
                "description": "中国知识基础设施工程，提供学术论文和期刊资源"
            },
            {
                "name": "物理实验在线",
                "url": "http://en.wuli.ac.cn/",
                "icon": "fa-atom",
                "description": "提供物理实验的在线模拟和教学资源"
            },
            {
                "name": "中国化学教育网",
                "url": "http://www.chemhtml.com/",
                "icon": "fa-flask",
                "description": "化学教育资源平台，提供教学课件和实验指导"
            },
            {
                "name": "中国数字教育资源公共服务平台",
                "url": "http://www.eduyun.cn/",
                "icon": "fa-cloud",
                "description": "教育部主管的数字教育资源服务平台"
            },
            {
                "name": "PhET互动科学模拟",
                "url": "https://phet.colorado.edu/zh_CN/",
                "icon": "fa-microscope",
                "description": "科罗拉多大学提供的互动科学模拟实验平台"
            }
        ]
        
        # 本地教育资源列表
        local_resources = [
            {
                "name": "自由落体运动探究",
                "url": url_for('education.free_fall'),
                "icon": "fa-arrow-down",
                "description": "通过交互式实验探究自由落体运动规律，理解伽利略的贡献"
            },
            {
                "name": "洛伦兹力2D实验",
                "url": url_for('education.lorentz_force_2d'),
                "icon": "fa-magnet",
                "description": "通过交互式实验探究带电粒子在磁场中的运动，理解洛伦兹力的作用"
            },
            {
                "name": "磁力耦合器模拟",
                "url": url_for('education.magnetic_coupler'),
                "icon": "fa-sync",
                "description": "通过交互式3D模型探究磁力耦合器的工作原理与应用"
            },
            {
                "name": "多普勒效应演示",
                "url": url_for('education.doppler_effect'),
                "icon": "fa-wave-square",
                "description": "通过麦克风实时分析声波频率变化来测量速度，理解多普勒效应原理"
            }
        ]
        
        logger.info("正在加载教育资源页面")
        return render_template('education/resources.html', 
                            online_resources=online_resources,
                            local_resources=local_resources)
    except Exception as e:
        logger.error(f"加载教育资源页面出错: {e}", exc_info=True)
        flash('加载教育资源页面时出错，请稍后再试', 'danger')
        return redirect(url_for('main.index'))

@education_bp.route('/free-fall')
def free_fall():
    """自由落体运动探究页面"""
    try:
        logger.info("正在加载自由落体运动探究页面")
        return render_template('education/free_fall.html')
    except Exception as e:
        logger.error(f"加载自由落体运动探究页面出错: {e}", exc_info=True)
        flash('加载自由落体运动探究页面时出错，请稍后再试', 'danger')
        return redirect(url_for('education.resources'))

@education_bp.route('/lorentz-force-2d')
def lorentz_force_2d():
    """洛伦兹力2D实验探究页面"""
    try:
        logger.info("正在加载洛伦兹力2D实验探究页面")
        return render_template('education/lorentz_force_2d.html')
    except Exception as e:
        logger.error(f"加载洛伦兹力2D实验探究页面出错: {e}", exc_info=True)
        flash('加载洛伦兹力2D实验探究页面时出错，请稍后再试', 'danger')
        return redirect(url_for('education.resources'))

@education_bp.route('/magnetic-coupler')
def magnetic_coupler():
    """磁力耦合器探究页面"""
    try:
        logger.info("正在加载磁力耦合器探究页面")
        return render_template('education/magnetic_coupler.html')
    except Exception as e:
        logger.error(f"加载磁力耦合器探究页面出错: {e}", exc_info=True)
        flash('加载磁力耦合器探究页面时出错，请稍后再试', 'danger')
        return redirect(url_for('education.resources'))

@education_bp.route('/doppler-effect')
def doppler_effect():
    """多普勒效应演示页面"""
    try:
        logger.info("正在加载多普勒效应演示页面")
        return render_template('education/doppler_effect.html')
    except Exception as e:
        logger.error(f"加载多普勒效应演示页面出错: {e}", exc_info=True)
        flash('加载多普勒效应演示页面时出错，请稍后再试', 'danger')
        return redirect(url_for('education.resources'))

@education_bp.route('/api/gemini', methods=['POST'])
def gemini_api():
    """处理AI API请求"""
    try:
        # 获取请求数据
        data = request.get_json()
        user_id = current_user.id if current_user.is_authenticated else "匿名用户"
        current_app.logger.info(f"接收到API请求，用户: {user_id}")
        
        if not data or 'prompt' not in data:
            current_app.logger.warning(f"API请求格式错误，缺少prompt字段")
            return jsonify({
                'success': False,
                'content': '请求格式错误，缺少prompt字段'
            })
        
        prompt = data['prompt']
        current_app.logger.info(f"提示词长度: {len(prompt)}")
        
        # 记录API调用
        if current_user.is_authenticated:
            log_action(
                action="education_ai_api",
                details=f"调用教育资源AI API，提示词长度：{len(prompt)}",
                user_id=current_user.id
            )
        
        # 获取API密钥
        api_key = os.environ.get("ARK_API_KEY")
        if not api_key:
            # 尝试从应用配置获取API密钥
            api_key = current_app.config.get('VOLCANO_API_KEY')
            if not api_key:
                current_app.logger.error("未找到API密钥，既没有ARK_API_KEY环境变量，也没有VOLCANO_API_KEY配置")
                return jsonify({
                    'success': False,
                    'content': '系统未配置API密钥，无法使用AI功能'
                })
        
        # 发送请求 - 使用正确的火山引擎端点
        url = current_app.config.get('VOLCANO_API_URL', "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        # 构建请求负载
        payload = {
            "model": "deepseek-v3-250324",  # 使用官方推荐模型
            "messages": [
                {"role": "system", "content": "请直接回答用户的问题，不要自称是任何角色。回答应该简洁、准确、有教育意义。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        
        # 记录请求开始
        current_app.logger.info(f"正在向AI API发送请求: {url}, 提示词长度：{len(prompt)}")
        
        try:
            # 添加超时参数，避免长时间等待
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            
            # 记录响应状态
            current_app.logger.info(f"AI API响应状态码：{response.status_code}")
            
            if response.status_code != 200:
                current_app.logger.error(f"AI API调用失败，状态码：{response.status_code}，响应：{response.text}")
                return jsonify({
                    'success': False,
                    'content': f"AI服务暂时不可用，请稍后再试。错误码：{response.status_code}"
                })
            
            response_data = response.json()
            
            # 使用AI标准响应格式
            if 'choices' in response_data and len(response_data['choices']) > 0:
                ai_response = response_data['choices'][0]['message']['content']
                
                # 记录成功响应
                current_app.logger.info(f"成功获取AI响应，长度：{len(ai_response)}")
                
                return jsonify({
                    'success': True,
                    'content': ai_response
                })
            else:
                current_app.logger.error(f"API响应格式异常：{response_data}")
                return jsonify({
                    'success': False,
                    'content': "AI响应格式错误，请稍后再试"
                })
                
        except requests.Timeout:
            current_app.logger.error("AI API请求超时")
            return jsonify({
                'success': False,
                'content': "AI服务响应超时，请稍后再试"
            })
        
        except requests.ConnectionError:
            current_app.logger.error("连接AI服务失败")
            return jsonify({
                'success': False,
                'content': "无法连接到AI服务，请检查网络连接"
            })
    
    except Exception as e:
        current_app.logger.error(f"AI API调用发生未知错误: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'content': "处理请求时发生错误，请稍后再试"
        })

@education_bp.route('/ai_chat_clear_history', methods=['POST'])
def ai_chat_clear_history():
    """清除AI聊天历史记录"""
    try:
        # 检查请求是否包含有效的CSRF令牌
        if not current_app.config.get('TESTING', False):  # 非测试环境下检查CSRF
            csrf_token = request.headers.get('X-CSRFToken')
            if not csrf_token:
                logger.warning("清除AI聊天历史时缺少CSRF令牌")
                return jsonify({
                    'success': False,
                    'message': 'CSRF验证失败'
                }), 400

        # 记录操作
        user_id = current_user.id if current_user.is_authenticated else None
        logger.info(f"用户 {user_id or '匿名用户'} 请求清除AI聊天历史")
        
        if user_id:
            log_action(
                action="education_ai_clear_history",
                details="清除教育资源AI聊天历史",
                user_id=user_id
            )
        
        # 这里我们实际上并不需要在服务器端存储任何内容，
        # 因为聊天历史是在客户端存储的
        # 但我们仍然返回成功，让前端知道清除操作已确认
        return jsonify({
            'success': True,
            'message': '聊天历史已清除'
        })
    
    except Exception as e:
        logger.error(f"清除AI聊天历史时出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': '清除聊天历史时出错，请稍后再试'
        }), 500

@education_bp.route('/test')
def test_route():
    """测试路由"""
    try:
        return jsonify({
            'success': True,
            'message': '教育资源路由运行正常'
        })
    except Exception as e:
        current_app.logger.error(f"测试路由出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f"测试路由出错: {str(e)}"
        })

@education_bp.route('/test-static')
def test_static():
    """测试静态文件路由"""
    try:
        return render_template('education/test.html')
    except Exception as e:
        current_app.logger.error(f"测试静态文件路由出错: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f"测试静态文件路由出错: {str(e)}"
        }) 