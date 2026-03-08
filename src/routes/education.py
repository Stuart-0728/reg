import os
import requests
import logging
from math import ceil

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify, send_from_directory
from flask_login import current_user

from src.routes.utils import log_action

logger = logging.getLogger(__name__)

education_bp = Blueprint('education', __name__)


class ListPagination:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = ceil(total / per_page) if per_page > 0 else 1
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1 if self.has_prev else None
        self.next_num = page + 1 if self.has_next else None

    def iter_pages(self, left_edge=2, left_current=2, right_current=2, right_edge=2):
        if self.pages <= 0:
            return

        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def paginate_list(items, page, per_page):
    if page < 1:
        page = 1
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    paged_items = items[start:end]
    return ListPagination(paged_items, page, per_page, total)


ONLINE_RESOURCES = [
    {
        "name": "国家中小学智慧教育平台",
        "url": "https://www.zxx.edu.cn/",
        "icon": "fa-school",
        "description": "国家级中小学教育平台，提供丰富的教学资源和教育服务",
    },
    {
        "name": "重庆师范大学官网",
        "url": "https://www.cqnu.edu.cn/",
        "icon": "fa-university",
        "description": "重庆师范大学官方网站，提供学校新闻、通知和资源",
    },
    {
        "name": "中国教育资源网",
        "url": "http://www.cersp.com/",
        "icon": "fa-book",
        "description": "综合性教育资源门户，提供各学科教学资源和教育新闻",
    },
    {
        "name": "学科网",
        "url": "https://www.zxxk.com/",
        "icon": "fa-pencil-alt",
        "description": "提供中小学各学科教案、试卷、课件等教学资源",
    },
    {
        "name": "全国教师管理信息系统",
        "url": "https://www.jszg.edu.cn/",
        "icon": "fa-id-card",
        "description": "教师资格证查询和管理的官方平台",
    },
    {
        "name": "中国知网",
        "url": "https://www.cnki.net/",
        "icon": "fa-file-alt",
        "description": "中国知识基础设施工程，提供学术论文和期刊资源",
    },
    {
        "name": "物理实验在线",
        "url": "http://en.wuli.ac.cn/",
        "icon": "fa-atom",
        "description": "提供物理实验的在线模拟和教学资源",
    },
    {
        "name": "中国化学教育网",
        "url": "http://www.chemhtml.com/",
        "icon": "fa-flask",
        "description": "化学教育资源平台，提供教学课件和实验指导",
    },
    {
        "name": "中国数字教育资源公共服务平台",
        "url": "http://www.eduyun.cn/",
        "icon": "fa-cloud",
        "description": "教育部主管的数字教育资源服务平台",
    },
    {
        "name": "PhET 互动科学模拟",
        "url": "https://phet.colorado.edu/zh_CN/",
        "icon": "fa-microscope",
        "description": "科罗拉多大学提供的互动科学模拟实验平台",
    },
]


