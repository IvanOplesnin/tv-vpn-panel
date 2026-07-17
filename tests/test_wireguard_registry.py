from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def configure_registry(
    tmp_path,
    monkeypatch,
):
    from tv_vpn_panel import wireguard_registry

    registry_file = (
        tmp_path / "wireguard-clients.json"
    )

    monkeypatch.setattr(
        wireguard_registry,
        "settings",
        SimpleNamespace(
            wireguard_clients_file=registry_file,
        ),
    )

    return wireguard_registry, registry_file


def test_legacy_profile_defaults_to_auto(
    tmp_path,
    monkeypatch,
):
    registry, registry_file = configure_registry(
        tmp_path,
        monkeypatch,
    )

    registry_file.write_text(
        json.dumps(
            [
                {
                    "public_key": "peer-key-one",
                    "ip": "10.10.0.6",
                    "name": "Test phone",
                }
            ]
        ),
        encoding="utf-8",
    )

    profiles = registry.load_wireguard_profiles()

    assert len(profiles) == 1
    assert profiles[0].name == "Test phone"
    assert profiles[0].routing_mode == "auto"


def test_wireguard_profile_partial_updates(
    tmp_path,
    monkeypatch,
):
    registry, _ = configure_registry(
        tmp_path,
        monkeypatch,
    )

    created = registry.upsert_wireguard_profile(
        public_key="peer-key-one",
        ip="10.10.0.6",
        name="Test phone",
    )

    assert created.name == "Test phone"
    assert created.routing_mode == "auto"

    mode_updated = registry.upsert_wireguard_profile(
        public_key="peer-key-one",
        ip="10.10.0.6",
        routing_mode="direct",
    )

    assert mode_updated.name == "Test phone"
    assert mode_updated.routing_mode == "direct"

    name_updated = registry.upsert_wireguard_profile(
        public_key="peer-key-one",
        ip="10.10.0.6",
        name="Bedroom tablet",
    )

    assert name_updated.name == "Bedroom tablet"
    assert name_updated.routing_mode == "direct"

    profiles = registry.load_wireguard_profiles()

    assert len(profiles) == 1
    assert profiles[0].name == "Bedroom tablet"
    assert profiles[0].routing_mode == "direct"


def test_wireguard_profile_validation(
    tmp_path,
    monkeypatch,
):
    registry, _ = configure_registry(
        tmp_path,
        monkeypatch,
    )

    with pytest.raises(
        ValueError,
        match="name must not be empty",
    ):
        registry.upsert_wireguard_profile(
            public_key="peer-key-one",
            ip="10.10.0.6",
            name="   ",
        )

    with pytest.raises(
        ValueError,
        match="invalid routing mode",
    ):
        registry.upsert_wireguard_profile(
            public_key="peer-key-one",
            ip="10.10.0.6",
            routing_mode="invalid",
        )

    with pytest.raises(
        ValueError,
        match="no profile changes requested",
    ):
        registry.upsert_wireguard_profile(
            public_key="peer-key-one",
            ip="10.10.0.6",
        )
