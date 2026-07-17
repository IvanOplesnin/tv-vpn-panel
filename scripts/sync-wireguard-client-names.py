#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tv_vpn_panel.config import settings
from tv_vpn_panel.wireguard_names import (
    load_wireguard_config_peers,
    sync_wireguard_client_names,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read WireGuard client names from "
            "comments in wg0.conf and save them "
            "to the TV VPN Panel registry."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=settings.wireguard_config_file,
        help=(
            "WireGuard configuration file. "
            "Default: %(default)s"
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "Overwrite names already edited "
            "in the web panel."
        ),
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help=(
            "Only show detected IP/name pairs "
            "without changing the registry."
        ),
    )

    args = parser.parse_args()

    try:
        peers = load_wireguard_config_peers(
            args.config
        )
    except FileNotFoundError:
        print(
            f"Configuration not found: {args.config}",
            file=sys.stderr,
        )
        return 2
    except PermissionError:
        print(
            f"Permission denied: {args.config}",
            file=sys.stderr,
        )
        return 3

    print(
        f"WireGuard configuration: {args.config}"
    )
    print(f"Peers found: {len(peers)}")
    print()

    for peer in peers:
        print(
            f"{peer.ip:<15} "
            f"{peer.name or '<без имени>'}"
        )

    if args.list_only:
        print()
        print("Registry was not changed.")
        return 0

    result = sync_wireguard_client_names(
        config_file=args.config,
        overwrite=args.overwrite,
    )

    print()
    print(f"With names:          {result.with_names}")
    print(f"Updated:             {result.updated}")
    print(f"Preserved:           {result.preserved}")
    print(
        "Without name:        "
        f"{result.skipped_without_name}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
