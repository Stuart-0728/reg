# 微信小程序版本部署指南

## 目录结构

```
miniprogram/
├── app.json                 # 小程序全局配置
├── app.js                   # 小程序全局逻辑
├── app.wxss                 # 小程序全局样式
├── pages/                   # 页面目录
│   ├── index/              # 首页
│   ├── activities/         # 活动列表
│   ├── activity-detail/    # 活动详情
│   ├── my-activities/      # 我的活动
│   ├── auth/               # 认证页面
│   │   ├── login.js/wxml/wxss
│   │   ├── register.js/wxml/wxss
│   │   └── profile/
│   └── profile/            # 个人资料
├── components/             # 可复用组件
├── utils/                  # 工具函数
│   ├── api.js             # API服务层
│   ├── config.js          # 配置文件
│   └── utils.js           # 工具函数
└── assets/                # 资源文件
    └── icons/            # 图标
```

## 一、后端配置（Flask应用）

### 1. 安装依赖

```bash
# 进入后端目录
cd /path/to/reg\ mini\ program

# 启用虚拟环境
source venv/bin/activate

# 安装新依赖（包含CORS支持）
pip install -r requirements.txt
```

新增依赖:
- `Flask-CORS` - 支持跨域请求
- `PyJWT` - JWT Token管理

### 2. 环境变量配置

创建 `.env` 文件或在腾讯云环境变量中设置：

```bash
# 微信小程序配置
WX_MINI_APP_ID=wx39c27f1ca93c8893
WX_MINI_APP_SECRET=your_app_secret_here  # 从微信公众平台获取

# CORS配置（可选，默认允许所有来源）
CORS_ORIGINS=*

# Flask配置
SECRET_KEY=your-secret-key-here
FLASK_ENV=production
```

### 3. 启动后端服务

#### 本地开发

```bash
python src/main.py --host 0.0.0.0 --port 8082
```

#### 腾讯云部署

```bash
# 使用Gunicorn
gunicorn -w 4 -b 0.0.0.0:8082 wsgi:app
```

### 4. 关键API端点

#### 微信登录
```
POST /auth/wx-login
Content-Type: application/json

{
  "code": "微信授权码"
}

Response:
{
  "success": true,
  "user_id": 123,
  "username": "wx_openid",
  "email": "openid@weixin.local",
  "session_token": "Bearer token用于API认证",
  "is_new_user": false
}
```

#### 验证Token
```
POST /auth/session-token-validate
Header: Authorization: Bearer {session_token}

Response:
{
  "valid": true,
  "user_id": 123,
  "username": "用户名"
}
```

#### 获取首页活动
```
GET /api/home-activities?page=1&page_size=10

Response:
{
  "success": true,
  "activities": [...]
}
```

#### 获取活动列表
```
GET /activities?page=1&page_size=10&status=active&search=keyword

Response:
{
  "success": true,
  "activities": [...]
}
```

#### 获取活动详情
```
GET /activity/{activity_id}

Response:
{
  "success": true,
  "activity": {...}
}
```

---

## 二、小程序开发

### 1. 微信开发者工具配置

