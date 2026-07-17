from __future__ import annotations


def test_wireguard_client_name_api(monkeypatch):
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

        return WireGuardStatusResponse(
            ok=True,
            interface="wg0",
            generated_at="2026-07-17T10:00:00+00:00",
            peers=[
                WireGuardPeerState(
                    public_key="peer-key-one",
                    public_key_short="peer-key-one",
                    name=name,
                    name_is_default="name" not in saved,
                    allowed_ips=["10.10.0.6/32"],
                    ip="10.10.0.6",
                    status="idle",
                    route_probe_ok=True,
                    route_probe=(
                        "8.8.8.8 from 10.10.0.6 "
                        "via 10.8.0.1 dev tun0 table 200"
                    ),
                )
            ],
        )

    def fake_upsert(
        *,
        public_key: str,
        ip: str,
        name: str,
    ):
        assert public_key == "peer-key-one"
        assert ip == "10.10.0.6"
        saved["name"] = name

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

    response = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={"name": "Bedroom tablet"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Bedroom tablet"
    assert response.json()["name_is_default"] is False
