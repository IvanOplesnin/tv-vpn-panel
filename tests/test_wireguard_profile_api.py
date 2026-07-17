from __future__ import annotations


def test_wireguard_client_profile_api(
    monkeypatch,
):
    from fastapi.testclient import TestClient

    from tv_vpn_panel import main
    from tv_vpn_panel.models import (
        WireGuardPeerState,
        WireGuardStatusResponse,
    )
    from tv_vpn_panel.wireguard_routing import (
        WireGuardRoutingError,
    )

    saved: dict[str, str] = {}
    applied_mode = {"value": "auto"}
    apply_calls: list[tuple[str, str]] = []
    fail_after_apply = {"value": False}
    fail_persistence = {"value": False}

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
                    name_is_default=(
                        "name" not in saved
                    ),
                    routing_mode=routing_mode,
                    routing_mode_applied=(
                        routing_mode
                        == applied_mode["value"]
                    ),
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

        if fail_persistence["value"]:
            raise ValueError(
                "test persistence failure"
            )

        if name is not None:
            saved["name"] = name

        if routing_mode is not None:
            saved["routing_mode"] = routing_mode

    def fake_apply(
        client_ip: str,
        routing_mode: str,
    ) -> str:
        apply_calls.append(
            (client_ip, routing_mode)
        )
        applied_mode["value"] = routing_mode

        if fail_after_apply["value"]:
            fail_after_apply["value"] = False
            raise WireGuardRoutingError(
                "verification failed after apply"
            )

        return "applied"

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
    monkeypatch.setattr(
        main,
        "apply_wireguard_routing_mode",
        fake_apply,
    )

    client = TestClient(main.app)

    renamed = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={"name": "Bedroom tablet"},
    )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == (
        "Bedroom tablet"
    )
    assert apply_calls == []

    changed_mode = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={"routing_mode": "direct"},
    )

    assert changed_mode.status_code == 200
    assert changed_mode.json()["routing_mode"] == (
        "direct"
    )
    assert (
        changed_mode.json()[
            "routing_mode_applied"
        ]
        is True
    )

    fail_after_apply["value"] = True

    failed_verification = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={"routing_mode": "vless"},
    )

    assert failed_verification.status_code == 409
    assert saved["routing_mode"] == "direct"
    assert applied_mode["value"] == "direct"
    assert apply_calls[-2:] == [
        ("10.10.0.6", "vless"),
        ("10.10.0.6", "direct"),
    ]

    fail_persistence["value"] = True

    failed_save = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={"routing_mode": "openvpn"},
    )

    assert failed_save.status_code == 400
    assert saved["routing_mode"] == "direct"
    assert applied_mode["value"] == "direct"
    assert apply_calls[-2:] == [
        ("10.10.0.6", "openvpn"),
        ("10.10.0.6", "direct"),
    ]

    empty_update = client.patch(
        "/api/wireguard/clients/10.10.0.6",
        json={},
    )

    assert empty_update.status_code == 400
