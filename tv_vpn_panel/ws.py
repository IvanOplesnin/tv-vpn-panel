from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fastapi import WebSocket

from .models import DeviceState, WsOutbound


@dataclass
class ClientInfo:
    websocket: WebSocket
    remote_id: str | None = None
    target_mac: str | None = None


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._info: dict[WebSocket, ClientInfo] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
            self._info[websocket] = ClientInfo(websocket=websocket)

    async def register(self, websocket: WebSocket, remote_id: str | None, target_mac: str | None) -> None:
        async with self._lock:
            info = self._info.get(websocket)
            if info:
                info.remote_id = remote_id
                info.target_mac = target_mac.lower() if target_mac else None

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
            self._info.pop(websocket, None)

    async def send(self, websocket: WebSocket, message: WsOutbound) -> None:
        await websocket.send_json(message.model_dump(exclude_none=True))

    async def broadcast(self, message: WsOutbound) -> None:
        async with self._lock:
            clients = list(self._clients)
        for websocket in clients:
            try:
                await websocket.send_json(message.model_dump(exclude_none=True))
            except Exception:
                await self.disconnect(websocket)

    async def broadcast_state(self, state: DeviceState) -> None:
        async with self._lock:
            clients = list(self._clients)
            info_map = dict(self._info)
        for websocket in clients:
            info = info_map.get(websocket)
            if info and info.target_mac and info.target_mac != state.device.mac.lower():
                continue
            try:
                await websocket.send_json(
                    WsOutbound(type="state", state=state).model_dump(exclude_none=True)
                )
            except Exception:
                await self.disconnect(websocket)


manager = ConnectionManager()
