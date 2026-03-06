from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DateTimeField, IntegerField, SelectField, SubmitField, SelectMultipleField, BooleanField, Field
from wtforms.validators import DataRequired, Length, Optional, NumberRange
from flask_wtf.file import FileField, FileAllowed
from .models import Tag  # Import the Tag model
import pytz
from datetime import datetime
from .utils.time_helpers import get_beijing_time, localize_time, ensure_timezone_aware, is_render_environment, normalize_datetime_for_db
import logging

class LocalizedDateTimeField(DateTimeField):
    """本地化的日期时间字段，自动处理时区转换"""
    
    def __init__(self, label=None, validators=None, format='%Y-%m-%d %H:%M', **kwargs):
        super(LocalizedDateTimeField, self).__init__(label, validators, format, **kwargs)
    
    def process_formdata(self, valuelist):
        """处理表单数据，将输入的时间视为北京时间"""
        super(LocalizedDateTimeField, self).process_formdata(valuelist)
        if self.data:
            try:
                # 将时间视为北京时间，添加时区信息
                beijing_tz = pytz.timezone('Asia/Shanghai')
                # 确保添加正确的时区信息
                if self.data.tzinfo is None:
                    self.data = beijing_tz.localize(self.data)
                    logging.info(f"LocalizedDateTimeField添加了北京时区: {self.data}")
            except Exception as e:
                logging.error(f"处理表单日期时间出错: {e}, data={self.data}")
    
    def _value(self):
        """返回表单字段显示值，如果有UTC时间则转换为北京时间"""
        if self.data:
            try:
                # 获取格式化字符串
                format_str = self.format
                if isinstance(format_str, list):
                    format_str = format_str[0]
                
                # 如果已有时区信息，转换为北京时间
                if self.data.tzinfo is not None:
                    beijing_tz = pytz.timezone('Asia/Shanghai')
                    beijing_time = self.data.astimezone(beijing_tz)
                    return beijing_time.strftime(format_str)
                else:
                    # 如果没有时区信息，假设是UTC时间，先添加UTC时区再转换为北京时间
                    utc_tz = pytz.UTC
                    utc_time = utc_tz.localize(self.data)
                    beijing_tz = pytz.timezone('Asia/Shanghai')
                    beijing_time = utc_time.astimezone(beijing_tz)
                    return beijing_time.strftime(format_str)
            except Exception as e:
                logging.error(f"获取表单字段显示值出错: {e}, data={self.data}")
                return ""
        
        # 如果没有数据，返回空字符串
        return ''
    
    def populate_obj(self, obj, name):
        """将表单数据保存到对象属性时，保存为UTC时间"""
        if self.data:
            try:
                # 确保有时区信息
                if self.data.tzinfo is None:
                    beijing_tz = pytz.timezone('Asia/Shanghai')
                    self.data = beijing_tz.localize(self.data)
                    logging.info(f"populate_obj时添加了北京时区: {self.data}")
                
                # 转换为UTC时间后去除时区信息
                utc_time = self.data.astimezone(pytz.UTC).replace(tzinfo=None)
                logging.info(f"将表单时间保存为UTC时间: 原时间={self.data}, UTC时间={utc_time}")
                setattr(obj, name, utc_time)
            except Exception as e:
                logging.error(f"保存表单时间到对象出错: {e}, data={self.data}")
                setattr(obj, name, None)
        else:
            setattr(obj, name, None)

class ActivityForm(FlaskForm):
    title = StringField('活动标题', validators=[DataRequired(message='活动标题不能为空')])
    description = TextAreaField('活动描述', validators=[DataRequired(message='活动描述不能为空')])
    location = StringField('活动地点', validators=[DataRequired(message='活动地点不能为空')])
    start_time = LocalizedDateTimeField('开始时间', format='%Y-%m-%d %H:%M', validators=[DataRequired(message='开始时间不能为空')])
    end_time = LocalizedDateTimeField('结束时间', format='%Y-%m-%d %H:%M', validators=[DataRequired(message='结束时间不能为空')])
    registration_deadline = LocalizedDateTimeField('报名截止时间', format='%Y-%m-%d %H:%M', validators=[DataRequired(message='报名截止时间不能为空')])
    max_participants = IntegerField('最大参与人数', validators=[NumberRange(min=0, message='参与人数不能为负数')], default=0)
    status = SelectField('活动状态', choices=[('active', '进行中'), ('completed', '已结束'), ('cancelled', '已取消')], default='active')
    is_featured = BooleanField('设为重点活动', default=False)
    points = IntegerField('活动积分', validators=[NumberRange(min=0, max=100, message='积分值必须在0-100之间')], default=10, description='学生参加活动获得的积分值，默认普通活动10分，重点活动20分')
    tags = SelectMultipleField('活动标签', coerce=int, validators=[Optional()])
    poster = FileField('活动海报', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], '只允许上传图片文件!')
    ])
    submit = SubmitField('保存')

class SearchForm(FlaskForm):
    query = StringField('搜索', validators=[Optional(), Length(max=100)])
    category = SelectField('类别', choices=[
        ('all', '全部'),
        ('title', '标题'),
        ('location', '地点'),
        ('description', '描述')
    ], validators=[Optional()])

class TagSelectionForm(FlaskForm):
    """学生标签选择表单"""
    tags = SelectMultipleField('兴趣标签', coerce=int, validators=[DataRequired(message='请至少选择一个标签')])
    submit = SubmitField('保存')
