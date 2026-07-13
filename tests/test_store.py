from __future__ import annotations

from tv_vpn_panel.models import DeviceCreate, DeviceUpdate, RemoteCreate


def test_sync_preserves_custom_name_and_excludes_remote_mac(store_env):
    cfg, _ = store_env
    from tv_vpn_panel import store

    cfg.leases_file.write_text(
        "100 aa:bb:cc:dd:ee:01 192.168.50.10 tv-dhcp *\n"
        "100 aa:bb:cc:dd:ee:02 192.168.50.11 esp32-remote *\n",
        encoding="utf-8",
    )

    store.add_or_update_remote(
        RemoteCreate(
            remote_id="remote-bedroom",
            remote_mac="aa:bb:cc:dd:ee:02",
            target_mac="aa:bb:cc:dd:ee:01",
        )
    )
    devices = store.sync_devices_from_leases()
    assert [device.mac for device in devices] == ["aa:bb:cc:dd:ee:01"]

    updated = store.update_device(
        "aa:bb:cc:dd:ee:01",
        DeviceUpdate(name="Bedroom TV", type="console", pinned=True),
    )
    assert updated.name == "Bedroom TV"
    assert updated.type.value == "console"
    assert updated.pinned is True
    assert updated.name_override is True

    cfg.leases_file.write_text(
        "200 aa:bb:cc:dd:ee:01 192.168.50.10 changed-dhcp-name *\n"
        "200 aa:bb:cc:dd:ee:02 192.168.50.11 esp32-remote *\n",
        encoding="utf-8",
    )
    devices = store.sync_devices_from_leases()
    assert len(devices) == 1
    assert devices[0].name == "Bedroom TV"
    assert devices[0].lease_name == "changed-dhcp-name"
    assert devices[0].pinned is True


def test_managed_devices_returns_pinned_devices_first(store_env):
    from tv_vpn_panel import store

    store.add_device(DeviceCreate(name="Normal", ip="192.168.50.20", mac="aa:bb:cc:dd:ee:20"))
    store.add_device(DeviceCreate(name="Pinned", ip="192.168.50.21", mac="aa:bb:cc:dd:ee:21"))
    store.update_device("aa:bb:cc:dd:ee:21", DeviceUpdate(pinned=True))

    devices = store.managed_devices()
    assert [device.name for device in devices] == ["Pinned", "Normal"]


def test_apply_all_rules_uses_mocked_route_operations(store_env):
    _, calls = store_env
    from tv_vpn_panel import store

    store.add_device(DeviceCreate(name="TV", ip="192.168.50.30", mac="aa:bb:cc:dd:ee:30"))
    store.set_device_vpn("aa:bb:cc:dd:ee:30", True)
    store.apply_all_rules()

    assert ("192.168.50.30", True) in calls["apply"]
