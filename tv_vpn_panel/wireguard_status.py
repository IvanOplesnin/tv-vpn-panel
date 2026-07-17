from __future__ import annotations

import ipaddress
import time
from datetime import UTC, datetime

from .config import settings
from .models import WireGuardPeerState, WireGuardStatusResponse
from .system_ops import safe_run
from .wireguard_registry import load_wireguard_profiles
from .wireguard_routing import (
    get_wireguard_rule_text,
    routing_mode_is_applied,
)


WG_INTERFACE = "wg0"
ONLINE_THRESHOLD_SECONDS = 180


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _to_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _short_key(public_key: str) -> str:
    if len(public_key) <= 20:
        return public_key
    return f"{public_key[:12]}...{public_key[-6:]}"


def _first_ipv4(allowed_ips: list[str]) -> str | None:
    for value in allowed_ips:
        try:
            interface = ipaddress.ip_interface(value)
        except ValueError:
            continue

        if interface.version == 4:
            return str(interface.ip)

    return None


def _route_test_target() -> str:
    try:
        ipaddress.ip_address(settings.route_test_ip)
    except ValueError:
        return "1.1.1.1"

    return settings.route_test_ip


def _probe_route(ip: str | None) -> tuple[bool, str | None]:
    if not ip:
        return False, None

    result = safe_run(
        [
            "ip",
            "route",
            "get",
            _route_test_target(),
            "from",
            ip,
            "iif",
            WG_INTERFACE,
        ],
        timeout=3.0,
    )

    if result is None:
        return False, None

    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output or None


def _peer_sort_key(peer: WireGuardPeerState) -> tuple[int, str]:
    if not peer.ip:
        return 2**32, peer.public_key

    try:
        return int(ipaddress.ip_address(peer.ip)), peer.public_key
    except ValueError:
        return 2**32, peer.public_key


def get_wireguard_status() -> WireGuardStatusResponse:
    generated_at = _utc_now()

    result = safe_run(
        ["wg", "show", WG_INTERFACE, "dump"],
        timeout=5.0,
    )

    if result is None:
        return WireGuardStatusResponse(
            ok=False,
            interface=WG_INTERFACE,
            generated_at=generated_at,
            online_threshold_seconds=ONLINE_THRESHOLD_SECONDS,
            error="failed to execute wg command",
        )

    if result.returncode != 0:
        error = (result.stderr or result.stdout or "").strip()

        return WireGuardStatusResponse(
            ok=False,
            interface=WG_INTERFACE,
            generated_at=generated_at,
            online_threshold_seconds=ONLINE_THRESHOLD_SECONDS,
            error=error or "wg command returned an error",
        )

    lines = result.stdout.splitlines()

    if not lines:
        return WireGuardStatusResponse(
            ok=False,
            interface=WG_INTERFACE,
            generated_at=generated_at,
            online_threshold_seconds=ONLINE_THRESHOLD_SECONDS,
            error="wg dump returned no data",
        )

    now_unix = int(time.time())
    peers: list[WireGuardPeerState] = []

    profiles = load_wireguard_profiles()
    profiles_by_key = {
        profile.public_key: profile
        for profile in profiles
    }
    profiles_by_ip = {
        profile.ip: profile
        for profile in profiles
    }
    rule_text = get_wireguard_rule_text()

    # Первая строка описывает интерфейс wg0.
    for line in lines[1:]:
        columns = line.split("\t")

        if len(columns) < 8:
            continue

        (
            public_key,
            _preshared_key,
            endpoint_raw,
            allowed_ips_raw,
            handshake_raw,
            rx_raw,
            tx_raw,
            keepalive_raw,
        ) = columns[:8]

        allowed_ips = [
            value.strip()
            for value in allowed_ips_raw.split(",")
            if value.strip() and value.strip() != "(none)"
        ]

        client_ip = _first_ipv4(allowed_ips)
        latest_handshake = _to_int(handshake_raw)

        if latest_handshake <= 0:
            status = "never"
            handshake_age = None
            handshake_at = None
        else:
            handshake_age = max(0, now_unix - latest_handshake)
            handshake_at = datetime.fromtimestamp(
                latest_handshake,
                tz=UTC,
            ).isoformat()

            status = (
                "online"
                if handshake_age <= ONLINE_THRESHOLD_SECONDS
                else "idle"
            )

        profile = profiles_by_key.get(public_key)

        if profile is None and client_ip:
            profile = profiles_by_ip.get(client_ip)

        if profile is None or not profile.name:
            display_name = (
                f"WireGuard {client_ip}"
                if client_ip
                else _short_key(public_key)
            )
            name_is_default = True
        else:
            display_name = profile.name
            name_is_default = False

        routing_mode = (
            profile.routing_mode
            if profile is not None
            else "auto"
        )

        route_ok, route_text = _probe_route(client_ip)

        peers.append(
            WireGuardPeerState(
                public_key=public_key,
                public_key_short=_short_key(public_key),
                name=display_name,
                name_is_default=name_is_default,
                routing_mode=routing_mode,
                routing_mode_applied=(
                    routing_mode_is_applied(
                        client_ip,
                        routing_mode,
                        route_ok,
                        route_text,
                        rule_text,
                    )
                ),
                endpoint=(
                    None
                    if endpoint_raw in {"", "(none)"}
                    else endpoint_raw
                ),
                allowed_ips=allowed_ips,
                ip=client_ip,
                status=status,
                latest_handshake_unix=latest_handshake,
                latest_handshake_at=handshake_at,
                latest_handshake_age_seconds=handshake_age,
                transfer_rx_bytes=_to_int(rx_raw),
                transfer_tx_bytes=_to_int(tx_raw),
                persistent_keepalive_seconds=_to_int(keepalive_raw),
                route_probe_ok=route_ok,
                route_probe=route_text,
            )
        )

    peers.sort(key=_peer_sort_key)

    return WireGuardStatusResponse(
        ok=True,
        interface=WG_INTERFACE,
        generated_at=generated_at,
        online_threshold_seconds=ONLINE_THRESHOLD_SECONDS,
        peers=peers,
    )
