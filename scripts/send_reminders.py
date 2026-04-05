import os
import sys
from datetime import datetime, timedelta
import pytz

# Load Flask App Context
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src import create_app, db
from src.models import Activity, Registration, User
from src.utils.wechat_api import send_subscribe_message
from src.utils.time_helpers import display_datetime

app = create_app()

def run_reminders():
    with app.app_context():
        now = datetime.now(pytz.utc)
        # Look for activities starting in 24 to 25 hours
        time_lower = now + timedelta(hours=24)
        time_upper = now + timedelta(hours=25)
        
        # Activity start notification template: 16S-vnKCWw7x2xqKi86K_mme2paucmkIl0-hkDXAkfA
        # User requested vars: 活动发起(thing)、开始时间(time)、活动名称(thing)、活动地点(thing)、温馨提示(thing)
        # Guessed mappings: thing1(originator), date2/time2(start time), thing3(activity name), thing4(location), thing5(tips)
        
        activities = Activity.query.filter(
            Activity.status == 'active',
            Activity.start_time >= time_lower,
            Activity.start_time < time_upper
        ).all()
        
        for activity in activities:
            start_str = display_datetime(activity.start_time, '%Y-%m-%d %H:%M')
            org_name = activity.society.name if activity.society else "智能社团+"
            title = activity.title[:20]
            loc = activity.location[:20] if getattr(activity, 'location', None) else "详见活动详情页面"
            
            regs = activity.registrations.filter_by(status='registered').all()
            for r in regs:
                user = r.user
                if user.wx_openid:
                    # Different accounts might have slightly different keys, we use a generic payload
                    payload = {
                        "name1": {"value": org_name[:10]},
                        "date3": {"value": start_str},
                        "thing4": {"value": title},
                        "thing6": {"value": loc},
                        "thing7": {"value": "活动快开始啦，请准时参加哦"}
                    }
                    try:
                        res = send_subscribe_message(
                            user.wx_openid,
                            "16S-vnKCWw7x2xqKi86K_mme2paucmkIl0-hkDXAkfA",
                            f"pages/activity/activity?id={activity.id}",
                            payload
                        )
                        app.logger.info(f"Reminded user {user.id} for activity {activity.id}: {res}")
                    except Exception as e:
                        app.logger.error(f"Failed to remind user {user.id}: {e}")

if __name__ == '__main__':
    run_reminders()
