#!/usr/bin/env bash
set -Eeuo pipefail

umask 022

MODE="prepare"
APP_PATH="${TVVPN_APP_PATH:-/opt/tv-vpn-panel-fastapi}"
RELEASES_DIR="${TVVPN_RELEASES_DIR:-/opt/tv-vpn-panel-releases}"
BACKUPS_DIR="${TVVPN_BACKUPS_DIR:-/opt/tv-vpn-panel-backups}"
SERVICE_NAME="${TVVPN_SERVICE_NAME:-tv-vpn-panel.service}"
ENV_FILE="${TVVPN_ENV_FILE:-/etc/default/tv-vpn-panel}"

REPO_URL="${TVVPN_REPO_URL:-https://github.com/IvanOplesnin/tv-vpn-panel.git}"
BRANCH="${TVVPN_BRANCH:-main}"

TEST_HOST="${TVVPN_TEST_HOST:-127.0.0.1}"
TEST_PORT="${TVVPN_TEST_PORT:-8091}"
PRODUCTION_BASE_URL="${TVVPN_PRODUCTION_BASE_URL:-http://127.0.0.1:8090}"

EXPECTED_WG_TABLE="${TVVPN_EXPECT_WG_TABLE:-200}"
WG_CLIENT_IP="${TVVPN_SAFE_WG_CLIENT:-}"

LOCK_FILE="${TVVPN_UPDATE_LOCK:-/run/lock/tv-vpn-panel-update.lock}"

STAMP="$(date +%Y%m%d-%H%M%S)"
BUILD_DIR=""
FINAL_RELEASE=""
BACKUP_DIR=""
OLD_TARGET=""
LEGACY_TARGET=""
OLD_PATH_WAS_SYMLINK=0
SWITCH_COMPLETED=0
SMOKE_PID=""

log() {
    printf '[safe-update] %s\n' "$*"
}

die() {
    printf '[safe-update] ERROR: %s\n' "$*" >&2
    return 1
}

usage() {
    cat <<'USAGE'
Usage:
  sudo ./scripts/update-safe.sh --prepare-only
  sudo TVVPN_SAFE_WG_CLIENT=10.10.0.5 ./scripts/update-safe.sh --activate

Modes:
  --prepare-only  Clone, install, test and smoke-test a release.
                  Does not modify the production service.

  --activate      Prepare the release, switch production to it,
                  run health checks and automatically roll back on failure.

Environment:
  TVVPN_BRANCH             Git branch to deploy, default: main
  TVVPN_REPO_URL           Repository URL
  TVVPN_SAFE_WG_CLIENT     Current WireGuard client IP for route verification
  TVVPN_EXPECT_WG_TABLE    Expected routing table, default: 200
USAGE
}

for argument in "$@"; do
    case "$argument" in
        --prepare-only)
            MODE="prepare"
            ;;
        --activate)
            MODE="activate"
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
done

require_commands() {
    local command_name

    for command_name in \
        curl \
        flock \
        git \
        ip \
        python3 \
        ss \
        systemctl
    do
        command -v "$command_name" >/dev/null 2>&1 ||
            die "Required command not found: $command_name"
    done
}

detect_wireguard_client() {
    if [[ -n "$WG_CLIENT_IP" ]]; then
        return
    fi

    if [[ -n "${SSH_CONNECTION:-}" ]]; then
        WG_CLIENT_IP="${SSH_CONNECTION%% *}"
    fi

    if [[ ! "$WG_CLIENT_IP" =~ ^10\.10\.0\.[0-9]+$ ]]; then
        WG_CLIENT_IP=""
    fi
}

wireguard_route() {
    if [[ -z "$WG_CLIENT_IP" ]]; then
        return 0
    fi

    ip route get \
        1.1.1.1 \
        from "$WG_CLIENT_IP" \
        iif wg0
}

