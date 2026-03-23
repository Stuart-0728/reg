#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import logging
from datetime import datetime, timedelta
import json
import time
import pytz
from src.config import Config
from src.utils.time_helpers import get_localized_now

logger = logging.getLogger(__name__)

WEATHER_HTTP_TIMEOUT = (1.5, 2.5)
WEATHER_FALLBACK_BUDGET_SECONDS = 2.2
WEATHER_CACHE_TTL_SECONDS = {
    'base': 300,
    'all': 900
}
_WEATHER_CACHE = {}
_WEATHER_MISS_CACHE = {}
WEATHER_MISS_TTL_SECONDS = {
    'base': 300,
    'all': 1800
}


def _resolve_weather_date(activity_date=None):
    if activity_date is None:
        return _get_beijing_now().date()
    try:
        if isinstance(activity_date, datetime):
            beijing_tz = pytz.timezone('Asia/Shanghai')
            if activity_date.tzinfo is None:
                return pytz.utc.localize(activity_date).astimezone(beijing_tz).date()
            return activity_date.astimezone(beijing_tz).date()
        if hasattr(activity_date, 'date'):
            return activity_date.date()
    except Exception:
        pass
    return _get_beijing_now().date()


def _weather_cache_key(city_adcode, extensions, activity_date=None):
    date_key = _resolve_weather_date(activity_date).isoformat()
    return f"{city_adcode}:{extensions}:{date_key}"


def _weather_cache_get(key):
    item = _WEATHER_CACHE.get(key)
    if not item:
        return None
    if item['expires_at'] <= time.time():
        _WEATHER_CACHE.pop(key, None)
        return None
    return item['data']


def _weather_cache_set(key, data, extensions):
    if not data:
        return
    ttl = WEATHER_CACHE_TTL_SECONDS.get(extensions, 300)
    _WEATHER_CACHE[key] = {
        'data': data,
        'expires_at': time.time() + ttl
    }


def _weather_miss_hit(key):
    expires_at = _WEATHER_MISS_CACHE.get(key)
    if not expires_at:
        return False
    if expires_at <= time.time():
        _WEATHER_MISS_CACHE.pop(key, None)
        return False
    return True


def _weather_miss_set(key, extensions):
    ttl = WEATHER_MISS_TTL_SECONDS.get(extensions, 300)
    _WEATHER_MISS_CACHE[key] = time.time() + ttl


def _get_db_weather_cache(city_adcode, extensions, activity_date=None):
    try:
        from src import db
        from src.models import WeatherDailyCache

        weather_date = _resolve_weather_date(activity_date)
        record = db.session.execute(
            db.select(WeatherDailyCache).filter_by(
                city_adcode=city_adcode,
                weather_date=weather_date,
                extensions=extensions
            )
        ).scalar_one_or_none()
        if not record or not record.payload:
            return None

        today = _get_beijing_now().date()
        updated_at = getattr(record, 'updated_at', None)
        if not updated_at:
            return None
        updated_date = updated_at.date() if hasattr(updated_at, 'date') else None
        if updated_date != today:
            return None

        return json.loads(record.payload)
    except Exception as e:
        logger.debug(f"读取数据库天气缓存失败: {e}")
        try:
            from src import db
            db.session.rollback()
        except Exception:
            pass
        return None


def _save_db_weather_cache(city_adcode, extensions, activity_date, weather_data):
    if not weather_data:
        return

    try:
        from src import db
        from src.models import WeatherDailyCache

        weather_date = _resolve_weather_date(activity_date)
        payload = json.dumps(weather_data, ensure_ascii=False)

        record = db.session.execute(
            db.select(WeatherDailyCache).filter_by(
                city_adcode=city_adcode,
                weather_date=weather_date,
                extensions=extensions
            )
        ).scalar_one_or_none()

        source = weather_data.get('api_source', 'unknown') if isinstance(weather_data, dict) else 'unknown'
        now = _get_beijing_now()

        if record:
            record.payload = payload
            record.source = source
            record.updated_at = now
        else:
            record = WeatherDailyCache(
                city_adcode=city_adcode,
                weather_date=weather_date,
                extensions=extensions,
                payload=payload,
                source=source,
                created_at=now,
                updated_at=now
            )
            db.session.add(record)

        db.session.commit()
    except Exception as e:
        logger.debug(f"保存数据库天气缓存失败: {e}")
        try:
            from src import db
            db.session.rollback()
        except Exception:
            pass

