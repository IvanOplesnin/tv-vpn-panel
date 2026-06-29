from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import settings
from .models import Device, DeviceCreate
from .system_ops import apply_device_rule, disable_vpn_rule


def _normal_mac(mac: str | None) -> str:
    if not mac:
        return ""
    return mac.strip().lower()


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
    path = settings.devices_file
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [d.model_dump(exclude_none=True) for d in devices]

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
    ESP32 remotes can later be marked as type=remote and hidden from managed TV list.
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
