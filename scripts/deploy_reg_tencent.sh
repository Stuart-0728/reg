#!/usr/bin/env bash
set -euo pipefail

SERVER_IP="49.234.20.60"
SERVER_USER="ubuntu"
DOMAIN="reg.cqaibase.cn"
APP_DIR="/var/www/reg/current"
STORAGE_DIR="/var/www/reg/storage"
ACTIVITY_DOCS_DIR="${STORAGE_DIR}/activity_docs"
SERVICE_NAME="reg"
DB_NAME="reg_db"
DB_USER="reg_user"

DB_PASSWORD="${DB_PASSWORD:-}"
GEMINI_API_KEY="${GEMINI_API_KEY:-}"
GOOGLE_API_KEY="${GOOGLE_API_KEY:-${GEMINI_API_KEY}}"
DIGITAL_HUMAN_APP_ID="${DIGITAL_HUMAN_APP_ID:-a9ef6b21}"
DIGITAL_HUMAN_API_KEY="${DIGITAL_HUMAN_API_KEY:-fc992cb7d37d74ba0dd2284f02e671c2}"
DIGITAL_HUMAN_API_SECRET="${DIGITAL_HUMAN_API_SECRET:-Y2E0NTA2NWRkMTI4MWZkZTQ4OGE5ZTY4}"
DIGITAL_HUMAN_SCENE_ID="${DIGITAL_HUMAN_SCENE_ID:-298285519761182720}"
DIGITAL_HUMAN_AVATAR_ID="${DIGITAL_HUMAN_AVATAR_ID:-111165001}"
DIGITAL_HUMAN_VCN="${DIGITAL_HUMAN_VCN:-x4_yezi}"
DIGITAL_HUMAN_WIDTH="${DIGITAL_HUMAN_WIDTH:-1920}"
DIGITAL_HUMAN_HEIGHT="${DIGITAL_HUMAN_HEIGHT:-1280}"
DIGITAL_HUMAN_BITRATE="${DIGITAL_HUMAN_BITRATE:-1000000}"
DIGITAL_HUMAN_FPS="${DIGITAL_HUMAN_FPS:-25}"
DIGITAL_HUMAN_PROTOCOL="${DIGITAL_HUMAN_PROTOCOL:-xrtc}"
DIGITAL_HUMAN_ALPHA="${DIGITAL_HUMAN_ALPHA:-1}"
DIGITAL_HUMAN_AUDIO_FORMAT="${DIGITAL_HUMAN_AUDIO_FORMAT:-1}"
DIGITAL_HUMAN_INTERACTIVE_MODE="${DIGITAL_HUMAN_INTERACTIVE_MODE:-0}"
DIGITAL_HUMAN_TEXT_INTERACTIVE_MODE="${DIGITAL_HUMAN_TEXT_INTERACTIVE_MODE:-0}"
DIGITAL_HUMAN_CONTENT_ANALYSIS="${DIGITAL_HUMAN_CONTENT_ANALYSIS:-0}"
DIGITAL_HUMAN_MASK_REGION="${DIGITAL_HUMAN_MASK_REGION:-[0,0,1080,1920]}"
DIGITAL_HUMAN_SCALE="${DIGITAL_HUMAN_SCALE:-1}"
DIGITAL_HUMAN_MOVE_H="${DIGITAL_HUMAN_MOVE_H:-0}"
DIGITAL_HUMAN_MOVE_V="${DIGITAL_HUMAN_MOVE_V:-0}"
if [[ -z "${DB_PASSWORD}" ]]; then
  DB_PASSWORD="$(python3 - << 'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "[1/8] 准备服务器目录"
ssh ${SERVER_USER}@${SERVER_IP} "sudo mkdir -p ${APP_DIR} ${ACTIVITY_DOCS_DIR} && sudo chown -R ${SERVER_USER}:${SERVER_USER} /var/www/reg"

echo "[1.1/8] 迁移历史活动资料到持久化目录（若存在）"
ssh ${SERVER_USER}@${SERVER_IP} "LEGACY_DIR='${APP_DIR}/static/uploads/posters/activity_docs'; if [ -d \"\${LEGACY_DIR}\" ]; then mkdir -p '${ACTIVITY_DOCS_DIR}' && cp -an \"\${LEGACY_DIR}/.\" '${ACTIVITY_DOCS_DIR}/' || true; fi"

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

