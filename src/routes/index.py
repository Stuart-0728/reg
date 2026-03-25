"""
智能社团+网站修复日志

日期: 2025-06-24
作者: AI助手

本文件记录了网站中发现和修复的问题。
"""

# 问题列表及修复方案

"""
1. 管理员删除通知时显示404错误
   - 问题: 在notifications.html中缺少CSRF令牌，导致表单提交被拒绝
   - 修复: 在表单中添加了<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

2. 首页海报与活动详情海报不符
   - 问题: 海报路径处理逻辑不一致，导致在不同页面显示不同的海报
   - 修复: 统一了首页和活动详情页的备用海报逻辑，都使用banner1.jpg等备用图片

3. 编辑活动时出错
   - 问题: 在edit_activity函数中，处理海报上传时出现"'int' object has no attribute '_sa_instance_state'"错误
   - 修复: 确保使用handle_poster_upload函数处理文件上传，正确传递活动ID

4. 活动状态更改和签到功能无法使用
   - 问题: JavaScript函数中没有包含CSRF令牌，导致POST请求被拒绝
   - 修复: 在fetch请求中添加了CSRF令牌，包括headers和body中

5. 活动签到切换按钮无法使用
   - 问题: toggle-checkin表单中缺少CSRF令牌
   - 修复: 在表单中添加了<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

6. 公告删除功能无法使用
   - 问题: 在announcements.html中缺少CSRF令牌
   - 修复: 在表单中添加了<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
""" 