verify_wireguard_route() {
    local route_text

    if [[ -z "$WG_CLIENT_IP" ]]; then
        log "WireGuard client was not detected; route verification skipped"
        return 0
    fi

    route_text="$(wireguard_route)"

    printf '%s\n' "$route_text"

    grep -q "table ${EXPECTED_WG_TABLE}" <<<"$route_text" ||
        die "WireGuard client ${WG_CLIENT_IP} is not using table ${EXPECTED_WG_TABLE}"

    ip -4 rule show |
        grep -Eq \
            "from 10\.10\.0\.0/24 lookup ${EXPECTED_WG_TABLE}" ||
        die "The general WireGuard rule for table ${EXPECTED_WG_TABLE} is missing"
}

stop_smoke_server() {
    if [[ -n "$SMOKE_PID" ]]; then
        kill "$SMOKE_PID" 2>/dev/null || true
        wait "$SMOKE_PID" 2>/dev/null || true
        SMOKE_PID=""
    fi
}

restore_previous_release() {
    trap - ERR INT TERM
    set +e

    stop_smoke_server

    if [[ "$SWITCH_COMPLETED" -eq 1 ]]; then
        log "Restoring the previous production release"

        rm -f "${APP_PATH}.new"

        if [[ "$OLD_PATH_WAS_SYMLINK" -eq 1 ]]; then
            rm -f "${APP_PATH}.rollback"
            ln -s "$OLD_TARGET" "${APP_PATH}.rollback"
            mv -Tf "${APP_PATH}.rollback" "$APP_PATH"
        else
            rm -f "$APP_PATH"

            if [[ -d "$LEGACY_TARGET" ]]; then
                mv "$LEGACY_TARGET" "$APP_PATH"
            fi
        fi

        systemctl restart "$SERVICE_NAME"
        sleep 2

        systemctl status "$SERVICE_NAME" --no-pager -l || true
    fi

    if [[ -n "$BUILD_DIR" && -d "$BUILD_DIR" ]]; then
        rm -rf "$BUILD_DIR"
    fi
}

on_error() {
    local exit_code=$?

    log "Update failed with exit code ${exit_code}"
    restore_previous_release

    if [[ -n "$BACKUP_DIR" ]]; then
        log "Diagnostic backup: $BACKUP_DIR"
    fi

    exit "$exit_code"
}

trap on_error ERR INT TERM

load_api_token() {
    TVVPN_API_TOKEN=""

    if [[ -f "$ENV_FILE" ]]; then
        set +u
        set -a
        # shellcheck disable=SC1090
        source "$ENV_FILE"
        set +a
        set -u
    fi

    API_TOKEN="${TVVPN_API_TOKEN:-}"
}

production_curl() {
    local path="$1"

    if [[ -n "${API_TOKEN:-}" ]]; then
        curl \
            --fail \
            --silent \
            --show-error \
            --max-time 5 \
            -H "X-API-Token: ${API_TOKEN}" \
            "${PRODUCTION_BASE_URL}${path}"
    else
        curl \
            --fail \
            --silent \
            --show-error \
            --max-time 5 \
            "${PRODUCTION_BASE_URL}${path}"
    fi
}

wait_for_production() {
    local attempt

    for attempt in $(seq 1 20); do
        if systemctl is-active --quiet "$SERVICE_NAME" &&
            production_curl "/api/health" >/dev/null 2>&1
        then
            return 0
        fi

        sleep 1
    done

    journalctl -u "$SERVICE_NAME" -n 60 --no-pager || true
    die "Production health check failed"
}

validate_wireguard_json() {
    local json_file="$1"
    local expected_client="${2:-}"

    python3 - "$json_file" "$expected_client" "$EXPECTED_WG_TABLE" <<'PY'
import json
import sys
from pathlib import Path

json_file = Path(sys.argv[1])
expected_client = sys.argv[2]
expected_table = sys.argv[3]

payload = json.loads(json_file.read_text(encoding="utf-8"))

assert payload["ok"] is True, payload
assert payload["interface"] == "wg0", payload
assert isinstance(payload["peers"], list), payload
assert payload["peers"], payload

if expected_client:
    peer = next(
        item
        for item in payload["peers"]
        if item["ip"] == expected_client
    )

    assert peer["route_probe_ok"] is True, peer
    assert f"table {expected_table}" in (peer["route_probe"] or ""), peer

print(
    f"WireGuard API valid: "
    f"{len(payload['peers'])} peer(s)"
)
PY
}

