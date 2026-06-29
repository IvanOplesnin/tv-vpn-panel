from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .config import settings
from .models import Device, DeviceCreate, Remote, RemoteCreate, RemoteUpdateRequest
from .system_ops import apply_device_rule, disable_vpn_rule


def _normal_mac(mac: str | None) -> str:
    if not mac:
        return ""
    return mac.strip().lower()


def _normal_remote_id(remote_id: str | None) -> str:
    return (remote_id or "").strip()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
        tmp_name = tmp.name

    os.replace(tmp_name, path)


def load_devices() -> list[Device]:
    path = settings.devices_file
    if not path.exists():
        save_devices([])
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(raw, list):
        return []

    devices: list[Device] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            # Backward-compatible with the current Flask devices.json.
            if "type" not in item:
                item["type"] = "tv"
            devices.append(Device(**item))
        except Exception:
            continue
    return devices


def save_devices(devices: list[Device]) -> None:
    data = [d.model_dump(exclude_none=True) for d in devices]
    _atomic_write_json(settings.devices_file, data)


def load_remotes() -> list[Remote]:
    path = settings.remotes_file
    if not path.exists():
        save_remotes([])
        return []

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(raw, list):
        return []

    remotes: list[Remote] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            remotes.append(Remote(**item))
        except Exception:
            continue
    return remotes


def save_remotes(remotes: list[Remote]) -> None:
    data = [r.model_dump(exclude_none=True) for r in remotes]
    _atomic_write_json(settings.remotes_file, data)


def find_remote(remote_id: str, remotes: list[Remote] | None = None) -> Remote | None:
    remote_id = _normal_remote_id(remote_id)
    remotes = remotes if remotes is not None else load_remotes()
    for remote in remotes:
        if remote.remote_id == remote_id:
            return remote
    return None


def add_or_update_remote(payload: RemoteCreate) -> Remote:
    remote_id = _normal_remote_id(payload.remote_id)
    if not remote_id:
        raise ValueError("remote_id is required")

    remotes = load_remotes()
    existing = find_remote(remote_id, remotes)
    target_mac = _normal_mac(payload.target_mac) or None
    remote_mac = _normal_mac(payload.remote_mac) or None

    if existing is not None:
        if payload.name is not None:
            existing.name = payload.name.strip() or None
        if remote_mac is not None:
            existing.remote_mac = remote_mac
        if payload.target_mac is not None:
            existing.target_mac = target_mac
        existing.enabled = payload.enabled
        if payload.firmware is not None:
            existing.firmware = payload.firmware
        save_remotes(remotes)
        return existing

    remote = Remote(
        remote_id=remote_id,
        name=(payload.name or "").strip() or None,
        remote_mac=remote_mac,
        target_mac=target_mac,
        enabled=payload.enabled,
        firmware=payload.firmware,
    )
    remotes.append(remote)
    save_remotes(remotes)
    return remote


def register_remote_seen(
    remote_id: str,
    *,
    name: str | None = None,
    remote_mac: str | None = None,
    target_mac: str | None = None,
    firmware: str | None = None,
    last_ip: str | None = None,
) -> Remote:
    """Create/update a remote when it connects through WebSocket.

    If target_mac is provided by the ESP32 setup page, it becomes/updates the binding.
    If target_mac is omitted, an existing binding is preserved.
    """
    remote_id = _normal_remote_id(remote_id)
    if not remote_id:
        raise ValueError("remote_id is required")

    remotes = load_remotes()
    remote = find_remote(remote_id, remotes)
    if remote is None:
        remote = Remote(remote_id=remote_id)
        remotes.append(remote)

    if name is not None:
        remote.name = name.strip() or None
    normalized_remote_mac = _normal_mac(remote_mac) or None
    if normalized_remote_mac is not None:
        remote.remote_mac = normalized_remote_mac
    if target_mac is not None:
        remote.target_mac = _normal_mac(target_mac) or None
    if firmware is not None:
        remote.firmware = firmware
    if last_ip is not None:
        remote.last_ip = last_ip
    remote.last_seen = _utc_now()

    save_remotes(remotes)
    return remote


def bind_remote(remote_id: str, target_mac: str) -> Remote:
    remotes = load_remotes()
    remote = find_remote(remote_id, remotes)
    if remote is None:
        remote = Remote(remote_id=_normal_remote_id(remote_id))
        remotes.append(remote)
    if not remote.remote_id:
        raise ValueError("remote_id is required")

    normalized_target = _normal_mac(target_mac)
    if not normalized_target:
        raise ValueError("target_mac is required")
    remote.target_mac = normalized_target
    save_remotes(remotes)
    return remote


def unbind_remote(remote_id: str) -> Remote:
    remotes = load_remotes()
    remote = find_remote(remote_id, remotes)
    if remote is None:
        raise KeyError(remote_id)
    remote.target_mac = None
    save_remotes(remotes)
    return remote