def _get_beijing_now():
    """获取北京时间（兼容 get_localized_now 返回 naive UTC 的情况）"""
    now = get_localized_now()
    beijing_tz = pytz.timezone('Asia/Shanghai')
    if now.tzinfo is None:
        return pytz.utc.localize(now).astimezone(beijing_tz)
    return now.astimezone(beijing_tz)

# 重庆市的adcode（区域编码）
CHONGQING_ADCODE = '500000'

# 天气现象到Weather Icons的映射
WEATHER_ICON_MAP = {
    '晴': 'wi-day-sunny',
    '少云': 'wi-day-cloudy',
    '晴间多云': 'wi-day-cloudy',
    '多云': 'wi-cloudy',
    '阴': 'wi-cloudy',
    '有风': 'wi-windy',
    '平静': 'wi-day-sunny',
    '微风': 'wi-day-windy',
    '和风': 'wi-windy',
    '清风': 'wi-windy',
    '强风/劲风': 'wi-strong-wind',
    '疾风': 'wi-strong-wind',
    '大风': 'wi-strong-wind',
    '烈风': 'wi-strong-wind',
    '风暴': 'wi-storm-showers',
    '狂爆风': 'wi-hurricane',
    '飓风': 'wi-hurricane',
    '热带风暴': 'wi-hurricane',
    '霾': 'wi-smog',
    '中度霾': 'wi-smog',
    '重度霾': 'wi-smog',
    '严重霾': 'wi-smog',
    '阵雨': 'wi-day-showers',
    '雷阵雨': 'wi-day-thunderstorm',
    '雷阵雨并伴有冰雹': 'wi-day-hail',
    '小雨': 'wi-rain',
    '中雨': 'wi-rain',
    '大雨': 'wi-rain',
    '暴雨': 'wi-rain',
    '大暴雨': 'wi-rain',
    '特大暴雨': 'wi-rain',
    '强阵雨': 'wi-showers',
    '强雷阵雨': 'wi-thunderstorm',
    '极端降雨': 'wi-rain',
    '毛毛雨/细雨': 'wi-sprinkle',
    '雨': 'wi-rain',
    '小雨-中雨': 'wi-rain',
    '中雨-大雨': 'wi-rain',
    '大雨-暴雨': 'wi-rain',
    '暴雨-大暴雨': 'wi-rain',
    '大暴雨-特大暴雨': 'wi-rain',
    '雨雪天气': 'wi-rain-mix',
    '雨夹雪': 'wi-rain-mix',
    '阵雨夹雪': 'wi-rain-mix',
    '冻雨': 'wi-rain-mix',
    '雪': 'wi-snow',
    '阵雪': 'wi-day-snow',
    '小雪': 'wi-snow',
    '中雪': 'wi-snow',
    '大雪': 'wi-snow',
    '暴雪': 'wi-snow',
    '小雪-中雪': 'wi-snow',
    '中雪-大雪': 'wi-snow',
    '大雪-暴雪': 'wi-snow',
    '浮尘': 'wi-dust',
    '扬沙': 'wi-sandstorm',
    '沙尘暴': 'wi-sandstorm',
    '强沙尘暴': 'wi-sandstorm',
    '龙卷风': 'wi-tornado',
    '雾': 'wi-fog',
    '浓雾': 'wi-fog',
    '强浓雾': 'wi-fog',
    '轻雾': 'wi-fog',
    '大雾': 'wi-fog',
    '特强浓雾': 'wi-fog',
    '热': 'wi-hot',
    '冷': 'wi-snowflake-cold',
    '未知': 'wi-na'
}

