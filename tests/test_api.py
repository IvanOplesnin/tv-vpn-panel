from __future__ import annotations

from types import SimpleNamespace


def test_device_api_smoke(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from tv_vpn_panel import main, store
    from tv_vpn_panel.models import BackendState, VpnInterfaceState

    cfg = SimpleNamespace(
        devices_file=tmp_path / "devices.json",
        remotes_file=tmp_path / "remotes.json",
        leases_file=tmp_path / "dnsmasq.leases",
        table_id="200",
    )
    monkeypatch.setattr(store, "settings", cfg)
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            devices_file=cfg.devices_file,
            remotes_file=cfg.remotes_file,
            leases_file=cfg.leases_file,
            wireguard_config_file=tmp_path / "wg-test0.conf",
            wireguard_interface="wg-test0",
            backend_switch_script=tmp_path / "vpn-backend-switch.sh",
            table_id="200",
            ap_interface="wlan0",
            route_test_ip="8.8.8.8",
            dry_run=True,
            allow_backend_refresh=False,
            api_token="",
        ),
    )
    monkeypatch.setattr(store, "disable_vpn_rule", lambda ip: None)
    monkeypatch.setattr(store, "apply_device_rule", lambda ip, vpn: None)
    monkeypatch.setattr(main.shutil, "which", lambda name: "/usr/sbin/ip" if name == "ip" else None)
    monkeypatch.setattr(main.getpass, "getuser", lambda: "pytest")
    monkeypatch.setattr(
        main,
        "get_backend_state",
        lambda: BackendState(table_id="200", active="none", ok=False, table_has_default=False),
    )
    monkeypatch.setattr(main, "ip_rule_text", lambda: "0: from all lookup local\n")
    monkeypatch.setattr(main, "route_table_text", lambda: "default dev sbtun0\n")
    monkeypatch.setattr(
        main,
        "get_vpn_interface_states",
        lambda route_table=None: [
            VpnInterfaceState(
                name="tun0",
                ok=False,
                exists=False,
                up=False,
                has_addresses=False,
                addresses=[],
                in_route_table=False,
                is_default_route=False,
            ),
            VpnInterfaceState(
                name="sbtun0",
                ok=True,
                exists=True,
                up=True,
                has_addresses=True,
                addresses=["172.19.0.2/30"],
                in_route_table=True,
                is_default_route=True,
            ),
        ],
    )

    client = TestClient(main.app)

    wireguard_page = client.get("/wireguard")
    assert wireguard_page.status_code == 200
    assert "wg-test0" in wireguard_page.text

    device_types = client.get("/api/device-types")
    assert device_types.status_code == 200
    assert {"value": "tv", "label": "TV"} in device_types.json()

    created = client.post(
        "/api/devices",
        json={
            "name": "Living Room TV",
            "ip": "192.168.50.40",
            "mac": "aa:bb:cc:dd:ee:40",
            "type": "tv",
        },
    )
    assert created.status_code == 200

    updated = client.patch(
        "/api/devices/aa:bb:cc:dd:ee:40",
        json={"name": "Main TV", "type": "console", "pinned": True},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Main TV"
    assert updated.json()["type"] == "console"
    assert updated.json()["pinned"] is True

    listed = client.get("/api/devices")
    assert listed.status_code == 200
    assert [device["name"] for device in listed.json()] == ["Main TV"]

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["dry_run"] is True
    assert health.json()["devices_file_ok"] is True
    assert health.json()["remotes_file_ok"] is True
    assert health.json()["ip_command_available"] is True
    assert health.json()["service_user"] == "pytest"

    diagnostics = client.get("/api/diagnostics")
    assert diagnostics.status_code == 200
    assert diagnostics.json()["dry_run"] is True
    assert diagnostics.json()["table_id"] == "200"
    assert diagnostics.json()["ap_interface"] == "wlan0"
    assert diagnostics.json()["vpn_interfaces"][1]["name"] == "sbtun0"
    assert diagnostics.json()["vpn_interfaces"][1]["ok"] is True
    assert diagnostics.json()["ip_rules"] == "0: from all lookup local\n"
    assert diagnostics.json()["route_table"] == "default dev sbtun0\n"