wait_for_production_wireguard() {
    local json_file="$1"
    local route_file="$2"
    local expected_client="${3:-}"
    local attempt
    local max_attempts=15
    local temporary_json="${json_file}.tmp"
    local validation_output="${json_file}.validation"
    local validation_error="${json_file}.validation-error"
    local route_output="${route_file}.tmp"
    local route_error="${route_file}.error"

    rm -f \
        "$temporary_json" \
        "$validation_output" \
        "$validation_error" \
        "$route_output" \
        "$route_error"

    for attempt in $(seq 1 "$max_attempts"); do
        if production_curl "/api/wireguard/clients" \
                >"$temporary_json" 2>"${json_file}.curl-error" &&
            validate_wireguard_json \
                "$temporary_json" \
                "$expected_client" \
                >"$validation_output" 2>"$validation_error" &&
            verify_wireguard_route \
                >"$route_output" 2>"$route_error"
        then
            mv "$temporary_json" "$json_file"
            mv "$route_output" "$route_file"

            cat "$validation_output"
            cat "$route_file"

            rm -f \
                "$validation_output" \
                "$validation_error" \
                "$route_error" \
                "${json_file}.curl-error"

            return 0
        fi

        log "WireGuard route validation attempt ${attempt}/${max_attempts} did not pass"

        if [[ "$attempt" -lt "$max_attempts" ]]; then
            sleep 1
        fi
    done

    log "Last WireGuard API response:"

    if [[ -s "$temporary_json" ]]; then
        cat "$temporary_json" >&2
    fi

    if [[ -s "$validation_error" ]]; then
        cat "$validation_error" >&2
    fi

    if [[ -s "$route_error" ]]; then
        cat "$route_error" >&2
    fi

    die "Production WireGuard route did not stabilize"
}


