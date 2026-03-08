#!/usr/bin/env bash
set -euo pipefail

SERVER_IP="49.234.20.60"
SERVER_USER="ubuntu"
DOMAIN="reg.cqaibase.cn"
APP_DIR="/var/www/reg/current"
SERVICE_NAME="reg"
DB_NAME="reg_db"
DB_USER="reg_user"

DB_PASSWORD="${DB_PASSWORD:-}"
GEMINI_API_KEY="${GEMINI_API_KEY:-}"
GOOGLE_API_KEY="${GOOGLE_API_KEY:-${GEMINI_API_KEY}}"
if [[ -z "${DB_PASSWORD}" ]]; then
  DB_PASSWORD="$(python3 - << 'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/8] 准备服务器目录"
ssh ${SERVER_USER}@${SERVER_IP} "sudo mkdir -p ${APP_DIR} && sudo chown -R ${SERVER_USER}:${SERVER_USER} /var/www/reg"

echo "[2/8] 同步项目代码"
rsync -az --delete \
  --exclude '.git' \
  --exclude '.github' \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'instance/*.db' \
  --exclude 'scripts/*.log' \
  --exclude '.env' \
  "${PROJECT_ROOT}/" ${SERVER_USER}@${SERVER_IP}:${APP_DIR}/

echo "[3/8] 安装依赖并创建虚拟环境"
ssh ${SERVER_USER}@${SERVER_IP} "cd ${APP_DIR} && python3 -m venv venv && source venv/bin/activate && pip install -U pip && pip install -r requirements.txt"

echo "[4/8] 创建 PostgreSQL 数据库"
ssh ${SERVER_USER}@${SERVER_IP} "sudo -u postgres psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'\" | grep -q 1 || sudo -u postgres psql -c \"CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';\"; sudo -u postgres psql -tc \"SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'\" | grep -q 1 || sudo -u postgres psql -c \"CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};\"; sudo -u postgres psql -c \"GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};\""

echo "[5/8] 生成环境变量文件（仅当不存在时创建）"
ssh ${SERVER_USER}@${SERVER_IP} "if [ ! -f ${APP_DIR}/.env ]; then cat > ${APP_DIR}/.env << 'EOF'
FLASK_CONFIG=production

# App
APP_NAME=cqnureg
APP_TIMEZONE=Asia/Shanghai
TIMEZONE_NAME=Asia/Shanghai

# Security
SECURITY_PASSWORD_SALT=cqnu-association-secret-key-12345

# API Keys
AMAP_API_KEY=
ARK_API_KEY=
GEMINI_API_KEY=
GOOGLE_API_KEY=

# Mail
MAIL_SERVER=smtp.qq.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USE_SSL=false
MAIL_USERNAME=stuart01@qq.com
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=stuart01@qq.com
MAIL_SUBJECT_PREFIX=[智能社团+]

# Sync
IMMEDIATE_SYNC=false
SYNC_INTERVAL_HOURS=6

# DB tuning / fallback
DB_CONNECT_TIMEOUT=8
SQLALCHEMY_ECHO=false
BACKUP_DATABASE_URL=

SECRET_KEY=$(python3 - << 'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}
EOF
else
  echo '.env 文件已存在，跳过覆盖以保留原有配置（包括持续会话）。'
fi"

echo "[5.1/8] 同步 Gemini API Key（仅当本地环境变量已设置）"
if [[ -n "${GEMINI_API_KEY}" ]]; then
  ssh ${SERVER_USER}@${SERVER_IP} "if grep -q '^GEMINI_API_KEY=' ${APP_DIR}/.env; then sed -i \"s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${GEMINI_API_KEY}|\" ${APP_DIR}/.env; else echo \"GEMINI_API_KEY=${GEMINI_API_KEY}\" >> ${APP_DIR}/.env; fi"
  echo "已同步 GEMINI_API_KEY 到服务器 .env"
else
  echo "本地未设置 GEMINI_API_KEY，跳过同步。"
fi

if [[ -n "${GOOGLE_API_KEY}" ]]; then
  ssh ${SERVER_USER}@${SERVER_IP} "if grep -q '^GOOGLE_API_KEY=' ${APP_DIR}/.env; then sed -i \"s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=${GOOGLE_API_KEY}|\" ${APP_DIR}/.env; else echo \"GOOGLE_API_KEY=${GOOGLE_API_KEY}\" >> ${APP_DIR}/.env; fi"
  echo "已同步 GOOGLE_API_KEY 到服务器 .env"
fi

echo "[6/8] 检查并重载 systemd 服务"
ssh ${SERVER_USER}@${SERVER_IP} "if [ ! -f /etc/systemd/system/${SERVICE_NAME}.service ]; then sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=Gunicorn service for reg.cqaibase.cn
After=network.target

[Service]
User=${SERVER_USER}
Group=www-data
WorkingDirectory=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/venv/bin/gunicorn --preload --workers 3 --bind 127.0.0.1:8082 --timeout 120 wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable ${SERVICE_NAME}.service
fi
sudo systemctl restart ${SERVICE_NAME}.service"

echo "[7/8] 检查并配置 Nginx 站点"
ssh ${SERVER_USER}@${SERVER_IP} "if [ ! -f /etc/nginx/sites-available/reg ]; then sudo tee /etc/nginx/sites-available/reg > /dev/null << 'EOF'
server {
    listen 80;
    server_name reg.cqaibase.cn;

    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/reg /etc/nginx/sites-enabled/reg
fi
sudo nginx -t && sudo systemctl reload nginx"

echo "[8/8] 申请免费 SSL（DNS 生效后）"
if dig +short ${DOMAIN} A | grep -q "${SERVER_IP}"; then
  ssh ${SERVER_USER}@${SERVER_IP} "sudo certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos -m admin@cqaibase.cn --redirect"
  echo "SSL 已申请并配置完成。"
else
  echo "当前 ${DOMAIN} 未解析到 ${SERVER_IP}，暂未执行 certbot。"
  echo "请先将 A 记录改到 ${SERVER_IP}，再执行："
  echo "ssh ${SERVER_USER}@${SERVER_IP} 'sudo certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos -m admin@cqaibase.cn --redirect'"
fi

echo "部署完成。检查命令："
echo "ssh ${SERVER_USER}@${SERVER_IP} 'systemctl status ${SERVICE_NAME} --no-pager'"
echo "ssh ${SERVER_USER}@${SERVER_IP} 'sudo nginx -t && sudo systemctl status nginx --no-pager'"
echo "PostgreSQL 连接串：postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"
