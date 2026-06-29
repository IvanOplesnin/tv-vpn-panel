#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${TVVPN_APP_DIR:-/opt/tv-vpn-panel-fastapi}"
SERVICE_NAME="${TVVPN_SERVICE_NAME:-tv-vpn-panel.service}"
SERVICE_DST="/etc/systemd/system/${SERVICE_NAME}"
ENV_FILE="${TVVPN_ENV_FILE:-/etc/default/tv-vpn-panel}"
BRANCH="${TVVPN_BRANCH:-main}"
REPO_URL="${TVVPN_REPO_URL:-${1:-}}"
INSTALL_APT_DEPS="${TVVPN_INSTALL_APT_DEPS:-true}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo TVVPN_REPO_URL=<repo-url> $0" >&2
  exit 1
fi

if [[ -z "${REPO_URL}" ]]; then
  cat >&2 <<'USAGE'
Missing repo URL.

Usage:
  sudo TVVPN_REPO_URL=https://github.com/<user>/<repo>.git ./scripts/install-from-git.sh

Or:
  sudo ./scripts/install-from-git.sh https://github.com/<user>/<repo>.git

Optional env:
  TVVPN_BRANCH=main
  TVVPN_APP_DIR=/opt/tv-vpn-panel-fastapi
  TVVPN_INSTALL_APT_DEPS=false
USAGE
  exit 2
fi

if [[ "${INSTALL_APT_DEPS}" == "true" ]]; then
  apt-get update
  apt-get install -y git python3 python3-venv python3-pip ca-certificates
fi

if [[ -d "${APP_DIR}/.git" ]]; then
  echo "Updating existing git checkout: ${APP_DIR}"
  git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
  git -C "${APP_DIR}" fetch origin "${BRANCH}"
  git -C "${APP_DIR}" checkout "${BRANCH}" || git -C "${APP_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
  git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
else
  if [[ -e "${APP_DIR}" ]]; then
    BACKUP_DIR="${APP_DIR}.backup.$(date +%Y%m%d-%H%M%S)"
    echo "${APP_DIR} exists and is not a git checkout. Moving to ${BACKUP_DIR}"
    mv "${APP_DIR}" "${BACKUP_DIR}"
  fi
  echo "Cloning ${REPO_URL}#${BRANCH} to ${APP_DIR}"
  git clone --branch "${BRANCH}" "${REPO_URL}" "${APP_DIR}"
fi

python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<'ENVEOF'
# Local settings for tv-vpn-panel.service.
# This file is intentionally outside the git checkout and is not overwritten by updates.

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
TVVPN_ALLOW_BACKEND_REFRESH=false
# Set this before exposing API outside trusted LAN:
# TVVPN_API_TOKEN=change-me
ENVEOF
  chmod 0640 "${ENV_FILE}"
fi

cp "${APP_DIR}/deploy/systemd/tv-vpn-panel-fastapi.service" "${SERVICE_DST}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager -l
