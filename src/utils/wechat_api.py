import requests
from flask import current_app
from src import cache

def get_wechat_access_token():
    token = cache.get("wechat_access_token")
    if token:
        return token
        
    appid = current_app.config.get('WX_APPID')
    secret = current_app.config.get('WX_APPSECRET')
    if not appid or not secret:
        return None
        
    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={secret}"
    try:
        resp = requests.get(url, timeout=5).json()
        if "access_token" in resp:
            # Cache for slightly less than 7200 seconds
            cache.set("wechat_access_token", resp["access_token"], timeout=7000)
            return resp["access_token"]
    except Exception as e:
        current_app.logger.error(f"Failed to get wechat token: {e}")
        
    return None

def send_subscribe_message(openid, template_id, page, data):
    token = get_wechat_access_token()
    if not token:
        return {'success': False, 'msg': '无 access_token'}
        
    url = f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={token}"
    payload = {
        "touser": openid,
        "template_id": template_id,
        "page": page,
        "data": data,
        "miniprogram_state": "developer" # formal / trial / developer
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=5).json()
        if resp.get('errcode') == 0:
            return {'success': True, 'msg': 'ok'}
        else:
            return {'success': False, 'msg': str(resp)}
    except Exception as e:
        return {'success': False, 'msg': str(e)}