#### 下载微信开发者工具
- [Windows](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
- [Mac](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)

#### 导入项目

1. 打开微信开发者工具
2. 选择 `打开` → 选择 `miniprogram` 文件夹
3. 输入项目名称：`智能社团+-小程序`
4. 选择`Backend Framework`: `React/Vue`,`TS`等（如无需选则不选）
5. `确定` 创建项目

#### 项目配置

打开 `miniprogram/miniprogram.config.json`（或微信开发者工具自动生成）：

```json
{
  "appid": "wx39c27f1ca93c8893",
  "projectname": "智能社团+-小程序",
  "description": "高校社团活动管理平台",
  "auth": [],
  "scripts": {},
  "compileType": "miniprogram",
  "libVersion": "3.0.0",
  "isGameTouching": false,
  "simulatorType": "wechat",
  "simulatorPluginLibVersion": {},
  "condition": {},
  "editorSetting": {
    "tabIndent": "auto",
    "tabSize": 2
  }
}
```

### 2. 更新API基地址

在 `miniprogram/utils/config.js` 中配置API服务器地址：

```javascript
// 生产环境
production: {
  apiBaseUrl: 'https://your-domain.com',  // 替换为腾讯云域名
  requestTimeout: 10000,
  retryCount: 2,
  retryDelay: 1000,
  debug: false
}

// 开发/测试环境
development: {
  apiBaseUrl: 'http://localhost:8082',  // 本地测试
  requestTimeout: 10000,
  retryCount: 2,
  retryDelay: 1000,
  debug: true
}
```

### 3. 在微信发布前的准备

#### 配置服务器域名

登录[微信公众平台](https://mp.weixin.qq.com/) → 开发 → 开发设置 → 服务器域名

添加以下域名：

- 请求合法域名：`https://your-domain.com`
- 文件上传域名：`https://your-domain.com`
- 文件下载域名：`https://your-domain.com`
- WebSocket 多媒体域名（如需）

#### 配置业务域名

- 业务域名：`https://your-domain.com`

### 4. 小程序编译与运行

1. 在微信开发者工具中点击 `编译` （Ctrl+B / Cmd+B）
2. 左侧模拟器会显示编译后的小程序
3. 可在真机上扫描预览二维码进行测试

### 5. 提交审核与发布

1. 在微信开发者工具中点击 `上传` 
2. 输入版本号和项目备注
3. 登录[微信公众平台](https://mp.weixin.qq.com/) → 版本管理 → 待审核
4. 提交审核
5. 审核通过后，点击 `发布` 使用新版本

---

## 三、腾讯云部署

### 1. COS 配置（用于托管图片等资源）

#### 创建 COS 存储桶

1. 登录[腾讯云COS控制台](https://console.cloud.tencent.com/cos)
2. 创建存储桶，名称如：`cqnu-association-1254343456`
3. 配置跨域访问规则：

```json
{
  "AllowedMethods": ["GET", "POST", "PUT", "HEAD", "DELETE"],
  "AllowedHeaders": ["*"],
  "AllowedOrigins": ["*"],
  "ExposeHeaders": ["Content-Length", "ETag"],
  "MaxAgeSeconds": 3600
}
```

#### 配置静态网站托管

1. 在存储桶设置中启用 `静态网站托管`
2. 设置索引文档为 `index.html`
3. 获取访问 URL，如：`https://cqnu-association-1254343456.cos.ap-beijing.myqcloud.com`

### 2. SCF 云函数部署（可选）

如需使用服务端渲染或特殊业务逻辑，可部署为云函数后由小程序调用：

```bash
# 1. 安装腾讯云 SDK
pip install tencentcloud-sdk-python

# 2. 编写函数代码
# 3. 使用 tccli 部署
```

### 3. CloudBase 托管部署（推荐）

#### 初始化 CloudBase

```bash
# 安装 tcb-cli
npm install -g @cloudbase/cli

# 登录腾讯云
tcb login

# 初始化项目
tcb init

# 部署
tcb deploy
```

### 4. Flask 应用部署（Linux ECS/轻量应用服务器）

#### 创建应用

1. 登录[腾讯云控制台](https://console.cloud.tencent.com)
2. 创建轻量应用服务器或 ECS
3. 选择操作系统：Ubuntu 20.04 LTS
4. SSH 连接到服务器

#### 环境配置

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装依赖
sudo apt install -y python3 python3-pip python3-venv git nginx supervisor

# 克隆项目
git clone your-repo-url
cd reg\ mini\ program

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 创建环境文件
nano .env  # 添加 WX_MINI_APP_SECRET 等配置
```

#### 配置 Nginx

创建 `/etc/nginx/sites-available/cqnu_association`:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    client_max_body_size 80M;

    # HTTP 重定向到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/your-cert.pem;
    ssl_certificate_key /path/to/your-key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 80M;

    # 静态文件
    location /static/ {
        alias /home/ubuntu/reg\ mini\ program/src/static/;
        expires 30d;
    }

    # API 代理
    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        proxy_connect_timeout 10s;
    }
}
```

启用站点：

```bash
sudo ln -s /etc/nginx/sites-available/cqnu_association /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

#### 配置 Supervisor（进程管理）

创建 `/etc/supervisor/conf.d/cqnu_association.conf`:

```ini
[program:cqnu_association]
directory=/home/ubuntu/reg\ mini\ program
command=/home/ubuntu/reg\ mini\ program/venv/bin/gunicorn -w 4 -b 127.0.0.1:8082 wsgi:app
user=ubuntu
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/cqnu_association.log
```

重启 Supervisor：

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start cqnu_association
```

#### 配置 SSL 证书（Let's Encrypt）

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书
sudo certbot certonly --standalone -d your-domain.com

# 自动更新（Cron）
sudo certbot renew --quiet
```

---

## 四、常见问题

### 1. 小程序无法登录

**问题**：微信登录返回 `errcode: 40001`

**解决**：
- 确认 AppID 和 AppSecret 正确
- 检查服务器域名是否已在微信平台配置
- 确认请求来自 HTTPS（微信要求）

### 2. CORS 错误

**问题**：`No 'Access-Control-Allow-Origin' header`

**解决**：
- 确认后端已安装 `flask-cors`
- 验证 CORS 配置是否正确
- 检查 URL 是否以 `https://` 开头

### 3. 数据不显示

**问题**：活动列表为空

**解决**：
- 检查数据库是否有数据
- 查看后端日志是否有错误
- 验证API端点是否正确

### 4. 上传文件失败

**问题**：`413 Payload Too Large`

**解决**：
- 检查 Nginx 配置中 `client_max_body_size` 是否足够大
- 验证 Flask 配置中 `MAX_CONTENT_LENGTH` 设置

---

## 五、性能优化建议

### 1. 缓存策略

```javascript
// 小程序端缓存活动列表
wx.setStorage({
  key: 'activitiesCache',
  data: activities,
  success: () => {
    // 缓存成功，下次打开可直接显示，等待新数据加载
  }
});
```

### 2. 图片优化

```javascript
// 使用图片压缩和适配
<image src="{{item.poster_image}}" mode="aspectFill" style="width: 100%; height: 160px;" />
```

### 3. 数据分页

```javascript
// 每页10条，按需加载
page: 1,
pageSize: 10,
hasMore: true
```

### 4. 预加载

```javascript
// 在用户进入活动列表时预加载详情页资源
wx.getImageInfo({
  src: activity.poster_image
});
```

---

## 六、后续功能建议

### MVP 阶段（已完成）
- [x] 微信登录
- [x] 首页展示
- [x] 活动列表
- [x] 活动详情
- [x] 用户登录/注册

### Phase 2（推荐）
- [ ] 报名活动
- [ ] 签到功能
- [ ] 个人资料编辑
- [ ] 消息通知
- [ ] 积分展示

### Phase 3（可选）
- [ ] 支付功能
- [ ] 分享海报生成
- [ ] 评价功能
- [ ] AI推荐
- [ ] 视频直播

---

## 七、监控与维护

### 查看日志

```bash
# 后端日志
tail -f /var/log/cqnu_association.log

# Nginx 日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log

# Supervisor 日志
tail -f /var/log/supervisor/cqnu_association.log
```

### 性能监控

```bash
# CPU 使用率
top

# 内存使用
free -h

# 数据库连接
ps aux | grep python
```

### 定期备份

```bash
# 数据库备份
mysqldump -u root -p database_name > backup_$(date +%Y%m%d).sql

# 代码备份
tar -czvf backup_code_$(date +%Y%m%d).tar.gz .
```

---

## 八、安全建议

- ✅ 使用 HTTPS（Let's Encrypt 证书）
- ✅ 定期更新依赖包
- ✅ 实施限流保护（已配置）
- ✅ 动态密码验证（微信 session）
- ✅ CSRF 保护（已启用）
- ✅ 数据加密存储
- ✅ API 速率限制
- ✅ 定期安全审计

---

## 联系支持

如有问题，请提交 Issue 或联系技术支持。
