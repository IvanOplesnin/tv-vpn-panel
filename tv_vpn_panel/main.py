from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .auth import require_http_token, require_ws_token
from .config import settings
from .models import (
    ApiMessage,
    Device,
    DeviceCreate,
    DeviceState,
    HealthResponse,
    SetVpnRequest,
    ToggleResponse,
    WsInbound,
    WsOutbound,
)
from .store import (
    add_device,
    apply_all_rules,
    delete_device,
    find_device,
    load_devices,
    managed_devices,
    set_device_vpn,
    sync_devices_from_leases,
    toggle_device_vpn,
)
from .system_ops import get_backend_state, probe_device_route, refresh_backend_route
from .ws import manager

BASE_DIR = Path(__file__).resolve().parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="TV VPN Panel", version="0.1.0")
state_lock = asyncio.Lock()
periodic_task: asyncio.Task | None = None


def build_device_state(device: Device) -> DeviceState:
    return DeviceState(
        device=device,
        backend=get_backend_state(),
        runtime=probe_device_route(device.ip),
    )


async def broadcast_device(mac: str) -> None:
    device = find_device(mac)
    if device is None:
        return
    await manager.broadcast_state(build_device_state(device))


async def sync_and_broadcast_all() -> None:
    devices = sync_devices_from_leases()
    backend = get_backend_state()
    await manager.broadcast(WsOutbound(type="devices", devices=managed_devices(devices), backend=backend))
    for device in managed_devices(devices):
        await manager.broadcast_state(build_device_state(device))


async def periodic_sync_loop() -> None:
    while True:
        await asyncio.sleep(settings.poll_interval_seconds)
        try:
            async with state_lock:
                await asyncio.to_thread(sync_devices_from_leases)
            await sync_and_broadcast_all()
        except Exception:
            # Keep the background task alive; errors are visible via HTTP health/status.
            pass


@app.on_event("startup")
async def startup() -> None:
    global periodic_task
    async with state_lock:
        await asyncio.to_thread(apply_all_rules)
    if settings.enable_periodic_sync:
        periodic_task = asyncio.create_task(periodic_sync_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    if periodic_task:
        periodic_task.cancel()
        with suppress(asyncio.CancelledError):
            await periodic_task


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "api_token_enabled": bool(settings.api_token),
        },
    )


@app.get("/api/health", response_model=HealthResponse)
async def health(_: None = Depends(require_http_token)) -> HealthResponse:
    devices = load_devices()
    return HealthResponse(
        ok=True,
        backend=get_backend_state(),
        devices_count=len(devices),
        managed_devices_count=len(managed_devices(devices)),
    )


@app.get("/api/devices", response_model=list[Device])
async def api_devices(_: None = Depends(require_http_token)) -> list[Device]:
    async with state_lock:
        devices = await asyncio.to_thread(sync_devices_from_leases)
    return managed_devices(devices)


@app.post("/api/devices/sync", response_model=list[Device])
async def api_sync(_: None = Depends(require_http_token)) -> list[Device]:
    async with state_lock:
        devices = await asyncio.to_thread(apply_all_rules)
    await sync_and_broadcast_all()
    return managed_devices(devices)


@app.post("/api/backend/refresh", response_model=ApiMessage)
async def api_backend_refresh(_: None = Depends(require_http_token)) -> ApiMessage:
    ok, message = await asyncio.to_thread(refresh_backend_route)
    await sync_and_broadcast_all()
    return ApiMessage(ok=ok, message=message)


@app.post("/api/devices", response_model=Device)
async def api_add_device(payload: DeviceCreate, _: None = Depends(require_http_token)) -> Device:
    async with state_lock:
        device = await asyncio.to_thread(add_device, payload)
    await sync_and_broadcast_all()
    return device


@app.get("/api/devices/{mac}", response_model=DeviceState)
async def api_device_state(mac: str, _: None = Depends(require_http_token)) -> DeviceState:
    async with state_lock:
        await asyncio.to_thread(sync_devices_from_leases)
        device = find_device(mac)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    return build_device_state(device)


