#!/usr/bin/env bash
set -euo pipefail

database_host="${1:?database host is required}"
database_port="${2:?database port is required}"
database_password_file="${3:?database password file is required}"
app_root="${4:-/opt/webfetch}"
artifact_root="${5:-/var/lib/webfetch/artifacts}"
listen_port="${6:-33333}"
proxy_url="${7:-}"

if [[ ! -s "$database_password_file" ]]; then
  echo "database password file is missing or empty" >&2
  exit 2
fi

if ! id webfetch >/dev/null 2>&1; then
  useradd --system --home /var/lib/webfetch --shell /usr/sbin/nologin webfetch
fi

install -d -m 0750 -o root -g webfetch /etc/webfetch
install -d -m 0750 -o webfetch -g webfetch "$artifact_root"
install -d -m 0755 -o webfetch -g webfetch "$app_root"

database_password="$(tr -d '\r\n' < "$database_password_file")"
api_key="$(openssl rand -hex 32)"
umask 027
printf '%s\n' "$api_key" > /etc/webfetch/api-key
chown root:webfetch /etc/webfetch/api-key
chmod 0640 /etc/webfetch/api-key

cat > /etc/webfetch/service.env <<EOF
WEBFETCH_ENVIRONMENT=production
WEBFETCH_SERVER__HOST=0.0.0.0
WEBFETCH_SERVER__PORT=$listen_port
WEBFETCH_SERVER__LOG_LEVEL=INFO
WEBFETCH_AUTH__BOOTSTRAP_API_KEY=$api_key
WEBFETCH_AUTH__BOOTSTRAP_CLIENT_NAME=bootstrap
WEBFETCH_DATABASE__ENABLED=true
WEBFETCH_DATABASE__URL=postgresql+asyncpg://webfetch:$database_password@$database_host:$database_port/webfetch
WEBFETCH_DATABASE__CREATE_SCHEMA_ON_START=false
WEBFETCH_REDIS__ENABLED=true
WEBFETCH_REDIS__URL=redis://127.0.0.1:6379/0
WEBFETCH_REDIS__KEY_PREFIX=webfetch:
WEBFETCH_STORAGE__ARTIFACT_ROOT=$artifact_root
WEBFETCH_STORAGE__SAVE_ARTIFACTS_BY_DEFAULT=true
WEBFETCH_PROXY__DEFAULT_POLICY=direct
WEBFETCH_PROXY__HTTP_URL=$proxy_url
WEBFETCH_BROWSER__ENABLED=true
WEBFETCH_BROWSER__CONCURRENCY=2
WEBFETCH_FETCH__DEFAULT_CACHE_TTL=3600
WEBFETCH_FETCH__DEFAULT_DOMAIN_INTERVAL_SECONDS=1.0
WEBFETCH_FETCH__DEFAULT_DOMAIN_CONCURRENCY=4
WEBFETCH_FETCH__MAX_ATTEMPTS=3
WEBFETCH_FETCH__MAX_RESPONSE_BYTES=10485760
WEBFETCH_SECURITY__ALLOW_PRIVATE_NETWORKS=false
WEBFETCH_SECURITY__ALLOWED_HOSTS=[]
WEBFETCH_SECURITY__ALLOWED_CIDRS=[]
WEBFETCH_APP_ROOT=$app_root
EOF

chown root:webfetch /etc/webfetch/service.env
chmod 0640 /etc/webfetch/service.env
systemctl enable --now redis-server
redis-cli ping
echo "server_configuration_created=/etc/webfetch/service.env"
echo "api_key_file_created=/etc/webfetch/api-key"

