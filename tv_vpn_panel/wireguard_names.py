from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .models import (
    WireGuardClientProfile,
    WireGuardNameSyncResponse,
)
from .wireguard_registry import (
    load_wireguard_profiles,
    save_wireguard_profiles,
)


@dataclass(frozen=True)
class WireGuardConfigPeer:
    public_key: str
    ip: str
    name: str | None = None


def _clean_comment_name(comment: str) -> str | None:
    value = comment.strip()

    if not value:
        return None

    lower_value = value.lower()

    for prefix in (
        "name:",
        "name=",
        "client:",
        "client=",
        "peer:",
        "peer=",
    ):
        if lower_value.startswith(prefix):
            value = value[len(prefix):].strip()
            break

    if not value:
        return None

    # Ограничение модели WireGuardClientProfile.
    if len(value) > 80:
        value = value[:80].rstrip()

    return value or None


def _first_ipv4(allowed_ips: list[str]) -> str | None:
    for raw_value in allowed_ips:
        value = raw_value.strip()

        if not value:
            continue

        try:
            interface = ipaddress.ip_interface(value)
        except ValueError:
            continue

        if interface.version == 4:
            return str(interface.ip)

    return None


def parse_wireguard_config(
    text: str,
) -> list[WireGuardConfigPeer]:
    peers: list[WireGuardConfigPeer] = []

    in_peer = False
    pending_name: str | None = None
    peer_name: str | None = None
    public_key: str | None = None
    allowed_ips: list[str] = []

    def flush_peer() -> None:
        if not in_peer or not public_key:
            return

        client_ip = _first_ipv4(allowed_ips)

        if not client_ip:
            return

        peers.append(
            WireGuardConfigPeer(
                public_key=public_key,
                ip=client_ip,
                name=peer_name,
            )
        )

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            comment_name = _clean_comment_name(
                line[1:]
            )

            if comment_name:
                peer_has_fields = bool(
                    public_key
                    or allowed_ips
                )

                if (
                    in_peer
                    and not peer_has_fields
                ):
                    # Комментарий сразу после [Peer]
                    # является именем текущего клиента.
                    if peer_name is None:
                        peer_name = comment_name
                else:
                    # Комментарий перед следующим
                    # [Peer] относится к следующему
                    # клиенту.
                    pending_name = comment_name

            continue

        if (
            line.startswith("[")
            and line.endswith("]")
        ):
            flush_peer()

            section = line[1:-1].strip().lower()
            in_peer = section == "peer"

            peer_name = (
                pending_name
                if in_peer
                else None
            )
            pending_name = None
            public_key = None
            allowed_ips = []
            continue

        if not in_peer:
            pending_name = None
            continue

        key, separator, value = line.partition("=")

        if not separator:
            continue

        normalized_key = key.strip().lower()
        normalized_value = value.strip()

        if normalized_key == "publickey":
            public_key = normalized_value
        elif normalized_key == "allowedips":
            allowed_ips = [
                item.strip()
                for item in normalized_value.split(",")
                if item.strip()
            ]

    flush_peer()

    return peers


def load_wireguard_config_peers(
    config_file: Path | None = None,
) -> list[WireGuardConfigPeer]:
    path = (
        config_file
        if config_file is not None
        else settings.wireguard_config_file
    )

    return parse_wireguard_config(
        path.read_text(encoding="utf-8")
    )


def sync_wireguard_client_names(
    *,
    config_file: Path | None = None,
    overwrite: bool = False,
) -> WireGuardNameSyncResponse:
    path = (
        config_file
        if config_file is not None
        else settings.wireguard_config_file
    )

    config_peers = load_wireguard_config_peers(
        path
    )
    profiles = load_wireguard_profiles()

    updated_count = 0
    preserved_count = 0
    skipped_without_name = 0
    named_count = 0

    for config_peer in config_peers:
        if not config_peer.name:
            skipped_without_name += 1
            continue

        named_count += 1

        existing = next(
            (
                profile
                for profile in profiles
                if (
                    profile.public_key
                    == config_peer.public_key
                    or profile.ip
                    == config_peer.ip
                )
            ),
            None,
        )

        if (
            existing is not None
            and existing.name == config_peer.name
        ):
            preserved_count += 1
            continue

        if (
            existing is not None
            and existing.name
            and not overwrite
        ):
            preserved_count += 1
            continue

        routing_mode = (
            existing.routing_mode
            if existing is not None
            else "auto"
        )

        profiles = [
            profile
            for profile in profiles
            if (
                profile.public_key
                != config_peer.public_key
                and profile.ip
                != config_peer.ip
            )
        ]

        profiles.append(
            WireGuardClientProfile(
                public_key=config_peer.public_key,
                ip=config_peer.ip,
                name=config_peer.name,
                routing_mode=routing_mode,
            )
        )

        updated_count += 1

    if updated_count:
        save_wireguard_profiles(profiles)

    return WireGuardNameSyncResponse(
        config_file=str(path),
        discovered=len(config_peers),
        with_names=named_count,
        updated=updated_count,
        preserved=preserved_count,
        skipped_without_name=(
            skipped_without_name
        ),
    )
