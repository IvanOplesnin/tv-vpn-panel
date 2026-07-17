from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace


WG_CONFIG = """
[Interface]
Address = 10.10.0.1/24
PrivateKey = secret-server-key

[Peer]
PublicKey = key-no-name
AllowedIPs = 10.10.0.2/32

[Peer]
# work_notebook
PublicKey = key-work
AllowedIPs = 10.10.0.5/32

# Name: polina_notebook
[Peer]
PublicKey = key-polina
AllowedIPs = 10.10.0.6/32
"""


def configure(
    tmp_path,
    monkeypatch,
):
    from tv_vpn_panel import (
        wireguard_names,
        wireguard_registry,
    )

    config_file = tmp_path / "wg0.conf"
    registry_file = (
        tmp_path / "wireguard-clients.json"
    )

    config_file.write_text(
        WG_CONFIG,
        encoding="utf-8",
    )

    cfg = SimpleNamespace(
        wireguard_config_file=config_file,
        wireguard_clients_file=registry_file,
    )

    monkeypatch.setattr(
        wireguard_names,
        "settings",
        cfg,
    )
    monkeypatch.setattr(
        wireguard_registry,
        "settings",
        cfg,
    )

    return (
        wireguard_names,
        wireguard_registry,
        config_file,
        registry_file,
    )


def test_parse_wireguard_names():
    from tv_vpn_panel.wireguard_names import (
        parse_wireguard_config,
    )

    peers = parse_wireguard_config(WG_CONFIG)

    assert [
        (peer.ip, peer.name)
        for peer in peers
    ] == [
        ("10.10.0.2", None),
        ("10.10.0.5", "work_notebook"),
        ("10.10.0.6", "polina_notebook"),
    ]

    # PrivateKey не попадает в модель.
    assert all(
        not hasattr(peer, "private_key")
        for peer in peers
    )


def test_sync_preserves_manual_names_and_modes(
    tmp_path,
    monkeypatch,
):
    (
        wireguard_names,
        wireguard_registry,
        config_file,
        registry_file,
    ) = configure(
        tmp_path,
        monkeypatch,
    )

    registry_file.write_text(
        json.dumps(
            [
                {
                    "public_key": "key-work",
                    "ip": "10.10.0.5",
                    "name": "Manual laptop",
                    "routing_mode": "direct",
                },
                {
                    "public_key": "key-polina",
                    "ip": "10.10.0.6",
                    "routing_mode": "vless",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = (
        wireguard_names
        .sync_wireguard_client_names(
            config_file=config_file,
        )
    )

    assert result.discovered == 3
    assert result.with_names == 2
    assert result.updated == 1
    assert result.preserved == 1
    assert result.skipped_without_name == 1

    profiles = (
        wireguard_registry
        .load_wireguard_profiles()
    )
    profiles_by_ip = {
        profile.ip: profile
        for profile in profiles
    }

    assert (
        profiles_by_ip["10.10.0.5"].name
        == "Manual laptop"
    )
    assert (
        profiles_by_ip["10.10.0.5"].routing_mode
        == "direct"
    )
    assert (
        profiles_by_ip["10.10.0.6"].name
        == "polina_notebook"
    )
    assert (
        profiles_by_ip["10.10.0.6"].routing_mode
        == "vless"
    )


def test_wireguard_template_contains_controls():
    root = Path(__file__).resolve().parents[1]
    template = (
        root
        / "tv_vpn_panel"
        / "templates"
        / "wireguard.html"
    ).read_text(encoding="utf-8")

    assert "WireGuard-клиенты" in template
    assert "sync-names" in template
    assert "routing_mode" in template
    assert "OpenVPN" in template
    assert "VLESS" in template
