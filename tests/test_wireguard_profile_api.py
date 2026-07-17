from __future__ import annotations


def test_wireguard_client_profile_api(monkeypatch):
    from fastapi.testclient import TestClient

    from tv_vpn_panel import main
    from tv_vpn_panel.models import (
        WireGuardPeerState,
        WireGuardStatusResponse,
    )

    saved: dict[str, str] = {}

    def fake_status() -> WireGuardStatusResponse:
        name = saved.get(
            "name",
            "WireGuard 10.10.0.6",
        )

        routing_mode = saved.get(
            "routing_mode",
            "auto",
        )

        return WireGuardStatusResponse(
            ok=True,
            interface="wg0",
            generated_at=(
                "2026-07-17T10:00:00+00:00"
            ),
            peers=[
                WireGuardPeerState(
                    public_key="peer-key-one",
                    public_key_short="peer-key-one",
                    name=name,
                    name_is_default="name" not in saved,
                    routing_mode=routing_mode,
                    routing_mode_applied=False,
                    allowed_ips=["10.10.0.6/32"],
                    ip="10.10.0.6",
                    status="idle",
                    route_probe_ok=True,
                    route_probe=(
                        "8.8.8.8 from 10.10.0.6 "
                        "via 10.8.0.1 dev tun0 "
                        "table 200"
                    ),
                )
            ],
        )

    def fake_upsert(
        *,
        public_key: str,
        ip: str,
        name: str | None = None,
        routing_mode: str | None = None,
    ):
        assert public_key == "peer-key-one"
        assert ip == "10.10.0.6"

        if name is not None:
            saved["name"] = name

        if routing_mode is not None:
            saved["routing_mode"] = routing_mode

    monkeypatch.setattr(
        main,
        "get_wireguard_status",
        fake_status,
    )
    monkeypatch.setattr(
        main,
        "upsert_wireguard_profile",
        fake_upsert,
    )

    client = TestClient(main.app)

    renamed = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={"name": "Bedroom tablet"},
    )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Bedroom tablet"
    assert renamed.json()["routing_mode"] == "auto"

    changed_mode = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={"routing_mode": "direct"},
    )

    assert changed_mode.status_code == 200
    assert changed_mode.json()["name"] == "Bedroom tablet"
    assert changed_mode.json()["routing_mode"] == "direct"
    assert (
        changed_mode.json()["routing_mode_applied"]
        is False
    )

    empty_update = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={},
    )

    assert empty_update.status_code == 400
