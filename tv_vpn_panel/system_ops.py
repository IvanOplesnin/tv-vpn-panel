from __future__ import annotations

import subprocess
from pathlib import Path

from .config import settings
from .models import BackendState, DeviceRuntimeState


def run_cmd(cmd: list[str], check: bool = False, timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def safe_run(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return run_cmd(cmd, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def rule_priority(ip: str) -> str:
    last_octet = int(ip.split(".")[-1])
    return str(32000 + last_octet)


def disable_vpn_rule(ip: str) -> None:
    # Delete several times in case duplicate rules were created earlier.
    for _ in range(5):
        safe_run(["ip", "rule", "del", "from", f"{ip}/32", "lookup", settings.table_id], timeout=2.0)


def enable_vpn_rule(ip: str) -> None:
    disable_vpn_rule(ip)
    safe_run(
        [
            "ip",
            "rule",
            "add",
            "from",
            f"{ip}/32",
            "lookup",
            settings.table_id,
            "priority",
            rule_priority(ip),
        ],
        timeout=2.0,
    )


def apply_device_rule(ip: str, vpn: bool) -> None:
    if vpn:
        enable_vpn_rule(ip)
    else:
        disable_vpn_rule(ip)


def ip_rule_text() -> str:
    result = safe_run(["ip", "rule"], timeout=3.0)
    if result is None:
        return ""
    return result.stdout


def is_rule_present(ip: str) -> bool:
    text = ip_rule_text()
    return f"from {ip} lookup {settings.table_id}" in text or f"from {ip}/32 lookup {settings.table_id}" in text


def route_table_text() -> str:
    result = safe_run(["ip", "route", "show", "table", settings.table_id], timeout=3.0)
    if result is None:
        return ""
    return result.stdout.strip()


def get_backend_state() -> BackendState:
    table = route_table_text()
    default_route = None
    for line in table.splitlines():
        if line.startswith("default"):
            default_route = line.strip()
            break

    if not default_route:
        return BackendState(
            active="none",
            ok=False,
            table_id=settings.table_id,
            table_has_default=False,
            default_route=None,
        )

    if " dev tun0" in default_route or " via 10.8.0.1" in default_route:
        active = "openvpn"
    elif " dev sbtun0" in default_route:
        active = "sing-box"
    else:
        active = "unknown"

    return BackendState(
        active=active,
        ok=active in {"openvpn", "sing-box"},
        table_id=settings.table_id,
        table_has_default=True,
        default_route=default_route,
    )


def probe_device_route(ip: str) -> DeviceRuntimeState:
    result = safe_run(
        [
            "ip",
            "route",
            "get",
            settings.route_test_ip,
            "from",
            ip,
            "iif",
            settings.ap_interface,
        ],
        timeout=3.0,
    )
    if result is None:
        return DeviceRuntimeState(rule_present=is_rule_present(ip), route_probe_ok=False, route_probe=None)

    route_text = (result.stdout or result.stderr or "").strip()
    return DeviceRuntimeState(
        rule_present=is_rule_present(ip),
        route_probe_ok=result.returncode == 0,
        route_probe=route_text or None,
    )


def refresh_backend_route() -> tuple[bool, str]:
    script: Path = settings.backend_switch_script
    if not settings.allow_backend_refresh:
        return False, "backend refresh is disabled; existing timer/service should switch table 200"
    if not script.exists():
        return False, f"backend switch script not found: {script}"
    result = safe_run([str(script)], timeout=15.0)
    if result is None:
        return False, "failed to run backend switch script"
    output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    return result.returncode == 0, output
