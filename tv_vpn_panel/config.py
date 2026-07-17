from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_host: str = os.getenv("TVVPN_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("TVVPN_PORT", "8090"))

    # Existing project defaults.
    table_id: str = os.getenv("TVVPN_TABLE_ID", "200")
    ap_interface: str = os.getenv("TVVPN_AP_INTERFACE", "enx00e04c2a7a88")
    route_test_ip: str = os.getenv("TVVPN_ROUTE_TEST_IP", "8.8.8.8")

    devices_file: Path = Path(os.getenv("TVVPN_DEVICES_FILE", "/opt/tv-vpn-panel/devices.json"))
    remotes_file: Path = Path(os.getenv("TVVPN_REMOTES_FILE", "/opt/tv-vpn-panel/remotes.json"))
    leases_file: Path = Path(os.getenv("TVVPN_LEASES_FILE", "/var/lib/misc/dnsmasq.leases"))
    wireguard_clients_file: Path = Path(
        os.getenv(
            "TVVPN_WIREGUARD_CLIENTS_FILE",
            "/opt/tv-vpn-panel/wireguard-clients.json",
        )
    )
    backend_switch_script: Path = Path(
        os.getenv("TVVPN_BACKEND_SWITCH_SCRIPT", "/usr/local/sbin/vpn-backend-switch.sh")
    )

    # Empty token means local/trusted LAN mode. Set a token before exposing outside the TV LAN.
    api_token: str = os.getenv("TVVPN_API_TOKEN", "")

    # Periodic sync/broadcast loop. Useful for ESP32 LED state.
    poll_interval_seconds: float = float(os.getenv("TVVPN_POLL_INTERVAL", "10"))
    enable_periodic_sync: bool = _bool_env("TVVPN_ENABLE_PERIODIC_SYNC", True)

    # Local development/testing mode. When enabled, commands that mutate host
    # network state are skipped, while read-only route probes still run.
    dry_run: bool = _bool_env("TVVPN_DRY_RUN", False)

    # Running the backend switch script from the API is optional; the existing timer may do it already.
    allow_backend_refresh: bool = _bool_env("TVVPN_ALLOW_BACKEND_REFRESH", False)


settings = Settings()
