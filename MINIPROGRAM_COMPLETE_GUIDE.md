# 微信小程序版本适配 - 完整手册

## 📋 项目概览

本项目已成功改造为微信小程序版本，完全兼容现有的 Flask 后端服务。小程序版本与网页版共用一套后端 API，支持微信原生登录、报名、签到等核心功能。

---

## ✨ 已完成的功能

### 后端改造
- ✅ **CORS 支持** - 允许小程序跨域请求
- ✅ **微信登录接口** (`POST /auth/wx-login`) - 集成微信原生登录
- ✅ **Token 验证接口** (`POST /auth/session-token-validate`) - 会话管理
- ✅ **API 认证机制** - Bearer Token 支持
- ✅ **环境配置** - 支持微信小程序特定参数

### 小程序前端
- ✅ **完整项目结构** - pages, components, utils 完整分层
- ✅ **API 服务层** (`miniprogram/utils/api.js`) - 自动认证、重试、错误处理
- ✅ **工具函数库** (`miniprogram/utils/utils.js`) - 时间格式、验证、缓存等
- ✅ **页面框架**：
  - 首页 (index) - 活动推荐、公告展示
  - 登录页 (auth/login) - 微信登录、账号登录、记住我
  - 活动列表 (activities) - 搜索、筛选、分页
  - 活动详情 (activity-detail) - 报名、签到、分享
  - 我的活动 (my-activities) - 框架待完成
  - 个人资料 (profile) - 框架待完成

### 配置与文档
- ✅ **部署指南** - 腾讯云完整部署方案
- ✅ **环境变量模板** - 开发/生产配置示例
- ✅ **API 文档** - 所有端点详细说明
- ✅ **安全配置** - SSL、HTTPS、限流保护

---

## 🚀 快速开始

### 步骤 1: 后端配置

#### 安装依赖
```bash
cd /path/to/reg\ mini\ program
source venv/bin/activate
pip install -r requirements.txt
```

#### 配置环境变量
创建 `.env` 文件：
```bash
WX_MINI_APP_ID=wx39c27f1ca93c8893
WX_MINI_APP_SECRET=your_secret_here  # 从微信公众平台获取
FLASK_ENV=production
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://...  # 腾讯云 CynosDB 地址
REDIS_URL=redis://...           # 腾讯云 Redis 地址
```

#### 启动服务
```bash
# 本地测试
python src/main.py

# 腾讯云生产
gunicorn -w 4 -b 0.0.0.0:8082 wsgi:app
```

### 步骤 2: 小程序开发

#### 打开微信开发者工具
1. 下载 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
2. 选择 "打开" → 选择 `miniprogram` 文件夹
3. 输入项目名称和 AppID (已有: `wx39c27f1ca93c8893`)

#### 配置 API 地址
编辑 `miniprogram/utils/config.js`：

**开发环境**：
```javascript
development: {
  apiBaseUrl: 'http://localhost:8082',
  ...
}
```

**生产环境**：
```javascript
production: {
  apiBaseUrl: 'https://your-domain.com',  // 替换为实际域名
  ...
}
```

#### 编译运行
- 按 `Ctrl+B` (或 `Cmd+B` on Mac) 编译
- 在模拟器中查看效果
- 扫描二维码在真机预览

### 步骤 3: 腾讯云部署

#### 部署 Flask 应用
```bash
# 连接到腾讯云 ECS/轻量应用服务器
ssh ubuntu@your-ip

# 克隆项目
git clone your-repo-url
cd reg\ mini\ program

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置环境变量
cat > .env << EOF
WX_MINI_APP_ID=wx39c27f1ca93c8893
WX_MINI_APP_SECRET=your_secret
FLASK_ENV=production
DATABASE_URL=your_db_url
REDIS_URL=your_redis_url
EOF

# 配置 Nginx 和 Supervisor（参考部署指南）
```