def update_remote(remote_id: str, payload: RemoteUpdateRequest) -> Remote:
    remotes = load_remotes()
    remote = find_remote(remote_id, remotes)
    if remote is None:
        raise KeyError(remote_id)
    if payload.name is not None:
        remote.name = payload.name.strip() or None
    if payload.enabled is not None:
        remote.enabled = payload.enabled
    if payload.target_mac is not None:
        remote.target_mac = _normal_mac(payload.target_mac) or None
    save_remotes(remotes)
    return remote


def delete_remote(remote_id: str) -> bool:
    remote_id = _normal_remote_id(remote_id)
    remotes = load_remotes()
    kept = [r for r in remotes if r.remote_id != remote_id]
    removed = len(kept) != len(remotes)
    if removed:
        save_remotes(kept)
    return removed


def remote_target_mac(remote_id: str | None) -> str | None:
    if not remote_id:
        return None
    remote = find_remote(remote_id)
    if remote and remote.enabled:
        return remote.target_mac.lower() if remote.target_mac else None
    return None


def read_leases() -> list[dict]:
    path = settings.leases_file
    if not path.exists():
        return []

    leases: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for line in lines:
        parts = line.strip().split()
        if len(parts) < 4:
            continue

        expiry, mac, ip, hostname = parts[:4]
        mac = _normal_mac(mac)
        if hostname == "*":
            hostname = f"device-{ip.split('.')[-1]}"

        leases.append(
            {
                "name": hostname,
                "ip": ip,
                "mac": mac,
                "lease_expiry": expiry,
            }
        )
    return leases


def sync_devices_from_leases() -> list[Device]:
    """Sync DHCP leases into devices.json.

    Existing VPN state is preserved. If IP changed, the old rule is removed.
    ESP32 remotes are now tracked in remotes.json, not devices.json.
    """
    devices = load_devices()
    leases = read_leases()

    by_mac = {d.mac.lower(): d for d in devices if d.mac}
    by_ip = {d.ip: d for d in devices if d.ip}

    for lease in leases:
        mac = lease["mac"]
        ip = lease["ip"]
        name = lease["name"]

        if mac in by_mac:
            device = by_mac[mac]
            old_ip = device.ip
            if old_ip and old_ip != ip:
                disable_vpn_rule(old_ip)
            device.ip = ip
            # Preserve custom names for remotes; update plain auto-generated names.
            if device.name.startswith("device-") or name != "*":
                device.name = name
            device.mac = mac
            device.lease_expiry = lease["lease_expiry"]
        elif ip in by_ip:
            device = by_ip[ip]
            device.name = name
            device.mac = mac
            device.lease_expiry = lease["lease_expiry"]
        else:
            devices.append(
                Device(
                    name=name,
                    ip=ip,
                    mac=mac,
                    vpn=False,
                    type="tv",
                    lease_expiry=lease["lease_expiry"],
                )
            )

    save_devices(devices)
    return devices


def managed_devices(devices: list[Device] | None = None) -> list[Device]:
    devices = devices if devices is not None else load_devices()
    return [d for d in devices if d.type != "remote"]


def find_device(mac: str, devices: list[Device] | None = None) -> Device | None:
    mac = _normal_mac(mac)
    devices = devices if devices is not None else load_devices()
    for device in devices:
        if device.mac.lower() == mac:
            return device
    return None


def add_device(payload: DeviceCreate) -> Device:
    devices = load_devices()
    mac = _normal_mac(payload.mac) or f"manual-{payload.ip}"

    existing = find_device(mac, devices)
    if existing is not None:
        existing.name = payload.name
        existing.ip = payload.ip
        existing.type = payload.type
        existing.target_mac = _normal_mac(payload.target_mac) or None
        save_devices(devices)
        return existing

    device = Device(
        name=payload.name.strip(),
        ip=payload.ip.strip(),
        mac=mac,
        vpn=False,
        type=payload.type,
        target_mac=_normal_mac(payload.target_mac) or None,
    )
    devices.append(device)
    save_devices(devices)
    return device


def delete_device(mac: str) -> bool:
    mac = _normal_mac(mac)
    devices = load_devices()
    kept: list[Device] = []
    removed = False
    for device in devices:
        if device.mac.lower() == mac:
            removed = True
            if device.ip:
                disable_vpn_rule(device.ip)
        else:
            kept.append(device)
    if removed:
        save_devices(kept)
    return removed


def set_device_vpn(mac: str, vpn: bool) -> Device:
    devices = sync_devices_from_leases()
    device = find_device(mac, devices)
    if device is None:
        raise KeyError(mac)
    if device.type == "remote":
        raise ValueError("remote devices cannot be routed through VPN directly")

    device.vpn = vpn
    apply_device_rule(device.ip, vpn)
    save_devices(devices)
    return device


def toggle_device_vpn(mac: str) -> Device:
    devices = sync_devices_from_leases()
    device = find_device(mac, devices)
    if device is None:
        raise KeyError(mac)
    return set_device_vpn(mac, not device.vpn)


def apply_all_rules() -> list[Device]:
    devices = sync_devices_from_leases()
    for device in devices:
        if device.type == "remote":
            continue
        apply_device_rule(device.ip, device.vpn)
    return devices