LOCAL_RESOURCES = [
    {
        "name": "自由落体运动探究",
        "endpoint": "education.free_fall",
        "icon": "fa-arrow-down",
        "description": "交互式探索自由落体运动规律，理解位移、速度与时间关系",
    },
    {
        "name": "洛伦兹力 2D 实验",
        "endpoint": "education.lorentz_force_2d",
        "icon": "fa-magnet",
        "description": "观察带电粒子在磁场中的轨迹变化，掌握洛伦兹力方向与大小",
    },
    {
        "name": "洛伦兹力 3D 可视化",
        "endpoint": "education.lorentz_force_3d",
        "icon": "fa-cube",
        "description": "以 3D 视角理解空间磁场中粒子运动，提升空间想象能力",
    },
    {
        "name": "波的干涉实验",
        "endpoint": "education.wave_interference",
        "icon": "fa-water",
        "description": "模拟双波源叠加，观察干涉条纹与相位关系",
    },
    {
        "name": "磁力耦合器模拟",
        "endpoint": "education.magnetic_coupler",
        "icon": "fa-sync",
        "description": "通过 3D 模型理解磁力耦合传动原理与工程应用",
    },
    {
        "name": "多普勒效应演示",
        "endpoint": "education.doppler_effect",
        "icon": "fa-wave-square",
        "description": "结合声音频率变化分析相对运动与观测频移",
    },
    {
        "name": "电梯超重失重实验",
        "endpoint": "education.experiment_elevator_acceleration",
        "icon": "fa-building",
        "description": "利用手机传感器分析电梯运动中的超重与失重现象",
    },
    {
        "name": "抛体运动实验",
        "endpoint": "education.experiment_projectile_motion",
        "icon": "fa-rocket",
        "description": "动态调整初速度和角度，验证抛体轨迹规律",
    },
    {
        "name": "双缝干涉实验",
        "endpoint": "education.experiment_double_slit",
        "icon": "fa-solar-panel",
        "description": "模拟光学双缝干涉，理解条纹间距与波长关系",
    },
    {
        "name": "薄透镜成像实验",
        "endpoint": "education.experiment_thin_lens",
        "icon": "fa-search",
        "description": "可视化凸透镜成像过程，掌握物像关系与焦距",
    },
    {
        "name": "RC 电路实验",
        "endpoint": "education.experiment_rc_circuit",
        "icon": "fa-bolt",
        "description": "探索电容充放电过程，理解时间常数与电压变化",
    },
    {
        "name": "共振管实验",
        "endpoint": "education.experiment_resonance_tube",
        "icon": "fa-music",
        "description": "通过声学共振现象测量并分析波长与频率",
    },
    {
        "name": "单摆相机实验",
        "endpoint": "education.experiment_pendulum_camera",
        "icon": "fa-video",
        "description": "结合摄像追踪分析单摆周期与摆长关系",
    },
    {
        "name": "设备运动重力实验",
        "endpoint": "education.experiment_device_motion_g",
        "icon": "fa-mobile-alt",
        "description": "采集设备重力与运动数据，理解加速度分解",
    },
    {
        "name": "石头剪刀布 AI 对战",
        "endpoint": "education.rock_paper_scissors",
        "icon": "fa-hand-rock",
        "description": "通过博弈小游戏学习策略分析与概率思维",
    },
]


@education_bp.route('/')
def education_home():
    return redirect(url_for('education.resources'))


@education_bp.route('/resources')
def resources():
    try:
        online_page = request.args.get('online_page', 1, type=int)
        local_page = request.args.get('local_page', 1, type=int)

        online_items = ONLINE_RESOURCES.copy()
        local_items = []
        for item in LOCAL_RESOURCES:
            local_items.append(
                {
                    **item,
                    "url": url_for(item["endpoint"]),
                }
            )

        online_pagination = paginate_list(online_items, online_page, per_page=6)
        local_pagination = paginate_list(local_items, local_page, per_page=9)

        return render_template(
            'education/resources.html',
            online_pagination=online_pagination,
            local_pagination=local_pagination,
            ai_login_required=not current_user.is_authenticated,
        )
    except Exception as e:
        logger.error(f"加载教育资源页面出错: {e}", exc_info=True)
        flash('加载教育资源页面时出错，请稍后再试', 'danger')
        return redirect(url_for('main.index'))


@education_bp.route('/auth-status')
def auth_status():
    return jsonify({"authenticated": bool(current_user.is_authenticated)})


@education_bp.route('/assets/<path:filename>')
def education_assets(filename):
    assets_dir = os.path.join(current_app.root_path, 'templates', 'education', 'assets')
    return send_from_directory(assets_dir, filename)


@education_bp.route('/free-fall')
def free_fall():
    return render_template('education/free_fall.html')


@education_bp.route('/lorentz-force-2d')
def lorentz_force_2d():
    return render_template('education/lorentz_force_2d.html')


@education_bp.route('/lorentz-force-3d')
def lorentz_force_3d():
    return render_template('education/lorentz_force_3d.html')


@education_bp.route('/wave-interference')
def wave_interference():
    return render_template('education/wave_interference.html')


@education_bp.route('/magnetic-coupler')
def magnetic_coupler():
    return render_template('education/magnetic_coupler.html')


