#!/usr/bin/env bash
# One-time droplet provisioning for DEBRIS. Run as root ON the droplet, after the
# code is present at /opt/debris (push it first with deploy/deploy.sh from the Mac).
#
#   sudo SERVER_NAME=debris.mdeller.com bash /opt/debris/deploy/provision.sh
#
# Idempotent. Installs the service user, the venv, the systemd web service and the
# weekly timer, the nginx site and a Let's Encrypt certificate. Copied from
# AlphaFraud/deploy/provision.sh with names, paths and port changed (see REUSE.md).
set -euo pipefail

APP_DIR=/opt/debris
APP_USER=debris
BIND_ADDR="${BIND_ADDR:-127.0.0.1:8014}"

if [[ -f "$APP_DIR/.env" ]]; then set -a; source "$APP_DIR/.env"; set +a; fi
SERVER_NAME="${SERVER_NAME:-debris.mdeller.com}"

echo "==> DEBRIS provisioning for ${SERVER_NAME} on ${BIND_ADDR}"
if [[ $EUID -ne 0 ]]; then echo "Run as root."; exit 1; fi
if [[ ! -f "$APP_DIR/wsgi.py" ]]; then
  echo "No code at $APP_DIR. Push it first: bash deploy/deploy.sh (from the Mac)."; exit 1
fi

echo "==> Service user '${APP_USER}'"
id -u "$APP_USER" &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR/data" "$APP_DIR/app/static/data"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> Python venv"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" env PIP_NO_CACHE_DIR=1 "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" env PIP_NO_CACHE_DIR=1 "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

echo "==> systemd units"
cp "$APP_DIR/deploy/debris-gunicorn.service" /etc/systemd/system/
cp "$APP_DIR/deploy/debris-weekly.service"   /etc/systemd/system/
cp "$APP_DIR/deploy/debris-weekly.timer"     /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now debris-gunicorn.service
systemctl enable --now debris-weekly.timer

echo "==> nginx site"
sed -e "s/__SERVER_NAME__/${SERVER_NAME}/" -e "s|__BIND_ADDR__|${BIND_ADDR}|" \
  "$APP_DIR/deploy/nginx.debris.conf" > /etc/nginx/sites-available/debris
ln -sf /etc/nginx/sites-available/debris /etc/nginx/sites-enabled/debris
nginx -t && systemctl reload nginx

echo "==> TLS certificate"
if [[ ! -d "/etc/letsencrypt/live/${SERVER_NAME}" ]]; then
  certbot --nginx -n --agree-tos --redirect -m marc@marcdeller.com -d "${SERVER_NAME}" || \
    echo "certbot failed; the site is still served over HTTP"
fi
nginx -t && systemctl reload nginx

echo "==> Provisioned. ${SERVER_NAME} -> ${BIND_ADDR}"
systemctl --no-pager --lines=3 status debris-gunicorn.service || true