def get_weather_data(city_adcode=CHONGQING_ADCODE, extensions='base', allow_fallback=True):
    """
    获取指定城市的天气数据（使用高德开放平台API）
    
    Args:
        city_adcode (str): 城市区域编码，默认为重庆
        extensions (str): 气象类型，base=实况天气，all=预报天气
    
    Returns:
        dict: 天气数据字典，包含温度、湿度、天气描述等信息
    """
    try:
        api_key = Config.AMAP_API_KEY
        if not api_key:
            logger.warning("高德API密钥未配置")
            return get_openweather_data('Chongqing', None) if allow_fallback else None
        
        # 高德天气API URL
        url = "https://restapi.amap.com/v3/weather/weatherInfo"
        params = {
            'key': api_key,
            'city': city_adcode,
            'extensions': extensions,
            'output': 'json'
        }
        
        logger.info(f"正在获取城市编码{city_adcode}的天气数据...")
        response = requests.get(url, params=params, timeout=WEATHER_HTTP_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('status') != '1':
            logger.error(f"高德天气API返回错误: {data.get('info', '未知错误')}")
            return get_openweather_data('Chongqing', None) if allow_fallback else None
        
        if extensions == 'base':
            # 处理实况天气数据
            lives = data.get('lives', [])
            if not lives:
                logger.warning("未获取到实况天气数据")
                return get_openweather_data('Chongqing', None) if allow_fallback else None
            
            live_data = lives[0]
            weather_info = {
                'temperature': int(live_data.get('temperature', 0)),
                'feels_like': int(live_data.get('temperature', 0)),  # 高德API没有体感温度，使用实际温度
                'humidity': int(live_data.get('humidity', 0)),
                'description': live_data.get('weather', '未知'),
                'icon': get_weather_icon(live_data.get('weather', '未知')),
                'location': live_data.get('city', '重庆'),
                'province': live_data.get('province', '重庆市'),
                'wind_direction': live_data.get('winddirection', ''),
                'wind_power': live_data.get('windpower', ''),
                'report_time': live_data.get('reporttime', ''),
                'date': _get_beijing_now().strftime('%Y-%m-%d'),
                'is_forecast': False
            }
            logger.info(f"获取{weather_info['location']}当前天气成功: {weather_info['description']}")
            return weather_info
        
        else:
            # 处理预报天气数据
            forecasts = data.get('forecasts', [])
            if not forecasts:
                logger.warning("未获取到预报天气数据")
                return get_openweather_data('Chongqing', None) if allow_fallback else None
            
            forecast_data = forecasts[0]
            casts = forecast_data.get('casts', [])
            if not casts:
                logger.warning("预报数据为空")
                return get_openweather_data('Chongqing', None) if allow_fallback else None
            
            # 返回今天的预报数据
            today_cast = casts[0]
            weather_info = {
                'temperature': int(today_cast.get('daytemp', 0)),
                'feels_like': int(today_cast.get('daytemp', 0)),
                'humidity': 0,  # 预报数据中没有湿度信息
                'description': today_cast.get('dayweather', '未知'),
                'icon': get_weather_icon(today_cast.get('dayweather', '未知')),
                'location': forecast_data.get('city', '重庆'),
                'province': forecast_data.get('province', '重庆市'),
                'night_temp': int(today_cast.get('nighttemp', 0)),
                'night_weather': today_cast.get('nightweather', ''),
                'date': today_cast.get('date', ''),
                'week': today_cast.get('week', ''),
                'report_time': forecast_data.get('reporttime', ''),
                'is_forecast': True,
                'casts': casts  # 保存完整的预报数据
            }
            logger.info(f"获取{weather_info['location']}预报天气成功: {weather_info['description']}")
            return weather_info
            
    except requests.exceptions.RequestException as e:
        logger.error(f"高德天气API请求失败: {e}")
        return get_openweather_data('Chongqing', None) if allow_fallback else None
    except Exception as e:
        logger.error(f"获取天气数据时发生错误: {e}")
        return get_openweather_data('Chongqing', None) if allow_fallback else None

def get_weather_icon(weather_desc):
    """
    根据天气描述获取对应的Weather Icons图标类名
    
    Args:
        weather_desc (str): 天气描述
    
    Returns:
        str: Weather Icons图标类名
    """
    return WEATHER_ICON_MAP.get(weather_desc, 'wi-na')

def get_openweather_data(city='Chongqing', date=None):
    """
    使用OpenWeather API获取天气数据（备用API）
    
    Args:
        city (str): 城市名称，默认为重庆
        date (datetime): 指定日期，None表示当前天气
    
    Returns:
        dict: 天气数据字典
    """
    try:
        api_key = Config.OPENWEATHER_API_KEY
        if not api_key:
            logger.warning("OpenWeather API密钥未配置")
            return None
        
        now = _get_beijing_now()
        
        # OpenWeatherMap API URL
        if date and date.date() != now.date():
            # 获取预报天气（5天预报）
            url = f"https://api.openweathermap.org/data/2.5/forecast"
            params = {
                'q': f'{city},CN',
                'appid': api_key,
                'units': 'metric',
                'lang': 'zh_cn'
            }
        else:
            # 获取当前天气
            url = f"https://api.openweathermap.org/data/2.5/weather"
            params = {
                'q': f'{city},CN',
                'appid': api_key,
                'units': 'metric',
                'lang': 'zh_cn'
            }
        
        logger.info(f"使用OpenWeather API获取{city}的天气数据...")
        response = requests.get(url, params=params, timeout=WEATHER_HTTP_TIMEOUT)
        response.raise_for_status()
        
        data = response.json()
        
        if date and date.date() != now.date():
            # 处理预报数据
            target_date = date.date()
            for forecast in data.get('list', []):
                forecast_date = datetime.fromtimestamp(forecast['dt']).date()
                if forecast_date == target_date:
                    # 将OpenWeather数据转换为统一格式
                    weather_info = {
                        'temperature': round(forecast['main']['temp']),
                        'feels_like': round(forecast['main']['feels_like']),
                        'humidity': forecast['main']['humidity'],
                        'description': forecast['weather'][0]['description'],
                        'icon': openweather_to_weather_icon(forecast['weather'][0]['icon']),
                        'location': '重庆',
                        'province': '重庆市',
                        'wind_direction': '',
                        'wind_power': '',
                        'report_time': _get_beijing_now().strftime('%Y-%m-%d %H:%M:%S'),
                        'date': date.strftime('%Y-%m-%d'),
                        'is_forecast': True,
                        'api_source': 'openweather'
                    }
                    logger.info(f"OpenWeather API获取{city}预报天气成功: {weather_info['description']}")
                    return weather_info
            
            logger.warning(f"OpenWeather API未找到{target_date}的天气预报数据")
            return None
        else:
            # 处理当前天气数据
            weather_info = {
                'temperature': round(data['main']['temp']),
                'feels_like': round(data['main']['feels_like']),
                'humidity': data['main']['humidity'],
                'description': data['weather'][0]['description'],
                'icon': openweather_to_weather_icon(data['weather'][0]['icon']),
                'location': '重庆',
                'province': '重庆市',
                'wind_direction': '',
                'wind_power': '',
                'report_time': _get_beijing_now().strftime('%Y-%m-%d %H:%M:%S'),
                'date': now.strftime('%Y-%m-%d'),
                'is_forecast': False,
                'api_source': 'openweather'
            }
            logger.info(f"OpenWeather API获取{city}当前天气成功: {weather_info['description']}")
            return weather_info
            
    except requests.exceptions.RequestException as e:
        logger.error(f"OpenWeather API请求失败: {e}")
        return None
    except Exception as e:
        logger.error(f"OpenWeather API获取天气数据时发生错误: {e}")
        return None

def openweather_to_weather_icon(openweather_icon):
    """
    将OpenWeather图标代码转换为Weather Icons类名
    
    Args:
        openweather_icon (str): OpenWeather图标代码（如'01d', '02n'等）
    
    Returns:
        str: Weather Icons类名
    """
    icon_map = {
        '01d': 'wi-day-sunny',      # 晴天
        '01n': 'wi-night-clear',    # 晴夜
        '02d': 'wi-day-cloudy',     # 少云
        '02n': 'wi-night-alt-cloudy',
        '03d': 'wi-cloudy',         # 多云
        '03n': 'wi-cloudy',
        '04d': 'wi-cloudy',         # 阴天
        '04n': 'wi-cloudy',
        '09d': 'wi-showers',        # 阵雨
        '09n': 'wi-night-alt-showers',
        '10d': 'wi-day-rain',       # 雨
        '10n': 'wi-night-alt-rain',
        '11d': 'wi-thunderstorm',   # 雷雨
        '11n': 'wi-thunderstorm',
        '13d': 'wi-snow',           # 雪
        '13n': 'wi-snow',
        '50d': 'wi-fog',            # 雾
        '50n': 'wi-fog'
    }
    return icon_map.get(openweather_icon, 'wi-na')

def get_weather_data_with_fallback(city_adcode=CHONGQING_ADCODE, extensions='base', activity_date=None):
    """
    获取天气数据，高德API失败时自动切换到OpenWeather API
    
    Args:
        city_adcode (str): 城市区域编码，默认为重庆
        extensions (str): 气象类型，base=实况天气，all=预报天气
        activity_date (datetime): 活动日期，用于OpenWeather API
    
    Returns:
        dict: 天气数据字典
    """
    cache_key = _weather_cache_key(city_adcode, extensions, activity_date)

    if _weather_miss_hit(cache_key):
        return None

    cached = _weather_cache_get(cache_key)
    if cached:
        return cached

    db_cached = _get_db_weather_cache(city_adcode, extensions, activity_date)
    if db_cached:
        _weather_cache_set(cache_key, db_cached, extensions)
        return db_cached

    started_at = time.time()

    # 首先尝试高德API
    logger.info("尝试使用高德API获取天气数据...")
    weather_data = get_weather_data(city_adcode, extensions, allow_fallback=False)
    
    if weather_data:
        weather_data['api_source'] = 'amap'
        _weather_cache_set(cache_key, weather_data, extensions)
        _save_db_weather_cache(city_adcode, extensions, activity_date, weather_data)
        logger.info("高德API获取天气数据成功")
        return weather_data
    
    # 高德API失败，尝试OpenWeather API
    elapsed = time.time() - started_at
    if elapsed >= WEATHER_FALLBACK_BUDGET_SECONDS:
        logger.warning(f"天气主接口已耗时{elapsed:.2f}s，跳过备用接口以避免阻塞页面渲染")
        _weather_miss_set(cache_key, extensions)
        return None

    logger.warning("高德API失败，尝试使用OpenWeather API作为备用...")
    
    # 将高德的extensions参数转换为OpenWeather的日期参数
    if extensions == 'all' and activity_date:
        # 预报天气
        fallback_data = get_openweather_data('Chongqing', activity_date)
    else:
        # 实况天气
        fallback_data = get_openweather_data('Chongqing', None)
    
    if fallback_data:
        _weather_cache_set(cache_key, fallback_data, extensions)
        _save_db_weather_cache(city_adcode, extensions, activity_date, fallback_data)
        logger.info("备用OpenWeather API获取天气数据成功")
        return fallback_data
    else:
        _weather_miss_set(cache_key, extensions)
        logger.error("所有天气API都失败，无法获取天气数据")
        return None

def get_activity_weather(activity_start_time):
    """
    获取活动当天的天气信息（带备用API支持）
    
    Args:
        activity_start_time (datetime): 活动开始时间
    
    Returns:
        dict: 天气数据字典，如果超过预报范围则返回None
    """
    if not activity_start_time:
        logger.warning("活动开始时间为空，无法获取天气数据")
        return None
    
    try:
        beijing_tz = pytz.timezone('Asia/Shanghai')
        if activity_start_time.tzinfo is None:
            localized_activity_start_time = pytz.utc.localize(activity_start_time).astimezone(beijing_tz)
        else:
            localized_activity_start_time = activity_start_time.astimezone(beijing_tz)

        now = _get_beijing_now()
        current_date = now.date()
        activity_date = localized_activity_start_time.date()
        
        # 计算活动距离今天的天数
        days_diff = (activity_date - current_date).days
        
        # 如果活动超过5天，不显示天气信息
        if days_diff > 5:
            logger.info(f"活动日期{activity_date}超过5天预报范围，不显示天气信息")
            return None
        
        # 如果活动是过去超过1天的，也不显示天气信息（避免显示不准确的当前天气）
        if days_diff < -1:
            logger.info(f"活动日期{activity_date}为过去日期且超过1天，不显示天气信息")
            return None
        
        # 判断是获取实况还是预报天气
        if activity_date <= current_date:
            # 活动是今天或昨天，获取实况天气
            weather_data = get_weather_data_with_fallback(CHONGQING_ADCODE, 'base', None)
            is_forecast = False
            if days_diff == 0:
                forecast_note = "当日天气"
            else:
                forecast_note = "近期天气"
        else:
            # 活动是未来，获取预报天气
            weather_data = get_weather_data_with_fallback(CHONGQING_ADCODE, 'all', activity_start_time)
            is_forecast = True
            
            if days_diff == 1:
                forecast_note = "明日天气预报"
            elif days_diff == 2:
                forecast_note = "后天天气预报"
            else:
                forecast_note = f"{days_diff}天后天气预报"
        
        if weather_data:
            # 添加活动相关信息
            weather_data['activity_date'] = localized_activity_start_time.strftime('%Y-%m-%d')
            weather_data['activity_time'] = localized_activity_start_time.strftime('%H:%M')
            weather_data['is_forecast'] = is_forecast
            weather_data['forecast_note'] = forecast_note
            
            # 添加API来源信息到显示中
            api_source = weather_data.get('api_source', 'unknown')
            if api_source == 'amap':
                weather_data['note'] = "数据来源：高德开放平台"
            elif api_source == 'openweather':
                weather_data['note'] = "数据来源：OpenWeather"
            
            return weather_data
        else:
            logger.warning(f"无法获取活动日期 {activity_date} 的天气数据")
            return None
            
    except Exception as e:
        logger.error(f"获取活动天气数据时发生错误: {e}")
        return None

# 全局天气服务实例
weather_service = None

def get_weather_service():
    """获取天气服务实例"""
    global weather_service
    if weather_service is None:
        weather_service = WeatherService()
    return weather_service

class WeatherService:
    """天气服务类，用于获取重庆天气信息"""
    
    def __init__(self):
        # 使用高德开放平台API
        # 您需要在环境变量中设置AMAP_API_KEY
        self.api_key = Config.AMAP_API_KEY
        self.base_url = "https://restapi.amap.com/v3/weather/weatherInfo"
        self.city_name = "重庆"
        self.city_adcode = CHONGQING_ADCODE
        
    def get_current_weather(self):
        """获取重庆当前天气"""
        try:
            weather_data = get_weather_data_with_fallback(self.city_adcode, 'base', None)
            return weather_data
        except Exception as e:
            logger.error(f"获取天气数据时发生错误: {e}")
            return None
    
    def get_weather_by_date(self, target_date):
        """获取指定日期的天气预报（最多支持5天）"""
        try:
            # 计算目标日期与今天的差异
            today = datetime.now().date()
            target_date_obj = target_date.date() if hasattr(target_date, 'date') else target_date
            days_diff = (target_date_obj - today).days
            
            # 如果是今天或过去的日期，返回当前天气
            if days_diff <= 0:
                return self.get_current_weather()
            
            # 如果超过5天，返回None（不显示天气信息）
            if days_diff > 5:
                logger.info(f"目标日期{target_date_obj}超过5天预报范围，不返回天气数据")
                return None
            
            # 获取5天预报
            weather_data = get_weather_data_with_fallback(self.city_adcode, 'all', target_date)
            return weather_data
        except Exception as e:
            logger.error(f"获取天气预报时发生错误: {e}")
            return None
