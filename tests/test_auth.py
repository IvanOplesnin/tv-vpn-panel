from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_http_token_is_header_only(monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from tv_vpn_panel import auth

    monkeypatch.setattr(
        auth,
        "settings",
        SimpleNamespace(api_token="expected-token"),
    )

    app = FastAPI()

    @app.get("/secure")
    async def secure(_: None = Depends(auth.require_http_token)):
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/secure?token=expected-token").status_code == 401
    assert (
        client.get(
            "/secure",
            headers={"X-API-Token": "expected-token"},
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/secure",
            headers={"Authorization": "Bearer expected-token"},
        ).status_code
        == 200
    )


def test_websocket_token_does_not_use_query_string(monkeypatch):
    from tv_vpn_panel import auth

    monkeypatch.setattr(
        auth,
        "settings",
        SimpleNamespace(api_token="expected-token"),
    )

    class FakeWebSocket:
        query_params = {"token": "expected-token"}

        def __init__(self):
            self.closed = False

        async def close(self, **_kwargs):
            self.closed = True

    websocket = FakeWebSocket()

    try:
        asyncio.run(auth.require_ws_token(websocket))
    except RuntimeError:
        pass
    else:
        raise AssertionError("query-string token was unexpectedly accepted")

    assert websocket.closed is True

    authenticated = FakeWebSocket()
    asyncio.run(
        auth.require_ws_token(
            authenticated,
            "expected-token",
        )
    )
    assert authenticated.closed is False