echo "[3.1/8] 安装中文字体（分享海报渲染）"
ssh ${SERVER_USER}@${SERVER_IP} "sudo apt-get update -y >/dev/null && sudo apt-get install -y fonts-noto-cjk fonts-wqy-zenhei >/dev/null || true"

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

# Digital human
DIGITAL_HUMAN_SERVER_URL=wss://avatar.cn-huadong-1.xf-yun.com/v1/interact
DIGITAL_HUMAN_APP_ID=
DIGITAL_HUMAN_API_KEY=
DIGITAL_HUMAN_API_SECRET=
DIGITAL_HUMAN_SCENE_ID=
DIGITAL_HUMAN_AVATAR_ID=111165001
DIGITAL_HUMAN_VCN=x4_yezi
DIGITAL_HUMAN_WIDTH=1920
DIGITAL_HUMAN_HEIGHT=1280
DIGITAL_HUMAN_BITRATE=1000000
DIGITAL_HUMAN_FPS=25
DIGITAL_HUMAN_PROTOCOL=xrtc
DIGITAL_HUMAN_ALPHA=1
DIGITAL_HUMAN_AUDIO_FORMAT=1
DIGITAL_HUMAN_INTERACTIVE_MODE=0
DIGITAL_HUMAN_TEXT_INTERACTIVE_MODE=0
DIGITAL_HUMAN_CONTENT_ANALYSIS=0
DIGITAL_HUMAN_MASK_REGION=[0,0,1080,1920]
DIGITAL_HUMAN_SCALE=1
DIGITAL_HUMAN_MOVE_H=0
DIGITAL_HUMAN_MOVE_V=0

# Mail
MAIL_PRIMARY_SERVER=smtp.mailersend.net
MAIL_PRIMARY_PORT=587
MAIL_PRIMARY_USE_TLS=true
MAIL_PRIMARY_USE_SSL=false
MAIL_PRIMARY_USERNAME=
MAIL_PRIMARY_PASSWORD=
MAIL_PRIMARY_DEFAULT_SENDER=

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

echo "[5.0/8] 确保持久化资料目录配置"
ssh ${SERVER_USER}@${SERVER_IP} "if grep -q '^ACTIVITY_DOCS_DIR=' ${APP_DIR}/.env; then sed -i \"s|^ACTIVITY_DOCS_DIR=.*|ACTIVITY_DOCS_DIR=${ACTIVITY_DOCS_DIR}|\" ${APP_DIR}/.env; else echo \"ACTIVITY_DOCS_DIR=${ACTIVITY_DOCS_DIR}\" >> ${APP_DIR}/.env; fi"

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

echo "[5.2/8] 同步数字人参数到服务器 .env"
sync_remote_env_key() {
  local key="$1"
  local value="$2"
  local escaped_value="${value//\\/\\\\}"
  escaped_value="${escaped_value//&/\\&}"
  escaped_value="${escaped_value//|/\\|}"
  ssh ${SERVER_USER}@${SERVER_IP} "if grep -q '^${key}=' ${APP_DIR}/.env; then sed -i \"s|^${key}=.*|${key}=${escaped_value}|\" ${APP_DIR}/.env; else echo \"${key}=${escaped_value}\" >> ${APP_DIR}/.env; fi"
}

