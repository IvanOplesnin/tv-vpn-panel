#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${TVVPN_APP_DIR:-/opt/tv-vpn-panel-fastapi}"
SERVICE_NAME="${TVVPN_SERVICE_NAME:-tv-vpn-panel.service}"
SERVICE_SRC="${APP_DIR}/deploy/systemd/tv-vpn-panel-fastapi.service"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}"
ENV_FILE="${TVVPN_ENV_FILE:-/etc/default/tv-vpn-panel}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

mkdir -p "${APP_DIR}"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.idea/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  ./ "${APP_DIR}/"
rm -rf "${APP_DIR}/.idea"

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'ENVEOF'
TVVPN_DEVICES_FILE=/opt/tv-vpn-panel/devices.json
TVVPN_REMOTES_FILE=/opt/tv-vpn-panel/remotes.json
TVVPN_LEASES_FILE=/var/lib/misc/dnsmasq.leases
TVVPN_TABLE_ID=200
TVVPN_AP_INTERFACE=enx00e04c2a7a88
TVVPN_ROUTE_TEST_IP=8.8.8.8
TVVPN_HOST=0.0.0.0
TVVPN_PORT=8090
TVVPN_POLL_INTERVAL=10
TVVPN_ENABLE_PERIODIC_SYNC=true
TVVPN_DRY_RUN=false
TVVPN_ALLOW_BACKEND_REFRESH=false
# TVVPN_API_TOKEN=change-me
ENVEOF
  chmod 0640 "${ENV_FILE}"
fi

cp "${SERVICE_SRC}" "${SERVICE_DST}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager -l
