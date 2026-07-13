from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def store_env(tmp_path, monkeypatch):
    from tv_vpn_panel import store

    cfg = SimpleNamespace(
        devices_file=tmp_path / "devices.json",
        remotes_file=tmp_path / "remotes.json",
        leases_file=tmp_path / "dnsmasq.leases",
        table_id="200",
    )
    calls: dict[str, list] = {"disable": [], "apply": []}

    monkeypatch.setattr(store, "settings", cfg)
    monkeypatch.setattr(store, "disable_vpn_rule", lambda ip: calls["disable"].append(ip))
    monkeypatch.setattr(store, "apply_device_rule", lambda ip, vpn: calls["apply"].append((ip, vpn)))

    return cfg, calls