sync_remote_env_key "DIGITAL_HUMAN_APP_ID" "${DIGITAL_HUMAN_APP_ID}"
sync_remote_env_key "DIGITAL_HUMAN_API_KEY" "${DIGITAL_HUMAN_API_KEY}"
sync_remote_env_key "DIGITAL_HUMAN_API_SECRET" "${DIGITAL_HUMAN_API_SECRET}"
sync_remote_env_key "DIGITAL_HUMAN_SCENE_ID" "${DIGITAL_HUMAN_SCENE_ID}"
sync_remote_env_key "DIGITAL_HUMAN_AVATAR_ID" "${DIGITAL_HUMAN_AVATAR_ID}"
sync_remote_env_key "DIGITAL_HUMAN_VCN" "${DIGITAL_HUMAN_VCN}"
sync_remote_env_key "DIGITAL_HUMAN_WIDTH" "${DIGITAL_HUMAN_WIDTH}"
sync_remote_env_key "DIGITAL_HUMAN_HEIGHT" "${DIGITAL_HUMAN_HEIGHT}"
sync_remote_env_key "DIGITAL_HUMAN_BITRATE" "${DIGITAL_HUMAN_BITRATE}"
sync_remote_env_key "DIGITAL_HUMAN_FPS" "${DIGITAL_HUMAN_FPS}"
sync_remote_env_key "DIGITAL_HUMAN_PROTOCOL" "${DIGITAL_HUMAN_PROTOCOL}"
sync_remote_env_key "DIGITAL_HUMAN_ALPHA" "${DIGITAL_HUMAN_ALPHA}"
sync_remote_env_key "DIGITAL_HUMAN_AUDIO_FORMAT" "${DIGITAL_HUMAN_AUDIO_FORMAT}"
sync_remote_env_key "DIGITAL_HUMAN_INTERACTIVE_MODE" "${DIGITAL_HUMAN_INTERACTIVE_MODE}"
sync_remote_env_key "DIGITAL_HUMAN_TEXT_INTERACTIVE_MODE" "${DIGITAL_HUMAN_TEXT_INTERACTIVE_MODE}"
sync_remote_env_key "DIGITAL_HUMAN_CONTENT_ANALYSIS" "${DIGITAL_HUMAN_CONTENT_ANALYSIS}"
sync_remote_env_key "DIGITAL_HUMAN_MASK_REGION" "${DIGITAL_HUMAN_MASK_REGION}"
sync_remote_env_key "DIGITAL_HUMAN_SCALE" "${DIGITAL_HUMAN_SCALE}"
sync_remote_env_key "DIGITAL_HUMAN_MOVE_H" "${DIGITAL_HUMAN_MOVE_H}"
sync_remote_env_key "DIGITAL_HUMAN_MOVE_V" "${DIGITAL_HUMAN_MOVE_V}"

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
  client_max_body_size 80m;

    location / {
    proxy_read_timeout 300s;
    proxy_send_timeout 300s;
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
A_RECORDS="$(dig +short ${DOMAIN} A | tr '\n' ' ' | xargs)"
CNAME_RECORD="$(dig +short ${DOMAIN} CNAME | head -n1 | sed 's/\.$//')"

if echo "${A_RECORDS}" | grep -q "${SERVER_IP}"; then
  ssh ${SERVER_USER}@${SERVER_IP} "sudo certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos -m admin@cqaibase.cn --redirect"
  echo "SSL 已申请并配置完成。"
elif [[ -n "${CNAME_RECORD}" ]]; then
  echo "检测到 ${DOMAIN} 使用 CNAME: ${CNAME_RECORD}"
  echo "当前可能处于 EdgeOne/CDN 代理场景，HTTP-01 验证通常无法直接在源站完成。"
  echo "建议操作："
  echo "1) 在 EdgeOne 控制台为 ${DOMAIN} 配置/开启边缘证书（推荐）。"
  echo "2) 如需源站证书，临时关闭代理或改为直连源站后，再执行 certbot。"
  echo "3) 也可改用 DNS-01 验证（需 DNS API 凭据）。"
  echo "若已在 EdgeOne 配置证书，本步骤可安全跳过。"
else
  echo "当前 ${DOMAIN} 未解析到 ${SERVER_IP}，且未检测到 CNAME，暂未执行 certbot。"
  echo "请先将 A 记录改到 ${SERVER_IP}，再执行："
  echo "ssh ${SERVER_USER}@${SERVER_IP} 'sudo certbot --nginx -d ${DOMAIN} --non-interactive --agree-tos -m admin@cqaibase.cn --redirect'"
fi

echo "部署完成。检查命令："
echo "ssh ${SERVER_USER}@${SERVER_IP} 'systemctl status ${SERVICE_NAME} --no-pager'"
echo "ssh ${SERVER_USER}@${SERVER_IP} 'sudo nginx -t && sudo systemctl status nginx --no-pager'"
echo "PostgreSQL 连接串：postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}"
