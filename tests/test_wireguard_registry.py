from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_wireguard_profile_create_and_update(
    tmp_path,
    monkeypatch,
):
    from tv_vpn_panel import wireguard_registry

    registry_file = tmp_path / "wireguard-clients.json"

    monkeypatch.setattr(
        wireguard_registry,
        "settings",
        SimpleNamespace(
            wireguard_clients_file=registry_file,
        ),
    )

    created = wireguard_registry.upsert_wireguard_profile(
        public_key="peer-key-one",
        ip="10.10.0.6",
        name="Test phone",
    )

    assert created.name == "Test phone"

    profiles = wireguard_registry.load_wireguard_profiles()

    assert len(profiles) == 1
    assert profiles[0].ip == "10.10.0.6"
    assert profiles[0].name == "Test phone"

    updated = wireguard_registry.upsert_wireguard_profile(
        public_key="peer-key-one",
        ip="10.10.0.6",
        name="Bedroom tablet",
    )

    assert updated.name == "Bedroom tablet"

    profiles = wireguard_registry.load_wireguard_profiles()

    assert len(profiles) == 1
    assert profiles[0].name == "Bedroom tablet"


def test_wireguard_profile_rejects_empty_name(
    tmp_path,
    monkeypatch,
):
    from tv_vpn_panel import wireguard_registry

    monkeypatch.setattr(
        wireguard_registry,
        "settings",
        SimpleNamespace(
            wireguard_clients_file=(
                tmp_path / "wireguard-clients.json"
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="name must not be empty",
    ):
        wireguard_registry.upsert_wireguard_profile(
            public_key="peer-key-one",
            ip="10.10.0.6",
            name="   ",
        )