#### 配置小程序服务器域名
登录 [微信公众平台](https://mp.weixin.qq.com/) → 开发 → 开发设置 → 服务器域名：

添加：
- 请求合法域名：`https://your-domain.com`
- 文件上传域名：`https://your-domain.com`
- 文件下载域名：`https://your-domain.com`

#### 提交审核发布
1. 微信开发者工具 → "上传"
2. 微信公众平台 → 版本管理 → 提交审核
3. 审核通过后点击 "发布"

---

## 📁 项目文件结构

```
/Users/luoyixin/Desktop/💻编程项目/reg mini program/
├── miniprogram/                          # 小程序项目
│   ├── app.json                         # 全局配置
│   ├── app.js                           # 全局逻辑
│   ├── app.wxss                         # 全局样式
│   ├── pages/
│   │   ├── index/                       # 首页（已完成）
│   │   ├── activities/                  # 活动列表（已完成）
│   │   ├── activity-detail/             # 活动详情（已完成）
│   │   ├── my-activities/               # 我的活动（框架）
│   │   ├── auth/
│   │   │   ├── login/                   # 登录页（已完成）
│   │   │   └── register/                # 注册页（框架）
│   │   └── profile/                     # 个人资料（框架）
│   ├── components/                       # 可复用组件
│   ├── utils/
│   │   ├── api.js                       # API 服务层（已完成）
│   │   ├── config.js                    # 配置文件（已完成）
│   │   └── utils.js                     # 工具函数（已完成）
│   └── assets/
│       └── icons/                       # tab 图标
│
├── src/                                  # 后端项目
│   ├── __init__.py                      # Flask 应用初始化（已改造支持CORS）
│   ├── config.py                        # 配置文件（已添加微信配置）
│   ├── routes/
│   │   └── auth.py                      # 认证路由（已添加微信登录）
│   ├── models/                          # 数据模型
│   ├── templates/                       # HTML 模板（Web版）
│   └── static/                          # 静态文件
│
├── MINIPROGRAM_DEPLOYMENT.md            # 完整部署指南
├── .env.example.miniprogram             # 环境变量示例
├── requirements.txt                      # 依赖（已更新）
└── wsgi.py                              # WSGI 入口
```

---

## 🔌 核心 API 端点

### 认证相关

#### 微信登录
```
POST /auth/wx-login
Content-Type: application/json

请求：
{
  "code": "微信授权码"
}

响应：
{
  "success": true,
  "user_id": 123,
  "username": "wx_openid",
  "email": "openid@weixin.local",
  "session_token": "eyJhbGc...",  # Bearer Token
  "is_new_user": false
}
```

#### 验证Token
```
POST /auth/session-token-validate
Header: Authorization: Bearer {session_token}

响应：
{
  "valid": true,
  "user_id": 123,
  "username": "用户名"
}
```

### 活动相关

#### 获取首页活动
```
GET /api/home-activities?page=1&page_size=10

响应：
{
  "success": true,
  "activities": [
    {
      "id": 1,
      "title": "校园运动会",
      "location": "体育馆",
      "start_time": "2026-04-10 09:00",
      "end_time": "2026-04-10 17:00",
      "max_participants": 100,
      "registration_count": 45,
      "poster_image": "https://...",
      "status": "active"
    },
    ...
  ]
}
```

#### 获取活动列表
```
GET /activities?page=1&page_size=10&status=active&search=&sort=newest

响应：
{
  "success": true,
  "activities": [...]
}
```

#### 获取活动详情
```
GET /activity/{activity_id}

响应：
{
  "success": true,
  "activity": {
    "id": 1,
    "title": "校园运动会",
    "description": "...",
    "location": "体育馆",
    "start_time": "2026-04-10 09:00:00",
    "end_time": "2026-04-10 17:00:00",
    "registration_deadline": "2026-04-08 17:00:00",
    "max_participants": 100,
    "registration_count": 45,
    "points": 10,
    "poster_image": "https://...",
    "status": "active"
  }
}
```

#### 报名活动
```
POST /activity/{activity_id}/register
Header: Authorization: Bearer {session_token}
Content-Type: application/json

响应：
{
  "success": true,
  "registration_id": 456,
  "message": "报名成功"
}
```

#### 取消报名
```
POST /activity/{activity_id}/cancel
Header: Authorization: Bearer {session_token}

响应：
{
  "success": true,
  "message": "已取消报名"
}
```

#### 签到
```
POST /api/attendance/checkin
Header: Authorization: Bearer {session_token}
Content-Type: application/json

请求：
{
  "activity_id": 1,
  "registration_id": 456
}

响应：
{
  "success": true,
  "message": "签到成功"
}
```

---

## 🔑 环境变量完整清单

### 必需的微信配置
| 变量 | 说明 | 示例 |
|------|------|------|
| `WX_MINI_APP_ID` | 微信小程序 ID | `wx39c27f1ca93c8893` |
| `WX_MINI_APP_SECRET` | 微信小程序密钥 | `abc123def456...` |

### 数据库配置
| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | 数据库连接字符串 | `postgresql://user:pass@host:5432/db` |
| `REDIS_URL` | Redis 缓存地址 | `redis://:pass@host:6379/0` |

### 应用配置
| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | Flask 密钥 | `dev-secret-key` |
| `FLASK_ENV` | 环境 | `production` |
| `FLASK_CONFIG` | 配置模式 | `production` |

详见 `.env.example.miniprogram` 文件。

---

## 🛡️ 安全检查清单

部署前必须检查：

- [ ] SSL 证书已安装（HTTPS）
- [ ] 微信 AppSecret 已配置（不能为空）
- [ ] 数据库连接安全（VPC 或防火墙）
- [ ] Redis 连接已认证
- [ ] 服务器域名已在微信平台配置
- [ ] CORS 白名单已设置
- [ ] 限流保护已启用
- [ ] 日志记录已启用
- [ ] 备份策略已配置
- [ ] 监控告警已设置

---

## 📊 性能优化建议

### 前端优化
- 启用图片压缩和适配
- 实现列表分页和虚拟滚动
- 缓存用户数据（localStorage）
- 预加载关键资源

### 后端优化
- 使用 Redis 缓存热数据
- 数据库查询优化（索引、连接池）
- CDN 加速静态资源
- 启用 WebSocket 实时更新（可选）

### 部署优化
- 使用 Nginx 反向代理
- 启用 Gzip 压缩
- 配置 HTTP/2
- 使用连接池和连接复用

---

## 🐛 常见问题排查

### 问题 1: 微信登录失败

**错误信息**: `errcode: 40001`

**排查步骤**:
1. 验证 `WX_MINI_APP_SECRET` 是否正确（从微信公众平台复制）
2. 确认请求使用的是 HTTPS
3. 检查后端日志中的详细错误信息
4. 验证服务器域名是否已在微信平台配置

**解决方案**:
```bash
# 查看后端日志
tail -f /var/log/cqnu_association.log | grep "微信"

# 测试 API
curl -X POST https://your-domain.com/auth/wx-login \
  -H "Content-Type: application/json" \
  -d '{"code":"test_code"}'
```

### 问题 2: CORS 错误

**错误信息**: `No 'Access-Control-Allow-Origin' header`

**排查步骤**:
1. 确认 `Flask-CORS` 已安装
2. 检查 `src/__init__.py` 中的 CORS 配置
3. 验证 Nginx 反向代理中是否正确转发 CORS 头

**解决方案**:
```bash
# 检查 CORS 响应头
curl -I https://your-domain.com/api/home-activities | grep Access-Control

# 重启应用
sudo supervisorctl restart cqnu_association
```

### 问题 3: 数据不显示

**错误信息**: 活动列表为空

**排查步骤**:
1. 确认数据库连接正常
2. 查看后端日志是否有数据库错误
3. 检查活动表是否有数据
4. 验证 API 端点是否正确

**解决方案**:
```bash
# 测试数据库连接
psql postgresql://user:pass@host:5432/db -c "SELECT COUNT(*) FROM activity;"

# 查看 API 响应
curl https://your-domain.com/api/home-activities

# 检查后端日志
tail -f /var/log/cqnu_association.log
```

### 问题 4: 上传文件失败

**错误信息**: `413 Payload Too Large`

**解决方案**:
```nginx
# 在 Nginx 配置中增加上传限制
client_max_body_size 80M;
```

```python
# 在 Flask config.py 中设置
MAX_CONTENT_LENGTH = 80 * 1024 * 1024
```

---

## 📈 监控与维护

### 实时监控

```bash
# 查看应用状态
sudo supervisorctl status cqnu_association

# 查看性能指标
top -p $(pgrep gunicorn)

# 查看连接数
netstat -an | grep ESTABLISHED | wc -l
```

### 日志分析

```bash
# 查看最近的错误
grep ERROR /var/log/cqnu_association.log | tail -20

# 查看特定用户的操作
grep "用户ID=123" /var/log/cqnu_association.log

# 统计 API 调用
grep "POST /auth/wx-login" /var/log/nginx/access.log | wc -l
```

### 定期维护

```bash
# 数据库备份
pg_dump postgresql://user:pass@host:5432/db > backup_$(date +%Y%m%d).sql

# 清理过期 session
flask shell
>>> from src.models import User
>>> db.session.query(User).filter(User.last_login < datetime.now() - timedelta(days=30)).delete()

# 更新依赖包
pip list --outdated
pip install -U package_name
```

---

## 🎯 后续功能规划

### Phase 2 (建议)
- [ ] 我的活动页面完成
- [ ] 个人资料编辑页面完成
- [ ] 消息通知系统
- [ ] 积分排行榜
- [ ] 社团管理后台

### Phase 3 (可选)
- [ ] 支付功能（事务转账）
- [ ] 海报生成和分享
- [ ] 活动评价功能
- [ ] AI 推荐系统
- [ ] 视频直播集成

### Phase 4 (增强)
- [ ] 离线功能
- [ ] 暗色主题支持
- [ ] 多语言支持
- [ ] 无障碍访问
- [ ] 性能监控 Dashboard

---

## 📞 技术支持

遇到问题？参考以下资源：

### 官方文档
- [微信小程序官方文档](https://developers.weixin.qq.com/miniprogram/dev/framework/)
- [Flask 官方文档](https://flask.palletsprojects.com/)
- [腾讯云文档中心](https://cloud.tencent.com/document)

### 常用命令
```bash
# 查看小程序日志（开发者工具）
Ctrl + Shift + I (Windows) / Cmd + Option + I (Mac)

# 实时查看后端日志
tail -f /var/log/cqnu_association.log

# SSH 连接腾讯云
ssh -i your-key.pem ubuntu@your-ip

# 远程 Git 部署
git pull origin main && supervisorctl restart cqnu_association
```

---

## 📝 变更日志

### v1.0.0 (2026-04-04)
- ✨ 完成小程序项目初始化
- 🔧 配置 CORS 和微信登录支持
- 📄 编写完整部署文档
- 🎯 完成核心页面框架

### 下个版本计划
- [ ] 完成所有页面逻辑
- [ ] 发布到微信应用市场
- [ ] 性能优化和测试

---

**项目地址**: `/Users/luoyixin/Desktop/💻编程项目/reg mini program`  
**小程序 AppID**: `wx39c27f1ca93c8893`  
**微信小程序项目目录**: `miniprogram/`
