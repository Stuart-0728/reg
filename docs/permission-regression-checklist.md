# 权限回归检查清单（按角色）

## 范围
- 目标：验证游客/学生/管理员/总管理员的访问边界、写操作保护、跨社团越权防护。
- 覆盖：`src/routes/admin.py`、`src/routes/student.py`、`src/routes/checkin.py`、`src/routes/utils.py`、`src/routes/tag.py`、`src/routes/main.py`。

## 已发现并需要重点回归的风险点
- 签到统计接口已从 `login_required` 调整为 `admin_required`：`/checkin/statistics/<activity_id>`。
- `checkin.py` 内仍有多处写接口仅 `login_required`（建议重点回归是否存在学生/管理员角色错用）。
- 已新增写操作同源校验（Origin 与 Host 一致）作为 CSRF 补充。

## A. 游客（未登录）
1. 访问管理页：`GET /admin/dashboard`，预期 302 到登录页。
2. 调用管理写接口：`POST /admin/activity/1/change_status`，预期 302/403。
3. 调用学生写接口：`POST /student/activity/1/register`，预期 302/401。
4. 调用签到写接口：`POST /checkin/1`，预期 302/401。

## B. 学生
1. 访问管理页：`GET /admin/dashboard`，预期 302/403。
2. 调用管理写接口：`POST /admin/student/2/promote-admin`，预期 403。
3. 学生报名本活动：`POST /student/activity/<id>/register`，预期成功。
4. 学生取消本人报名：`POST /student/activity/<id>/cancel`，预期成功。
5. 直接访问签到统计：`GET /checkin/statistics/<activity_id>`，预期 302/403（不能成功）。

## C. 社团管理员（非总管理员）
1. 查看本社团活动/学生：应成功。
2. 修改他社团活动：`POST /admin/activity/<other_id>/edit`，预期 403。
3. 删除他社团学生：`POST /admin/student/<other_user_id>/delete`，预期 403。
4. 积分调整越权：`POST /admin/student/<other_user_id>/adjust_points`，预期 403。

## D. 总管理员
1. 管理任意社团活动/学生：应成功。
2. 社团绑定与分配管理员：`POST /admin/society/<id>/assign-admin`，应成功。
3. 高危操作（重置/备份恢复）仅总管理员可执行。

## E. 安全性专项
1. CSRF：表单缺 token 的 POST 应失败。
2. 同源策略：伪造 `Origin: https://evil.example.com` 的 POST 应失败（403）。
3. 会话一致性：改密后旧会话应失效（已采用指纹化 session id）。
4. 缓存隔离：登录态页面响应头必须包含 no-store，且带 Cookie 相关 Vary。

## F. 回归执行建议
- 每次发布前执行 A~E 全套。
- 对失败用例记录：URL、角色、请求头、响应码、响应体摘要。
- 重点复测最近改动文件：`src/routes/checkin.py`、`src/routes/utils.py`、`src/__init__.py`。
