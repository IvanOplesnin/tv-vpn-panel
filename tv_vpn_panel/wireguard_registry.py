from __future__ import annotations

import ipaddress
import json
import os
import tempfile
from pathlib import Path

from .config import settings
from .models import (
    WireGuardClientProfile,
    WireGuardRoutingMode,
)


VALID_ROUTING_MODES = {
    "auto",
    "direct",
    "openvpn",
    "vless",
}


def _profile_sort_key(
    profile: WireGuardClientProfile,
) -> tuple[int, str]:
    try:
        return (
            int(ipaddress.ip_address(profile.ip)),
            profile.public_key,
        )
    except ValueError:
        return 2**32, profile.public_key


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp_name: str | None = None

    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(
                data,
                temp_file,
                ensure_ascii=False,
                indent=2,
            )
            temp_file.write("\n")
            temp_name = temp_file.name

        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def load_wireguard_profiles() -> list[WireGuardClientProfile]:
    path = settings.wireguard_clients_file

    if not path.exists():
        return []

    try:
        raw = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(raw, list):
        return []

    profiles: list[WireGuardClientProfile] = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        try:
            profile = WireGuardClientProfile(**item)
        except Exception:
            continue

        profiles.append(profile)

    profiles.sort(key=_profile_sort_key)
    return profiles


def save_wireguard_profiles(
    profiles: list[WireGuardClientProfile],
) -> None:
    profiles = sorted(
        profiles,
        key=_profile_sort_key,
    )

    _atomic_write_json(
        settings.wireguard_clients_file,
        [
            profile.model_dump(
                mode="json",
                exclude_none=True,
            )
            for profile in profiles
        ],
    )


def upsert_wireguard_profile(
    *,
    public_key: str,
    ip: str,
    name: str | None = None,
    routing_mode: WireGuardRoutingMode | None = None,
) -> WireGuardClientProfile:
    public_key = public_key.strip()
    ip = ip.strip()

    if not public_key:
        raise ValueError("public_key is required")

    try:
        parsed_ip = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise ValueError(
            "invalid WireGuard client IP"
        ) from exc

    if parsed_ip.version != 4:
        raise ValueError(
            "WireGuard client must use IPv4"
        )

    if name is None and routing_mode is None:
        raise ValueError(
            "no profile changes requested"
        )

    normalized_name: str | None = None

    if name is not None:
        normalized_name = name.strip()

        if not normalized_name:
            raise ValueError(
                "name must not be empty"
            )

        if len(normalized_name) > 80:
            raise ValueError(
                "name is too long"
            )

    normalized_mode: WireGuardRoutingMode | None = None

    if routing_mode is not None:
        mode_value = str(routing_mode).strip().lower()

        if mode_value not in VALID_ROUTING_MODES:
            raise ValueError(
                "invalid routing mode"
            )

        normalized_mode = mode_value  # type: ignore[assignment]

    profiles = load_wireguard_profiles()

    existing = next(
        (
            profile
            for profile in profiles
            if profile.public_key == public_key
        ),
        None,
    )

    if existing is None:
        existing = next(
            (
                profile
                for profile in profiles
                if profile.ip == ip
            ),
            None,
        )

    profile_name = (
        existing.name
        if existing is not None
        else None
    )

    profile_mode: WireGuardRoutingMode = (
        existing.routing_mode
        if existing is not None
        else "auto"
    )

    if normalized_name is not None:
        profile_name = normalized_name

    if normalized_mode is not None:
        profile_mode = normalized_mode

    profiles = [
        profile
        for profile in profiles
        if (
            profile.public_key != public_key
            and profile.ip != ip
        )
    ]

    updated = WireGuardClientProfile(
        public_key=public_key,
        ip=ip,
        name=profile_name,
        routing_mode=profile_mode,
    )

    profiles.append(updated)
    save_wireguard_profiles(profiles)

    return updated
