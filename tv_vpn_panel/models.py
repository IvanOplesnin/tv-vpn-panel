from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field
from typing import Literal


BackendName = Literal["openvpn", "sing-box", "none", "unknown"]


class DeviceType(str, Enum):
    TV = "tv"
    PHONE = "phone"
    TABLET = "tablet"
    LAPTOP = "laptop"
    DESKTOP = "desktop"
    CONSOLE = "console"
    IOT = "iot"
    UNKNOWN = "unknown"


class DeviceTypeInfo(BaseModel):
    value: DeviceType
    label: str


DEVICE_TYPE_LABELS: dict[DeviceType, str] = {
    DeviceType.TV: "TV",
    DeviceType.PHONE: "Phone",
    DeviceType.TABLET: "Tablet",
    DeviceType.LAPTOP: "Laptop",
    DeviceType.DESKTOP: "Desktop",
    DeviceType.CONSOLE: "Game console",
    DeviceType.IOT: "IoT",
    DeviceType.UNKNOWN: "Unknown",
}


def device_type_options() -> list[DeviceTypeInfo]:
    return [
        DeviceTypeInfo(value=device_type, label=label)
        for device_type, label in DEVICE_TYPE_LABELS.items()
    ]


class Device(BaseModel):
    name: str
    ip: str
    mac: str
    vpn: bool = False
    type: DeviceType = DeviceType.TV
    pinned: bool = False
    name_override: bool = False
    lease_name: str | None = None
    lease_expiry: str | None = None


class DeviceCreate(BaseModel):
    name: str
    ip: str
    mac: str | None = None
    type: DeviceType = DeviceType.TV


class DeviceUpdate(BaseModel):
    name: str | None = None
    type: DeviceType | None = None
    pinned: bool | None = None


class Remote(BaseModel):
    remote_id: str
    name: str | None = None
    remote_mac: str | None = None
    target_mac: str | None = None
    enabled: bool = True
    firmware: str | None = None
    last_seen: str | None = None
    last_ip: str | None = None


class RemoteCreate(BaseModel):
    remote_id: str
    name: str | None = None
    remote_mac: str | None = None
    target_mac: str | None = None
    enabled: bool = True
    firmware: str | None = None


class RemoteBindRequest(BaseModel):
    target_mac: str


class RemoteUpdateRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    target_mac: str | None = None


class SetVpnRequest(BaseModel):
    vpn: bool


class ToggleResponse(BaseModel):
    ok: bool
    device: Device


class BackendState(BaseModel):
    active: BackendName = "unknown"
    ok: bool = False
    table_id: str
    table_has_default: bool = False
    default_route: str | None = None


class DeviceRuntimeState(BaseModel):
    rule_present: bool = False
    route_probe_ok: bool = False
    route_probe: str | None = None


class DeviceState(BaseModel):
    ok: bool = True
    device: Device
    backend: BackendState
    runtime: DeviceRuntimeState


class HealthResponse(BaseModel):
    ok: bool
    backend: BackendState
    devices_count: int
    managed_devices_count: int
    remotes_count: int = 0
    online_remotes_count: int = 0


class WsInbound(BaseModel):
    type: Literal["hello", "ping", "get_state", "set_vpn", "toggle_vpn", "sync"]
    remote_id: str | None = None
    remote_name: str | None = None
    remote_mac: str | None = None
    target_mac: str | None = None
    token: str | None = None
    vpn: bool | None = None
    firmware: str | None = None


class WsOutbound(BaseModel):
    type: str
    ok: bool = True
    message: str | None = None
    remote_id: str | None = None
    target_mac: str | None = None
    remote: Remote | None = None
    state: DeviceState | None = None
    devices: list[Device] | None = None
    remotes: list[Remote] | None = None
    backend: BackendState | None = None


class ApiMessage(BaseModel):
    ok: bool = True
    message: str = Field(default="ok")
