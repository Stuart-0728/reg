import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src import create_app, db
from src.models import Activity, User, StudentInfo
from src.utils.wechat_api import send_subscribe_message
from src.utils.time_helpers import display_datetime

app = create_app()

def notify_new_activity(activity_id):
    with app.app_context():
        activity = Activity.query.get(activity_id)
        if not activity:
            return
            
        start_str = display_datetime(activity.start_time, '%Y-%m-%d %H:%M')
        org_name = activity.society.name if activity.society else "智能社团+"
        title = activity.title[:20]
        # thing1: 发起方, thing2: 活动名称, time3: 开始时间, thing4: 活动地点, thing5: 名额限制
        limit_str = str(activity.max_participants) if activity.max_participants > 0 else "999"
        loc = getattr(activity, 'location', '地点详见详情页')[:20]
        
        # 获取加入了该社团的学生
        society_id = activity.society_id
        if society_id:
            # Join StudentInfo to filter by joined_societies
            users = User.query.join(User.student_info).filter(
                User.wx_openid.isnot(None), 
                User.active == True,
                User.student_info.has(StudentInfo.joined_societies.any(id=society_id))
            ).all()
        else:
            # 如果活动没有关联特定社团（例如超级管理员发布的全校活动）则推送给全体
            users = User.query.filter(User.wx_openid.isnot(None), User.active == True).all()
        for u in users:
            payload = {
                "thing1": {"value": org_name},
                "thing6": {"value": title},
                "date2": {"value": start_str},
                "thing4": {"value": loc},
                "number5": {"value": limit_str}
            }
            try:
                res = send_subscribe_message(
                    u.wx_openid,
                    "ESmqrDAYo8rVBDq5EL8YjbKGedpxOYuPQgIZ3Nz_EZ0",
                    f"pages/activity/activity?id={activity.id}",
                    payload
                )
            except:
                pass

if __name__ == '__main__':
    if len(sys.argv) > 1:
        notify_new_activity(int(sys.argv[1]))