prepare_release() {
    local new_head
    local runtime_dir
    local smoke_log
    local smoke_json
    local attempt
    local smoke_ready=0

    mkdir -p "$RELEASES_DIR"
    mkdir -p "$BACKUPS_DIR"

    BUILD_DIR="${RELEASES_DIR}/.build-${STAMP}-$$"

    log "Cloning ${REPO_URL} branch ${BRANCH}"

    git clone \
        --branch "$BRANCH" \
        --single-branch \
        "$REPO_URL" \
        "$BUILD_DIR"

    new_head="$(git -C "$BUILD_DIR" rev-parse HEAD)"
    FINAL_RELEASE="${RELEASES_DIR}/${new_head:0:12}-${STAMP}"

    log "Candidate commit: $new_head"

    [[ ! -e "$FINAL_RELEASE" ]] ||
        die "Release path already exists: $FINAL_RELEASE"

    # Move the source tree to its permanent path before creating the venv.
    # Console scripts inside a venv contain absolute interpreter paths.
    mv "$BUILD_DIR" "$FINAL_RELEASE"
    BUILD_DIR="$FINAL_RELEASE"

    log "Creating candidate virtual environment"

    python3 -m venv "${BUILD_DIR}/.venv"

    "${BUILD_DIR}/.venv/bin/python" -m pip install \
        -r "${BUILD_DIR}/requirements.txt"

    if [[ -f "${BUILD_DIR}/requirements-dev.txt" ]]; then
        "${BUILD_DIR}/.venv/bin/python" -m pip install \
            -r "${BUILD_DIR}/requirements-dev.txt"
    else
        "${BUILD_DIR}/.venv/bin/python" -m pip install \
            pytest \
            httpx
    fi

    runtime_dir="${BUILD_DIR}/.runtime-smoke"
    mkdir -p "$runtime_dir"

    printf '[]\n' > "${runtime_dir}/devices.json"
    printf '[]\n' > "${runtime_dir}/remotes.json"
    printf '[]\n' > "${runtime_dir}/wireguard-clients.json"
    : > "${runtime_dir}/dnsmasq.leases"

    log "Running unit tests in dry-run mode"

    env \
        PYTHONPATH="$BUILD_DIR" \
        TVVPN_DRY_RUN=true \
        TVVPN_ENABLE_PERIODIC_SYNC=false \
        TVVPN_DEVICES_FILE="${runtime_dir}/devices.json" \
        TVVPN_REMOTES_FILE="${runtime_dir}/remotes.json" \
        TVVPN_WIREGUARD_CLIENTS_FILE="${runtime_dir}/wireguard-clients.json" \
        TVVPN_LEASES_FILE="${runtime_dir}/dnsmasq.leases" \
        "${BUILD_DIR}/.venv/bin/python" \
        -m pytest \
        -q \
        "${BUILD_DIR}/tests"

    if ss -ltn |
        grep -Eq ":${TEST_PORT}[[:space:]]"
    then
        die "Smoke-test port ${TEST_PORT} is already in use"
    fi

    smoke_log="${runtime_dir}/uvicorn.log"
    smoke_json="${runtime_dir}/wireguard.json"

    log "Starting isolated smoke-test server on ${TEST_HOST}:${TEST_PORT}"

    env \
        PYTHONPATH="$BUILD_DIR" \
        TVVPN_DRY_RUN=true \
        TVVPN_ENABLE_PERIODIC_SYNC=false \
        TVVPN_API_TOKEN="" \
        TVVPN_HOST="$TEST_HOST" \
        TVVPN_PORT="$TEST_PORT" \
        TVVPN_DEVICES_FILE="${runtime_dir}/devices.json" \
        TVVPN_REMOTES_FILE="${runtime_dir}/remotes.json" \
        TVVPN_WIREGUARD_CLIENTS_FILE="${runtime_dir}/wireguard-clients.json" \
        TVVPN_LEASES_FILE="${runtime_dir}/dnsmasq.leases" \
        "${BUILD_DIR}/.venv/bin/uvicorn" \
            tv_vpn_panel.main:app \
            --host "$TEST_HOST" \
            --port "$TEST_PORT" \
        >"$smoke_log" 2>&1 &

    SMOKE_PID=$!

    for attempt in $(seq 1 20); do
        if curl \
            --fail \
            --silent \
            --max-time 2 \
            "http://${TEST_HOST}:${TEST_PORT}/api/health" \
            >/dev/null 2>&1
        then
            smoke_ready=1
            break
        fi

        if ! kill -0 "$SMOKE_PID" 2>/dev/null; then
            cat "$smoke_log" >&2
            die "Smoke-test server stopped unexpectedly"
        fi

        sleep 1
    done

    [[ "$smoke_ready" -eq 1 ]] ||
        die "Smoke-test server did not become ready"

    curl \
        --fail \
        --silent \
        --show-error \
        --max-time 10 \
        "http://${TEST_HOST}:${TEST_PORT}/api/wireguard/clients" \
        >"$smoke_json"

    validate_wireguard_json "$smoke_json" "$WG_CLIENT_IP"

    stop_smoke_server

    rm -rf "$runtime_dir"

    printf '%s\n' \
        "commit=${new_head}" \
        "branch=${BRANCH}" \
        "prepared_at=${STAMP}" \
        >"${BUILD_DIR}/RELEASE_INFO"

    # The release is already located at FINAL_RELEASE.
    # Clearing BUILD_DIR prevents cleanup after successful preparation.
    BUILD_DIR=""

    log "Prepared release: $FINAL_RELEASE"
}

