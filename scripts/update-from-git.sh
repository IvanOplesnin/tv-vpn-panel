#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${TVVPN_APP_DIR:-/opt/tv-vpn-panel-fastapi}"
SERVICE_NAME="${TVVPN_SERVICE_NAME:-tv-vpn-panel.service}"
BRANCH="${TVVPN_BRANCH:-main}"
REPO_URL="${TVVPN_REPO_URL:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

if [[ ! -d "${APP_DIR}/.git" ]]; then
  if [[ -z "${REPO_URL}" ]]; then
    echo "${APP_DIR} is not a git checkout. Run install-from-git.sh with TVVPN_REPO_URL first." >&2
    exit 2
  fi
  exec "$(dirname "$0")/install-from-git.sh" "${REPO_URL}"
fi

if [[ -n "${REPO_URL}" ]]; then
  git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
fi

git -C "${APP_DIR}" fetch origin "${BRANCH}"
git -C "${APP_DIR}" checkout "${BRANCH}" || git -C "${APP_DIR}" checkout -B "${BRANCH}" "origin/${BRANCH}"
git -C "${APP_DIR}" reset --hard "origin/${BRANCH}"
rm -rf "${APP_DIR}/.idea"

"${APP_DIR}/.venv/bin/pip" install --upgrade pip || python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

cp "${APP_DIR}/deploy/systemd/tv-vpn-panel-fastapi.service" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl restart "${SERVICE_NAME}"
systemctl status "${SERVICE_NAME}" --no-pager -l
