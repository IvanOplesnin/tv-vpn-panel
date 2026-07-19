from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field

from .config import settings
from .models import WireGuardRoutingMode
from .system_ops import safe_run
from .wireguard_registry import load_wireguard_profiles


VALID_MODES = {
    "auto",
    "direct",
    "openvpn",
    "vless",
}


class WireGuardRoutingError(RuntimeError):
    pass


@dataclass(frozen=True)
class WireGuardRoutingReplayResult:
    attempted: int = 0
    applied: int = 0
    errors: list[str] = field(default_factory=list)


def _client_priority(client_ip: str) -> int:
    try:
        address = ipaddress.ip_address(client_ip)
    except ValueError as exc:
        raise ValueError(
            "invalid WireGuard client IP"
        ) from exc

    if address.version != 4:
        raise ValueError(
            "WireGuard client must use IPv4"
        )

    last_octet = int(str(address).split(".")[-1])

    return (
        settings.wireguard_routing_priority_base
        + last_octet
    )


def _managed_lookup(
    client_ip: str,
    rule_text: str,
) -> str | None:
    try:
        priority = _client_priority(client_ip)
    except ValueError:
        return None

    expected_sources = {
        client_ip,
        f"{client_ip}/32",
    }

    for raw_line in rule_text.splitlines():
        parts = raw_line.split()

        if not parts:
            continue

        if parts[0] != f"{priority}:":
            continue

        try:
            source_index = parts.index("from")
            lookup_index = parts.index("lookup")
        except ValueError:
            continue

        if (
            source_index + 1 >= len(parts)
            or lookup_index + 1 >= len(parts)
        ):
            continue

        if parts[source_index + 1] not in expected_sources:
            continue

        return parts[lookup_index + 1]

    return None


def get_wireguard_rule_text() -> str:
    result = safe_run(
        ["ip", "-4", "rule", "show"],
        timeout=3.0,
    )

    if result is None or result.returncode != 0:
        return ""

    return result.stdout


def probe_wireguard_route(
    client_ip: str,
) -> tuple[bool, str | None]:
    result = safe_run(
        [
            "ip",
            "route",
            "get",
            settings.route_test_ip,
            "from",
            client_ip,
            "iif",
            settings.wireguard_interface,
        ],
        timeout=3.0,
    )

    if result is None:
        return False, None

    output = (
        result.stdout
        or result.stderr
        or ""
    ).strip()

    return (
        result.returncode == 0,
        output or None,
    )


def routing_mode_is_applied(
    client_ip: str | None,
    routing_mode: WireGuardRoutingMode,
    route_ok: bool,
    route_text: str | None,
    rule_text: str,
) -> bool:
    if (
        not client_ip
        or not route_ok
        or not route_text
    ):
        return False

    lookup = _managed_lookup(
        client_ip,
        rule_text,
    )

    if routing_mode == "auto":
        return (
            lookup is None
            and (
                f"table {settings.table_id}"
                in route_text
            )
        )

    if routing_mode == "direct":
        return (
            lookup == "main"
            and (
                f" dev "
                f"{settings.wireguard_direct_interface}"
                in route_text
            )
        )

    if routing_mode == "openvpn":
        table = settings.wireguard_openvpn_table

        return (
            lookup == table
            and f"table {table}" in route_text
            and (
                f" dev "
                f"{settings.wireguard_openvpn_interface}"
                in route_text
            )
        )

    if routing_mode == "vless":
        table = settings.wireguard_vless_table

        return (
            lookup == table
            and f"table {table}" in route_text
            and (
                f" dev "
                f"{settings.wireguard_vless_interface}"
                in route_text
            )
        )

    return False


def apply_wireguard_routing_mode(
    client_ip: str,
    routing_mode: WireGuardRoutingMode,
) -> str:
    if routing_mode not in VALID_MODES:
        raise WireGuardRoutingError(
            f"invalid routing mode: {routing_mode}"
        )

    try:
        _client_priority(client_ip)
    except ValueError as exc:
        raise WireGuardRoutingError(
            str(exc)
        ) from exc

    if settings.dry_run:
        return (
            "dry run: WireGuard routing change "
            f"skipped for {client_ip}"
        )

    script = settings.wireguard_routing_script

    if not script.is_file():
        raise WireGuardRoutingError(
            "WireGuard routing script not found: "
            f"{script}"
        )

    if not os.access(script, os.X_OK):
        raise WireGuardRoutingError(
            "WireGuard routing script is not "
            f"executable: {script}"
        )

    result = safe_run(
        [
            str(script),
            "set",
            client_ip,
            routing_mode,
        ],
        timeout=20.0,
    )

    if result is None:
        raise WireGuardRoutingError(
            "failed to execute WireGuard "
            "routing script"
        )

    output = "\n".join(
        part
        for part in (
            (result.stdout or "").strip(),
            (result.stderr or "").strip(),
        )
        if part
    )

    if result.returncode != 0:
        raise WireGuardRoutingError(
            output
            or (
                "WireGuard routing script "
                "returned an error"
            )
        )

    route_ok, route_text = (
        probe_wireguard_route(client_ip)
    )
    rule_text = get_wireguard_rule_text()

    if not routing_mode_is_applied(
        client_ip,
        routing_mode,
        route_ok,
        route_text,
        rule_text,
    ):
        raise WireGuardRoutingError(
            "routing mode was not verified: "
            f"client={client_ip}, "
            f"mode={routing_mode}, "
            f"route={route_text or '-'}"
        )

    return output or (
        f"{client_ip}: routing mode "
        f"{routing_mode} applied"
    )


def replay_wireguard_routing_modes() -> WireGuardRoutingReplayResult:
    attempted = 0
    applied = 0
    errors: list[str] = []

    for profile in load_wireguard_profiles():
        if profile.routing_mode == "auto":
            continue

        attempted += 1

        try:
            apply_wireguard_routing_mode(
                profile.ip,
                profile.routing_mode,
            )
        except WireGuardRoutingError as exc:
            errors.append(f"{profile.ip}: {exc}")
            continue

        applied += 1

    return WireGuardRoutingReplayResult(
        attempted=attempted,
        applied=applied,
        errors=errors,
    )