backup_production_state() {
    BACKUP_DIR="${BACKUPS_DIR}/${STAMP}"
    mkdir -p "$BACKUP_DIR"

    systemctl cat "$SERVICE_NAME" \
        >"${BACKUP_DIR}/service.txt"

    if [[ -f "/etc/systemd/system/${SERVICE_NAME}" ]]; then
        cp -a \
            "/etc/systemd/system/${SERVICE_NAME}" \
            "${BACKUP_DIR}/"
    fi

    if [[ -f "$ENV_FILE" ]]; then
        cp -a "$ENV_FILE" "$BACKUP_DIR/"
    fi

    ip -4 rule show \
        >"${BACKUP_DIR}/ip-rule-before.txt"

    ip -4 route show table "$EXPECTED_WG_TABLE" \
        >"${BACKUP_DIR}/table-${EXPECTED_WG_TABLE}-before.txt"

    if [[ -n "$WG_CLIENT_IP" ]]; then
        wireguard_route \
            >"${BACKUP_DIR}/wg-route-before.txt"
    fi

    log "Production state backup: $BACKUP_DIR"
}

switch_release() {
    if [[ -L "$APP_PATH" ]]; then
        OLD_PATH_WAS_SYMLINK=1
        OLD_TARGET="$(readlink -f "$APP_PATH")"

        [[ -d "$OLD_TARGET" ]] ||
            die "Current release target does not exist: $OLD_TARGET"

        rm -f "${APP_PATH}.new"
        ln -s "$FINAL_RELEASE" "${APP_PATH}.new"
        mv -Tf "${APP_PATH}.new" "$APP_PATH"
    elif [[ -d "$APP_PATH" ]]; then
        OLD_PATH_WAS_SYMLINK=0

        local old_head="legacy"

        if git -C "$APP_PATH" rev-parse HEAD >/dev/null 2>&1; then
            old_head="$(
                git -C "$APP_PATH" rev-parse --short=12 HEAD
            )"
        fi

        LEGACY_TARGET="${RELEASES_DIR}/${old_head}-legacy-${STAMP}"

        log "Moving legacy installation to $LEGACY_TARGET"

        # Prepare the new symlink before moving the working installation.
        # If the final atomic rename fails, SWITCH_COMPLETED is already set
        # and the error trap restores LEGACY_TARGET back to APP_PATH.
        rm -f "${APP_PATH}.new"
        ln -s "$FINAL_RELEASE" "${APP_PATH}.new"

        mv "$APP_PATH" "$LEGACY_TARGET"
        SWITCH_COMPLETED=1

        mv -Tf "${APP_PATH}.new" "$APP_PATH"
    else
        die "Production application path not found: $APP_PATH"
    fi

    SWITCH_COMPLETED=1
}

activate_release() {
    local production_json

    log "Verifying current WireGuard route"
    verify_wireguard_route

    systemctl is-active --quiet "$SERVICE_NAME" ||
        die "Production service is not active before update"

    backup_production_state
    load_api_token
    switch_release

    log "Restarting only ${SERVICE_NAME}"

    systemctl restart "$SERVICE_NAME"
    wait_for_production

    production_json="${BACKUP_DIR}/wireguard-production.json"

    log "Waiting for production WireGuard route to stabilize"

    wait_for_production_wireguard \
        "$production_json" \
        "${BACKUP_DIR}/wg-route-after.txt" \
        "$WG_CLIENT_IP"

    ip -4 rule show |
        tee "${BACKUP_DIR}/ip-rule-after.txt"

    systemctl status "$SERVICE_NAME" \
        --no-pager \
        -l |
        sed -n '1,20p'

    log "Activation completed successfully"
    log "Active release: $FINAL_RELEASE"

    if [[ "$OLD_PATH_WAS_SYMLINK" -eq 1 ]]; then
        log "Previous release: $OLD_TARGET"
    else
        log "Legacy installation preserved at: $LEGACY_TARGET"
    fi
}

main() {
    [[ "$EUID" -eq 0 ]] ||
        die "Run this script with sudo"

    require_commands
    detect_wireguard_client

    exec 9>"$LOCK_FILE"
    flock -n 9 ||
        die "Another update process is already running"

    if [[ -n "$WG_CLIENT_IP" ]]; then
        log "Protected WireGuard client: $WG_CLIENT_IP"
    fi

    prepare_release

    if [[ "$MODE" == "prepare" ]]; then
        log "Prepare-only mode: production was not changed"
        trap - ERR INT TERM
        exit 0
    fi

    activate_release

    trap - ERR INT TERM
}

main "$@"