@app.post("/api/devices/{mac}/vpn", response_model=ToggleResponse)
async def api_set_vpn(mac: str, payload: SetVpnRequest, _: None = Depends(require_http_token)) -> ToggleResponse:
    try:
        async with state_lock:
            device = await asyncio.to_thread(set_device_vpn, mac, payload.vpn)
    except KeyError:
        raise HTTPException(status_code=404, detail="device not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_device(mac)
    return ToggleResponse(ok=True, device=device)


@app.post("/api/devices/{mac}/toggle", response_model=ToggleResponse)
async def api_toggle_vpn(mac: str, _: None = Depends(require_http_token)) -> ToggleResponse:
    try:
        async with state_lock:
            device = await asyncio.to_thread(toggle_device_vpn, mac)
    except KeyError:
        raise HTTPException(status_code=404, detail="device not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await broadcast_device(mac)
    return ToggleResponse(ok=True, device=device)


@app.delete("/api/devices/{mac}", response_model=ApiMessage)
async def api_delete_device(mac: str, _: None = Depends(require_http_token)) -> ApiMessage:
    async with state_lock:
        removed = await asyncio.to_thread(delete_device, mac)
    await sync_and_broadcast_all()
    if not removed:
        raise HTTPException(status_code=404, detail="device not found")
    return ApiMessage(ok=True, message="deleted")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await require_ws_token(websocket)
    await manager.connect(websocket)
    target_mac = websocket.query_params.get("target_mac")
    remote_id = websocket.query_params.get("remote_id")
    await manager.register(websocket, remote_id=remote_id, target_mac=target_mac)

    if target_mac:
        device = find_device(target_mac)
        if device:
            await manager.send(websocket, WsOutbound(type="state", state=build_device_state(device)))
        else:
            await manager.send(
                websocket,
                WsOutbound(type="error", ok=False, message="target device not found", target_mac=target_mac),
            )
    else:
        await manager.send(
            websocket,
            WsOutbound(type="devices", devices=managed_devices(load_devices()), backend=get_backend_state()),
        )

    try:
        while True:
            payload = await websocket.receive_json()
            inbound = WsInbound(**payload)

            if inbound.type == "hello":
                await require_ws_token(websocket, inbound.token)
                if inbound.target_mac:
                    target_mac = inbound.target_mac.lower()
                if inbound.remote_id:
                    remote_id = inbound.remote_id
                await manager.register(websocket, remote_id=remote_id, target_mac=target_mac)
                await manager.send(
                    websocket,
                    WsOutbound(
                        type="hello_ok",
                        remote_id=remote_id,
                        target_mac=target_mac,
                        backend=get_backend_state(),
                    ),
                )
                if target_mac:
                    device = find_device(target_mac)
                    if device:
                        await manager.send(websocket, WsOutbound(type="state", state=build_device_state(device)))
                continue

            if inbound.type == "ping":
                await manager.send(websocket, WsOutbound(type="pong", remote_id=remote_id, target_mac=target_mac))
                continue

            if inbound.type == "sync":
                async with state_lock:
                    await asyncio.to_thread(apply_all_rules)
                await sync_and_broadcast_all()
                continue

            effective_mac = (inbound.target_mac or target_mac or "").lower()
            if not effective_mac:
                await manager.send(websocket, WsOutbound(type="error", ok=False, message="target_mac is required"))
                continue

            if inbound.type == "get_state":
                device = find_device(effective_mac)
                if not device:
                    await manager.send(websocket, WsOutbound(type="error", ok=False, message="device not found"))
                    continue
                await manager.send(websocket, WsOutbound(type="state", state=build_device_state(device)))
                continue

            if inbound.type == "set_vpn":
                if inbound.vpn is None:
                    await manager.send(websocket, WsOutbound(type="error", ok=False, message="vpn boolean is required"))
                    continue
                try:
                    async with state_lock:
                        await asyncio.to_thread(set_device_vpn, effective_mac, inbound.vpn)
                except Exception as exc:
                    await manager.send(websocket, WsOutbound(type="error", ok=False, message=str(exc)))
                    continue
                await broadcast_device(effective_mac)
                continue

            if inbound.type == "toggle_vpn":
                try:
                    async with state_lock:
                        await asyncio.to_thread(toggle_device_vpn, effective_mac)
                except Exception as exc:
                    await manager.send(websocket, WsOutbound(type="error", ok=False, message=str(exc)))
                    continue
                await broadcast_device(effective_mac)
                continue

    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
        with suppress(Exception):
            await websocket.close()
