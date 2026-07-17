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