@education_bp.route('/doppler-effect')
def doppler_effect():
    return render_template('education/doppler_effect.html')


@education_bp.route('/experiment-elevator-acceleration')
def experiment_elevator_acceleration():
    return render_template('education/experiment_elevator_acceleration.html')


@education_bp.route('/experiment-projectile-motion')
def experiment_projectile_motion():
    return render_template('education/experiment_projectile_motion.html')


@education_bp.route('/experiment-double-slit')
def experiment_double_slit():
    return render_template('education/experiment_double_slit.html')


@education_bp.route('/experiment-thin-lens')
def experiment_thin_lens():
    return render_template('education/experiment_thin_lens.html')


@education_bp.route('/experiment-rc-circuit')
def experiment_rc_circuit():
    return render_template('education/experiment_rc_circuit.html')


@education_bp.route('/experiment-resonance-tube')
def experiment_resonance_tube():
    return render_template('education/experiment_resonance_tube.html')


@education_bp.route('/experiment-pendulum-camera')
def experiment_pendulum_camera():
    return render_template('education/experiment_pendulum_camera.html')


@education_bp.route('/experiment-device-motion-g')
def experiment_device_motion_g():
    return render_template('education/experiment_device_motion_g.html')


@education_bp.route('/rock-paper-scissors')
def rock_paper_scissors():
    return render_template('education/石头剪刀布.html')


@education_bp.route('/api/gemini', methods=['POST'])
def gemini_api():
    try:
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'content': '请登录后使用AI功能'}), 401

        data = request.get_json() or {}
        prompt = (data.get('prompt') or '').strip()
        if not prompt:
            return jsonify({'success': False, 'content': '请求格式错误，缺少prompt字段'}), 400

        log_action(
            action='education_ai_api',
            details=f'调用教育资源AI API，提示词长度：{len(prompt)}',
            user_id=current_user.id,
        )

        api_key = os.environ.get('ARK_API_KEY') or current_app.config.get('VOLCANO_API_KEY')
        if not api_key:
            return jsonify({'success': False, 'content': '系统未配置API密钥，无法使用AI功能'}), 500

        url = current_app.config.get('VOLCANO_API_URL', 'https://ark.cn-beijing.volces.com/api/v3/chat/completions')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        payload = {
            'model': 'deepseek-v3-250324',
            'messages': [
                {'role': 'system', 'content': '请直接回答用户的问题，不要自称是任何角色。回答应该简洁、准确、有教育意义。'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': 0.7,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code != 200:
            return jsonify({'success': False, 'content': f'AI服务暂时不可用，请稍后再试。错误码：{response.status_code}'}), 502

        response_data = response.json()
        choices = response_data.get('choices') or []
        if not choices:
            return jsonify({'success': False, 'content': 'AI响应格式错误，请稍后再试'}), 502

        ai_response = choices[0].get('message', {}).get('content', '')
        return jsonify({'success': True, 'content': ai_response})
    except requests.Timeout:
        return jsonify({'success': False, 'content': 'AI服务响应超时，请稍后再试'}), 504
    except requests.ConnectionError:
        return jsonify({'success': False, 'content': '无法连接到AI服务，请检查网络连接'}), 502
    except Exception as e:
        current_app.logger.error(f'AI API调用发生未知错误: {str(e)}', exc_info=True)
        return jsonify({'success': False, 'content': '处理请求时发生错误，请稍后再试'}), 500


@education_bp.route('/ai_chat_clear_history', methods=['POST'])
def ai_chat_clear_history():
    try:
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'message': '请登录后使用AI功能'}), 401

        log_action(
            action='education_ai_clear_history',
            details='清除教育资源AI聊天历史',
            user_id=current_user.id,
        )

        return jsonify({'success': True, 'message': '聊天历史已清除'})
    except Exception as e:
        logger.error(f"清除AI聊天历史时出错: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': '清除聊天历史时出错，请稍后再试'}), 500


@education_bp.route('/test')
def test_route():
    return jsonify({'success': True, 'message': '教育资源路由运行正常'})
