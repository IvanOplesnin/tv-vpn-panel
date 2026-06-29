from __future__ import annotations

from fastapi import Header, HTTPException, Query, WebSocket, status

from .config import settings


def _valid_token(token: str | None) -> bool:
    if not settings.api_token:
        return True
    return token == settings.api_token


async def require_http_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    bearer = None
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    if not _valid_token(x_api_token or bearer or token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api token")


async def require_ws_token(websocket: WebSocket, token_from_message: str | None = None) -> None:
    token = token_from_message or websocket.query_params.get("token")
    if not _valid_token(token):
        await websocket.close(code=1008, reason="invalid api token")
        raise RuntimeError("invalid api token")
