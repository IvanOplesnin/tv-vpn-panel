from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts"
    / "wireguard-client-routing.sh"
)


def run_script(
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "TVVPN_WG_ROUTING_DRY_RUN": "true",
            "TVVPN_PROTECTED_WG_CLIENT": "10.10.0.5",
            "TVVPN_TEST_TUN0_READY": "false",
            "TVVPN_TEST_SBTUN0_READY": "false",
        }
    )

    return subprocess.run(
        ["bash", str(SCRIPT), *arguments],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


def test_direct_mode_uses_main_table():
    result = run_script(
        "set",
        "10.10.0.7",
        "direct",
    )

    assert result.returncode == 0, result.stderr

    assert (
        "ip -4 rule add from "
        "10.10.0.7/32 lookup main "
        "priority 31007"
        in result.stdout
    )

    assert (
        "ip -4 route flush table 201"
        in result.stdout
    )

    assert (
        "ip -4 route flush table 202"
        in result.stdout
    )

    # Автоматическая table 200 не должна
    # очищаться или перестраиваться.
    assert (
        "route flush table 200"
        not in result.stdout
    )

    assert "-o eth0" in result.stdout
    assert "-o tun0" in result.stdout
    assert "-o sbtun0" in result.stdout


def test_pinned_vpn_modes_use_dedicated_tables():
    cases = (
        ("openvpn", "201"),
        ("vless", "202"),
    )

    for mode, table in cases:
        result = run_script(
            "set",
            "10.10.0.7",
            mode,
        )

        assert result.returncode == 0, (
            mode,
            result.stderr,
        )

        expected = (
            "ip -4 rule add from "
            f"10.10.0.7/32 lookup {table} "
            "priority 31007"
        )

        assert expected in result.stdout


def test_protected_client_cannot_be_switched():
    result = run_script(
        "set",
        "10.10.0.5",
        "direct",
    )

    assert result.returncode != 0

    assert (
        "Protected WireGuard client "
        "10.10.0.5 can only use auto mode"
        in result.stderr
    )

    # Защита срабатывает до любых изменений.
    assert "route flush" not in result.stdout
    assert "iptables" not in result.stdout
