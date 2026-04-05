# 🚀 快速开始 - 微信小程序版本

> 项目已成功改造为微信小程序版本，完全支持微信登录和腾讯云部署！

## ⚡ 5分钟快速启动（本地测试）

### 1️⃣ 启动后端服务

```bash
cd "/Users/luoyixin/Desktop/💻编程项目/reg mini program"
source venv/bin/activate
python src/main.py --host 0.0.0.0 --port 8082
```

✅ 看到 `Running on http://0.0.0.0:8082` 表示成功

### 2️⃣ 打开微信开发者工具

1. 下载 [微信开发者工具](https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html)
2. 打开 → 选择项目文件夹 → `miniprogram`
3. AppID 已配置：`wx39c27f1ca93c8893`
4. 点击 `编译` (Ctrl+B)

✅ 模拟器中应显示"智能社团+"首页

### 3️⃣ 配置 API 地址

编辑 `miniprogram/utils/config.js`，找到开发环境配置：

```javascript
development: {
  apiBaseUrl: 'http://localhost:8082',  // 本地测试
  ...
}
```

💾 保存后自动刷新

### 4️⃣ 测试登录

在小程序模拟器中：
1. 点击首页 "登录" 按钮
2. 选择 "微信登录" 
3. 应该能成功登录

---

## 🌐 腾讯云部署（完整指南）

### Phase 1: 后端部署

#### 环境变量配置
```bash
# SSH 连接到腾讯云服务器
ssh ubuntu@your-server-ip

# 创建 .env 文件
cat > .env << 'EOF'
WX_MINI_APP_ID=wx39c27f1ca93c8893
WX_MINI_APP_SECRET=your-secret-from-wechat
FLASK_ENV=production
SECRET_KEY=your-random-secret
DATABASE_URL=postgresql://username:password@db-host:5432/db_name
REDIS_URL=redis://:password@redis-host:6379/0
EOF
```

#### 使用 Supervisor 和 Nginx 部署
详见完整指南：`MINIPROGRAM_DEPLOYMENT.md`

### Phase 2: 小程序发布

#### 在微信公众平台配置域名
1. 登录 https://mp.weixin.qq.com/
2. 开发 → 开发设置 → 服务器域名
3. 添加 HTTPS 域名：`https://your-domain.com`

#### 提交审核
1. 微信开发者工具 → 上传
2. 微信公众平台 → 版本管理 → 提交审核
3. 审核通过 → 发布

---

## 📁 项目结构

```
miniprogram/
├── app.json                # 小程序配置
├── app.js                  # 全局逻辑  
├── app.wxss                # 全局样式
├── pages/
│   ├── index/             # ✅ 首页完成
│   ├── activities/        # ✅ 活动列表完成
│   ├── activity-detail/   # ✅ 活动详情完成
│   ├── auth/login         # ✅ 登录完成
│   ├── my-activities/     # ⏳ 规划中
│   └── profile/           # ⏳ 规划中
└── utils/
    ├── api.js            # ✅ API 服务层
    ├── config.js         # ✅ 配置文件
    └── utils.js          # ✅ 工具函数
```

---

## 🔑 重要命令

```bash
# 后端专用
python src/main.py                    # 启动开发服务
gunicorn -w 4 -b 0.0.0.0:8082 wsgi:app  # 生产部署

# 小程序专用  
# 使用微信开发者工具的 UI 界面操作

# 腾讯云专用
supervisorctl status cqnu_association     # 查看应用状态
supervisorctl restart cqnu_association    # 重启应用
tail -f /var/log/cqnu_association.log     # 查看日志
```

---

## 🐛 常见问题速查

| 问题 | 解决方案 |
|------|--------|
| 微信登录失败 | 检查 WX_MINI_APP_SECRET 是否正确 |
| CORS 错误 | 确保后端已重启，检查域名配置 |
| 活动数据为空 | 检查数据库是否有数据 |
| 上传文件失败 | 增加 client_max_body_size 到 80M |

详见：`MINIPROGRAM_COMPLETE_GUIDE.md`

---

## 📚 完整文档

- **部署指南**: [`MINIPROGRAM_DEPLOYMENT.md`](MINIPROGRAM_DEPLOYMENT.md)
- **完整手册**: [`MINIPROGRAM_COMPLETE_GUIDE.md`](MINIPROGRAM_COMPLETE_GUIDE.md)
- **环境变量**: [`.env.example.miniprogram`](.env.example.miniprogram)

---

## ✅ 功能清单

### 已完成  
- [x] 微信登录集成
- [x] 首页推荐活动
- [x] 活动列表搜索筛选
- [x] 活动详情展示
- [x] 报名和签到
- [x] API 认证机制
- [x] CORS 跨域支持
- [x] 完整文档

### 规划中
- [ ] 我的活动页面
- [ ] 个人资料编辑
- [ ] 消息通知系统
- [ ] 积分排行榜

### 可选功能
- [ ] 支付功能
- [ ] 分享海报生成
- [ ] 活动评价
- [ ] AI 推荐

---

## 💡 最佳实践建议

### 开发阶段
1. 使用本地 SQLite 数据库快速迭代
2. 启用 Flask 调试模式和热重载
3. 在微信开发者工具中测试全部流程

### 测试阶段
1. 真机测试各项功能
2. 检查网络差和高延迟场景
3. 测试微信官方 API 的异常情况

### 上线阶段
1. 配置 HTTPS 和 SSL 证书
2. 启用监控和告警
3. 定期备份数据库
4. 设置自动化部署流程

---

## 🆘 获取帮助

### 查看日志
```bash
# 后端日志
tail -f logs/cqnu_association.log

# 微信开发者工具
右键 → 调试 → Console
```

### 检查配置
```bash
# 查看环境变量
cat .env

# 验证数据库连接
psql $DATABASE_URL -c "SELECT 1"

# 验证 Redis 连接
redis-cli -u $REDIS_URL ping
```

### 提交问题
请提供以下信息：
1. 错误日志（完整输出）
2. 重现步骤
3. 系统环境（OS、Python版本等）
4. 已尝试的解决方案

---

## 🎯 下一步行动

### 立即开始
1. ✅ 启动本地后端服务
2. ✅ 打开小程序预览效果
3. ✅ 测试微信登录功能

### 1-2周内
- [ ] 完成其他页面逻辑
- [ ] 进行完整功能测试
- [ ] 部署到腾讯云测试环境

### 2-4周内
- [ ] 进行性能优化
- [ ] 安全审计
- [ ] 提交微信审核

---

**版本**: v1.0.0  
**更新日期**: 2026年4月4日  
**项目位置**: `/Users/luoyixin/Desktop/💻编程項目/reg mini program`
