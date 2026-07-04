#!/usr/bin/env bash
set -euo pipefail

host="${1:?database host is required}"
port="${2:?database port is required}"
admin_user="${3:?administrator user is required}"
admin_password="${4:?administrator password is required}"
sql_file="${5:?SQL file is required}"
password_output="${6:?password output file is required}"

umask 077
webfetch_password="$(openssl rand -hex 24)"
printf '%s' "$webfetch_password" > "$password_output"

PGPASSWORD="$admin_password" psql \
  --host "$host" --port "$port" --username "$admin_user" --dbname postgres \
  --set webfetch_password="$webfetch_password" --file "$sql_file"

PGPASSWORD="$webfetch_password" psql \
  --host "$host" --port "$port" --username webfetch --dbname webfetch \
  --tuples-only --no-align --command 'select current_database(), current_user'

