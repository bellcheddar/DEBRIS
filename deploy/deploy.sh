#!/usr/bin/env bash
# Push DEBRIS from the Mac to the droplet and restart the web service.
# Deploy to debris.mdeller.com is pre-approved (spec section 0) and runs at the end
# of every phase. Adapted from AlphaFraud/deploy/deploy.sh (see REUSE.md).
#
#   bash deploy/deploy.sh                # code, data and static bundles, then restart
#   bash deploy/deploy.sh --data-only    # the weekly swap: SQLite and JSON bundles only
#   bash deploy/deploy.sh --provision    # push, then run provision.sh on the droplet
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DATA_ONLY=0
PROVISION=0
for arg in "$@"; do
  case "$arg" in
    --data-only) DATA_ONLY=1 ;;
    --provision) PROVISION=1 ;;
    *) echo "unknown flag: $arg"; exit 2 ;;
  esac
done

# Target from config/deploy.toml (host, user and layout copied from AlphaFraud/.env).
read_toml() { python3 -c "import tomllib,sys;print(tomllib.load(open('config/deploy.toml','rb')).get('$1',''))"; }
SSH_TARGET="$(read_toml ssh_target)"
APP_DIR="$(read_toml app_dir)"
APP_USER="$(read_toml app_user)"
SERVICE="$(read_toml service)"
SERVER_NAME="$(read_toml server_name)"
BIND_ADDR="$(read_toml bind_addr)"

if [[ -z "$SSH_TARGET" ]]; then
  echo "config/deploy.toml has no ssh_target. Copy config/deploy.toml.example and fill it in."
  exit 1
fi

echo "==> Target ${SSH_TARGET}:${APP_DIR} (${SERVER_NAME} -> ${BIND_ADDR})"

if [[ "$DATA_ONLY" -eq 1 ]]; then
  # The weekly swap. SQLite goes to a temp name and is moved into place on the
  # droplet so a reader never sees a half-copied file.
  echo "==> Syncing data only"
  rsync -az --info=stats1 --chmod=F644 data/debris.sqlite "${SSH_TARGET}:${APP_DIR}/data/debris.sqlite.incoming"
  rsync -az --delete --info=stats1 --chmod=D755,F644 app/static/data/ "${SSH_TARGET}:${APP_DIR}/app/static/data/"
  ssh "$SSH_TARGET" bash -s <<REMOTE
set -euo pipefail
cd "${APP_DIR}"
mv -f data/debris.sqlite.incoming data/debris.sqlite
rm -f data/debris.sqlite-wal data/debris.sqlite-shm
chown -R ${APP_USER}:${APP_USER} data app/static/data
REMOTE
  echo "==> Data swapped. No restart needed: the app opens the database per request."
  exit 0
fi

echo "==> Syncing code and static assets"
rsync -az --delete --info=stats1 --chmod=D755,F644 \
  --exclude '.venv/' --exclude '.pixi/' --exclude 'data/' --exclude '__pycache__/' \
  --exclude '*.pyc' --exclude '.git/' --exclude '.env' --exclude 'wandb/' \
  --exclude 'tests/qc_screenshots/' --exclude 'node_modules/' \
  ./ "${SSH_TARGET}:${APP_DIR}/"

echo "==> Syncing the database and the chart bundles"
ssh "$SSH_TARGET" "mkdir -p ${APP_DIR}/data ${APP_DIR}/app/static/data"
if [[ -f data/debris.sqlite ]]; then
  rsync -az --info=stats1 --chmod=F644 data/debris.sqlite "${SSH_TARGET}:${APP_DIR}/data/debris.sqlite.incoming"
fi
rsync -az --delete --info=stats1 --chmod=D755,F644 app/static/data/ "${SSH_TARGET}:${APP_DIR}/app/static/data/"

# The droplet's .env carries the serving values only; no API keys are deployed.
ssh "$SSH_TARGET" bash -s <<REMOTE
set -euo pipefail
cd "${APP_DIR}"
printf 'SERVER_NAME=%s\nBIND_ADDR=%s\nDEBRIS_DB=%s/data/debris.sqlite\n' \
  "${SERVER_NAME}" "${BIND_ADDR}" "${APP_DIR}" > .env
if [[ -f data/debris.sqlite.incoming ]]; then
  mv -f data/debris.sqlite.incoming data/debris.sqlite
  rm -f data/debris.sqlite-wal data/debris.sqlite-shm
fi
REMOTE

if [[ "$PROVISION" -eq 1 ]]; then
  echo "==> Provisioning on the droplet"
  ssh "$SSH_TARGET" "SERVER_NAME=${SERVER_NAME} BIND_ADDR=${BIND_ADDR} bash ${APP_DIR}/deploy/provision.sh"
else
  echo "==> Installing dependencies and restarting ${SERVICE}"
  ssh "$SSH_TARGET" bash -s <<REMOTE
set -euo pipefail
cd "${APP_DIR}"
if [[ ! -x .venv/bin/python ]]; then
  echo "No venv yet. Re-run with --provision."; exit 1
fi
sudo -u ${APP_USER} env PIP_NO_CACHE_DIR=1 ./.venv/bin/pip install --quiet -r requirements.txt
# rsync leaves new files root-owned; chown the code but prune the venv and the live
# database so an open reader is never disturbed.
find "${APP_DIR}" -path "${APP_DIR}/.venv" -prune -o -name 'debris.sqlite*' -prune -o \
  -exec chown ${APP_USER}:${APP_USER} {} +
systemctl restart ${SERVICE}
sleep 2
systemctl --no-pager --lines=3 status ${SERVICE} || true
REMOTE
fi

echo "==> Checking the live site"
curl -fsS --max-time 20 "https://${SERVER_NAME}/healthz" || \
  curl -fsS --max-time 20 "http://${SERVER_NAME}/healthz" || echo "healthz not answering yet"
echo
echo "==> Deployed to https://${SERVER_NAME}"
