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


class VpnInterfaceState(BaseModel):
    name: str
    ok: bool = False
    exists: bool = False
    up: bool = False
    has_addresses: bool = False
    addresses: list[str] = Field(default_factory=list)
    in_route_table: bool = False
    is_default_route: bool = False


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
    dry_run: bool = False
    devices_file_ok: bool = False
    remotes_file_ok: bool = False
    leases_file_exists: bool = False
    can_read_leases: bool = False
    ip_command_available: bool = False
    service_user: str | None = None
    backend_switch_allowed: bool = False


class DiagnosticsResponse(BaseModel):
    dry_run: bool
    backend: BackendState
    devices_file: str
    remotes_file: str
    leases_file: str
    backend_switch_script: str
    table_id: str
    ap_interface: str
    route_test_ip: str
    devices_count: int
    managed_devices_count: int
    remotes_count: int
    online_remotes_count: int
    ip_command_available: bool
    vpn_interfaces: list[VpnInterfaceState] = Field(default_factory=list)
    ip_rules: str
    route_table: str


class ViewerResponse(BaseModel):
    ip: str | None = None


WireGuardRoutingMode = Literal[
    "auto",
    "direct",
    "openvpn",
    "vless",
]


class WireGuardClientProfile(BaseModel):
    public_key: str
    ip: str
    name: str | None = None
    routing_mode: WireGuardRoutingMode = "auto"


class WireGuardClientUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    routing_mode: WireGuardRoutingMode | None = None


class WireGuardPeerState(BaseModel):
    public_key: str
    public_key_short: str
    name: str | None = None
    name_is_default: bool = True
    routing_mode: WireGuardRoutingMode = "auto"
    routing_mode_applied: bool = False
    endpoint: str | None = None
    allowed_ips: list[str] = Field(default_factory=list)
    ip: str | None = None
    status: Literal["online", "idle", "never"] = "never"
    latest_handshake_unix: int = 0
    latest_handshake_at: str | None = None
    latest_handshake_age_seconds: int | None = None
    transfer_rx_bytes: int = 0
    transfer_tx_bytes: int = 0
    persistent_keepalive_seconds: int = 0
    route_probe_ok: bool = False
    route_probe: str | None = None


class WireGuardStatusResponse(BaseModel):
    ok: bool = True
    interface: str = "wg0"
    generated_at: str
    online_threshold_seconds: int = 180
    peers: list[WireGuardPeerState] = Field(default_factory=list)
    error: str | None = None


class WireGuardNameSyncResponse(BaseModel):
    ok: bool = True
    config_file: str
    discovered: int
    with_names: int
    updated: int
    preserved: int
    skipped_without_name: int


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
