# 重庆师范大学师能素质协会活动报名系统

这是一个为重庆师范大学师能素质协会开发的活动报名管理系统，旨在帮助协会高效管理活动和学生报名流程。

## 系统功能

### 用户系统
- 学生用户注册（收集：姓名、学号、年级、专业、学院、手机号、QQ号）
- 管理员账户管理
- 用户登录和信息修改功能
- 密码重置功能

### 管理员功能
- 活动发布功能（标题、描述、地点、时间、截止日期等）
- 活动编辑和删除功能
- 活动报名情况查看功能
- 报名学生信息导出功能（CSV格式）
- 系统公告发布功能

### 学生功能
- 浏览可报名活动列表
- 活动详情查看
- 活动报名功能
- 查看已报名活动
- 取消报名功能

### 额外实用功能
- 响应式设计（适配手机和电脑）
- 活动搜索和筛选功能
- 活动提醒功能（即将截止提醒）
- 活动签到功能
- 数据统计和可视化（报名人数、学院分布等）
- 系统日志记录
- 数据备份功能

## 技术栈

- 后端：Flask框架
- 数据库：MySQL
- 前端：Bootstrap 5、jQuery、Chart.js
- 用户认证：Flask-Login
- 表单处理：Flask-WTF
- 数据库ORM：SQLAlchemy

## 部署说明

### 环境要求
- Python 3.6+
- MySQL 5.7+
- 所有依赖包已列在requirements.txt中

### 部署步骤

1. 创建MySQL数据库：
```sql
CREATE DATABASE cqnu_association CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 设置环境变量：
```bash
export SECRET_KEY="your-secret-key"
export DB_USERNAME="数据库用户名"
export DB_PASSWORD="数据库密码"
export DB_HOST="数据库主机"
export DB_PORT="数据库端口"
export DB_NAME="cqnu_association"
```

4. 初始化数据库：
```bash
flask db init
flask db migrate
flask db upgrade
```

5. 创建管理员账户：
```bash
flask create-admin
```

6. 启动应用：
```bash
flask run --host=0.0.0.0
```

### 默认管理员账户
- 用户名：admin
- 密码：admin123（建议首次登录后立即修改）

## 系统维护

- 定期使用管理员面板中的"数据备份"功能备份数据
- 可以通过系统日志查看用户操作记录
- 如需修改系统配置，请编辑src/main.py文件

## 项目结构

```
cqnu_association/
├── venv/                   # 虚拟环境
├── src/                    # 源代码目录
│   ├── models/             # 数据库模型
│   ├── routes/             # 路由和视图函数
│   ├── static/             # 静态文件（CSS、JS、图片）
│   ├── templates/          # HTML模板
│   ├── utils/              # 工具函数
│   └── main.py             # 应用入口
├── backups/                # 数据备份目录
├── requirements.txt        # 依赖包列表
└── README.md               # 项目说明文档
```

## 联系方式

如有任何问题或需要进一步的功能扩展，请联系系统管理员。
