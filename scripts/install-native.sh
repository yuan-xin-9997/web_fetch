#!/usr/bin/env bash
set -euo pipefail

source_dir="${1:?source directory is required}"
app_root="${2:-/opt/webfetch}"
service_user="${3:-webfetch}"
release_id="${BUILD_TAG:-$(date -u +%Y%m%d%H%M%S)}"
release_dir="$app_root/releases/$release_id"
previous="$(readlink -f "$app_root/current" 2>/dev/null || true)"
services=(webfetch-browser-worker webfetch-http-worker webfetch-api)

if [[ ! -f /etc/webfetch/service.env ]]; then
  echo "/etc/webfetch/service.env is missing; create it from .env.example first" >&2
  exit 2
fi

install -d -o "$service_user" -g "$service_user" "$app_root/releases" /var/lib/webfetch/artifacts
install -d -m 0750 -o root -g "$service_user" /etc/webfetch
install -d "$release_dir"
rsync -a --delete \
  --exclude .git --exclude .venv --exclude data --exclude __pycache__ \
  "$source_dir/" "$release_dir/"
chown -R "$service_user:$service_user" "$release_dir" /var/lib/webfetch

sudo -u "$service_user" python3 -m venv "$release_dir/.venv"
sudo -u "$service_user" "$release_dir/.venv/bin/python" -m pip install --upgrade pip
sudo -u "$service_user" "$release_dir/.venv/bin/python" -m pip install "$release_dir[browser]"
sudo -u "$service_user" "$release_dir/.venv/bin/playwright" install chromium

install -m 0755 "$release_dir/deploy/webfetch-launch" /usr/local/bin/webfetch-launch
install -m 0644 "$release_dir"/deploy/systemd/*.service /etc/systemd/system/
install -m 0644 "$release_dir"/deploy/systemd/*.timer /etc/systemd/system/

ln -sfn "$release_dir" "$app_root/current"
port="$(sed -n 's/^WEBFETCH_SERVER__PORT=//p' /etc/webfetch/service.env | tail -n 1)"
"$release_dir/.venv/bin/python" - "$release_dir" <<'PY'
import os
import subprocess
import sys

from dotenv import dotenv_values

release_dir = sys.argv[1]
environment = os.environ.copy()
environment.update({
    key: value for key, value in dotenv_values("/etc/webfetch/service.env", interpolate=False).items()
    if value is not None
})
subprocess.run(
    [f"{release_dir}/.venv/bin/alembic", "-c", f"{release_dir}/alembic.ini", "upgrade", "head"],
    env=environment, check=True,
)
PY
for service in "${services[@]}"; do
  systemctl stop "$service" 2>/dev/null || true
done
systemctl daemon-reload
systemctl enable webfetch-api webfetch-http-worker webfetch-browser-worker webfetch-maintenance.timer
systemctl restart webfetch-api webfetch-http-worker webfetch-browser-worker webfetch-maintenance.timer

port="${port:-33333}"
ready=false
for _ in $(seq 1 30); do
  if curl --fail --silent "http://127.0.0.1:$port/health/ready" >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
if [[ "$ready" != true ]]; then
  echo "health check failed" >&2
  if [[ -n "$previous" && -d "$previous" ]]; then
    ln -sfn "$previous" "$app_root/current"
    systemctl restart webfetch-api webfetch-http-worker webfetch-browser-worker
  fi
  exit 1
fi

echo "deployed_release=$release_dir"
