#!/bin/bash
# Server setup for Amazon Linux 2023 (arm64 or x86_64). Idempotent: re-run to update.
#   sudo REPO=https://github.com/cosmos-dx/claude-blooded.git bash bootstrap.sh
set -euo pipefail
REPO="${REPO:-https://github.com/cosmos-dx/claude-blooded.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/claude-blooded
DATA_DIR=/var/lib/claude-blooded
ENV_FILE=/etc/claude-blooded.env

# 512 MB machines need swap for installs and renders
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

dnf -y -q install python3.12 python3.12-pip git nginx tar xz

if ! command -v ffmpeg >/dev/null; then        # static ffmpeg (AL2023 has no ffmpeg package)
  case "$(uname -m)" in aarch64) a=arm64 ;; *) a=amd64 ;; esac
  curl -fsSL "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-$a-static.tar.xz" -o /tmp/ffmpeg.tar.xz
  mkdir -p /opt/ffmpeg && tar -xJf /tmp/ffmpeg.tar.xz -C /opt/ffmpeg --strip-components=1
  ln -sf /opt/ffmpeg/ffmpeg /usr/local/bin/ffmpeg && ln -sf /opt/ffmpeg/ffprobe /usr/local/bin/ffprobe
fi

id blooded >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --shell /sbin/nologin blooded
mkdir -p "$DATA_DIR" && chown blooded:blooded "$DATA_DIR"

if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" fetch -q origin "$BRANCH" && git -C "$APP_DIR" reset -q --hard "origin/$BRANCH"
else git clone -q --depth 1 -b "$BRANCH" "$REPO" "$APP_DIR"; fi
[ -x "$APP_DIR/.venv/bin/python" ] || python3.12 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
sh "$APP_DIR/deploy/fetch_fonts.sh" /usr/share/fonts/reel

if [ ! -f "$ENV_FILE" ]; then                     # first run: template with a fresh JWT secret
  sed "s|^JWT_SECRET=.*|JWT_SECRET=$(python3.12 -c 'import secrets;print(secrets.token_urlsafe(64))')|" "$APP_DIR/.env.example" > "$ENV_FILE"
fi
chown root:blooded "$ENV_FILE" && chmod 640 "$ENV_FILE"

# Database: a real DATABASE_URL in the env file wins; otherwise run Postgres on this box (localhost only)
if grep -qE '^DATABASE_URL=(.*USER:PASSWORD@HOST.*)?$' "$ENV_FILE"; then
  dnf -y -q install postgresql16-server || dnf -y -q install postgresql15-server
  [ -f /var/lib/pgsql/data/PG_VERSION ] || postgresql-setup --initdb >/dev/null
  sed -i -E 's/^(host[[:space:]]+all[[:space:]]+all[[:space:]]+(127\.0\.0\.1\/32|::1\/128)[[:space:]]+)ident/\1scram-sha-256/' /var/lib/pgsql/data/pg_hba.conf
  systemctl enable -q --now postgresql
  cd /tmp
  sudo -u postgres psql -q -c "ALTER SYSTEM SET listen_addresses = 'localhost'" -c "ALTER SYSTEM SET max_connections = 20" \
    -c "ALTER SYSTEM SET shared_buffers = '32MB'" -c "ALTER SYSTEM SET work_mem = '2MB'" \
    -c "ALTER SYSTEM SET maintenance_work_mem = '16MB'" -c "ALTER SYSTEM SET effective_cache_size = '128MB'"
  systemctl restart postgresql
  PGPW=$(python3.12 -c 'import secrets;print(secrets.token_urlsafe(24))')
  if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'blooded'" | grep -q 1; then
    sudo -u postgres psql -q -c "ALTER ROLE blooded PASSWORD '$PGPW'"
  else
    sudo -u postgres psql -q -c "CREATE ROLE blooded LOGIN PASSWORD '$PGPW'"
  fi
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = 'claude_blooded'" | grep -q 1 \
    || sudo -u postgres createdb -O blooded -E UTF8 -T template0 claude_blooded
  sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://blooded:$PGPW@127.0.0.1:5432/claude_blooded|" "$ENV_FILE"
  cd - >/dev/null
fi

install -m 644 "$APP_DIR/deploy/claude-blooded-api.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/claude-blooded-worker.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/nginx.conf" /etc/nginx/nginx.conf
systemctl daemon-reload
systemctl enable -q --now nginx claude-blooded-api claude-blooded-worker
systemctl restart claude-blooded-api claude-blooded-worker
nginx -t -q && systemctl reload nginx
echo "bootstrap done. Edit $ENV_FILE, then: sudo systemctl restart claude-blooded-api claude-blooded-worker"
