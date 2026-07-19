from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def configure(
    monkeypatch,
    *,
    dry_run: bool = False,
):
    from tv_vpn_panel import wireguard_routing

    monkeypatch.setattr(
        wireguard_routing,
        "settings",
        SimpleNamespace(
            dry_run=dry_run,
            table_id="200",
            route_test_ip="8.8.8.8",
            wireguard_routing_script=Path(
                "/missing/routing-script"
            ),
            wireguard_routing_priority_base=31000,
            wireguard_openvpn_table="201",
            wireguard_vless_table="202",
            wireguard_interface="wg-test0",
            wireguard_direct_interface="eth0",
            wireguard_openvpn_interface="tun0",
            wireguard_vless_interface="sbtun0",
        ),
    )

    return wireguard_routing


def test_auto_and_direct_applied(
    monkeypatch,
):
    routing = configure(monkeypatch)

    auto_rules = (
        "0: from all lookup local\n"
        "32765: from 10.10.0.0/24 "
        "lookup 200\n"
    )

    assert routing.routing_mode_is_applied(
        "10.10.0.6",
        "auto",
        True,
        (
            "8.8.8.8 from 10.10.0.6 "
            "via 10.8.0.1 dev tun0 table 200"
        ),
        auto_rules,
    )

    direct_rules = (
        "31006: from 10.10.0.6 lookup main\n"
    )

    assert routing.routing_mode_is_applied(
        "10.10.0.6",
        "direct",
        True,
        (
            "8.8.8.8 from 10.10.0.6 "
            "via 192.168.1.1 dev eth0"
        ),
        direct_rules,
    )


def test_pinned_backends_applied(
    monkeypatch,
):
    routing = configure(monkeypatch)

    assert routing.routing_mode_is_applied(
        "10.10.0.6",
        "openvpn",
        True,
        (
            "8.8.8.8 from 10.10.0.6 "
            "via 10.8.0.1 dev tun0 table 201"
        ),
        (
            "31006: from 10.10.0.6 "
            "lookup 201\n"
        ),
    )

    assert routing.routing_mode_is_applied(
        "10.10.0.6",
        "vless",
        True,
        (
            "8.8.8.8 from 10.10.0.6 "
            "dev sbtun0 table 202"
        ),
        (
            "31006: from 10.10.0.6 "
            "lookup 202\n"
        ),
    )


def test_mismatched_mode_not_applied(
    monkeypatch,
):
    routing = configure(monkeypatch)

    assert not routing.routing_mode_is_applied(
        "10.10.0.6",
        "direct",
        True,
        (
            "8.8.8.8 from 10.10.0.6 "
            "via 10.8.0.1 dev tun0 table 200"
        ),
        "",
    )

    assert not routing.routing_mode_is_applied(
        "10.10.0.6",
        "openvpn",
        True,
        (
            "8.8.8.8 from 10.10.0.6 "
            "dev sbtun0 table 202"
        ),
        (
            "31006: from 10.10.0.6 "
            "lookup 202\n"
        ),
    )


def test_apply_skips_host_in_dry_run(
    monkeypatch,
):
    routing = configure(
        monkeypatch,
        dry_run=True,
    )

    result = (
        routing.apply_wireguard_routing_mode(
            "10.10.0.6",
            "direct",
        )
    )

    assert "dry run" in result


def test_probe_uses_configured_wireguard_interface(
    monkeypatch,
):
    routing = configure(monkeypatch)
    calls: list[list[str]] = []

    def fake_safe_run(cmd, timeout=3.0):
        from subprocess import CompletedProcess

        calls.append(cmd)
        return CompletedProcess(
            cmd,
            0,
            "8.8.8.8 from 10.10.0.6 dev eth0\n",
            "",
        )

    monkeypatch.setattr(
        routing,
        "safe_run",
        fake_safe_run,
    )

    route_ok, route_text = (
        routing.probe_wireguard_route(
            "10.10.0.6",
        )
    )

    assert route_ok is True
    assert "dev eth0" in (route_text or "")
    assert calls == [
        [
            "ip",
            "route",
            "get",
            "8.8.8.8",
            "from",
            "10.10.0.6",
            "iif",
            "wg-test0",
        ]
    ]


def test_replay_wireguard_routing_modes(
    monkeypatch,
):
    routing = configure(monkeypatch)
    calls: list[tuple[str, str]] = []

    from tv_vpn_panel.models import (
        WireGuardClientProfile,
    )

    profiles = [
        WireGuardClientProfile(
            public_key="auto-key",
            ip="10.10.0.5",
            routing_mode="auto",
        ),
        WireGuardClientProfile(
            public_key="openvpn-key",
            ip="10.10.0.6",
            routing_mode="openvpn",
        ),
        WireGuardClientProfile(
            public_key="vless-key",
            ip="10.10.0.7",
            routing_mode="vless",
        ),
    ]

    def fake_apply(
        client_ip: str,
        routing_mode: str,
    ) -> str:
        calls.append((client_ip, routing_mode))

        if routing_mode == "vless":
            raise routing.WireGuardRoutingError(
                "backend unavailable"
            )

        return "applied"

    monkeypatch.setattr(
        routing,
        "load_wireguard_profiles",
        lambda: profiles,
    )
    monkeypatch.setattr(
        routing,
        "apply_wireguard_routing_mode",
        fake_apply,
    )

    result = (
        routing.replay_wireguard_routing_modes()
    )

    assert calls == [
        ("10.10.0.6", "openvpn"),
        ("10.10.0.7", "vless"),
    ]
    assert result.attempted == 2
    assert result.applied == 1
    assert result.errors == [
        "10.10.0.7: backend unavailable"
    ]
