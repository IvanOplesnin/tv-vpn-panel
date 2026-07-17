from __future__ import annotations

import subprocess
from types import SimpleNamespace


def completed(
    args: list[str],
    stdout: str = "",
    stderr: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_wireguard_status_parses_peers(monkeypatch):
    from tv_vpn_panel import wireguard_status

    now = 1_700_000_000

    dump = (
        "server-private\tserver-public\t51820\toff\n"
        "peer-key-one\t(none)\t198.51.100.10:50000\t"
        "10.10.0.5/32\t1699999970\t1000\t2000\t25\n"
        "peer-key-two\t(none)\t(none)\t"
        "10.10.0.6/32\t0\t3000\t4000\t0\n"
    )

    def fake_safe_run(cmd: list[str], timeout: float = 5.0):
        if cmd[:4] == ["wg", "show", "wg0", "dump"]:
            return completed(cmd, stdout=dump)

        if cmd[:3] == ["ip", "route", "get"]:
            client_ip = cmd[cmd.index("from") + 1]

            return completed(
                cmd,
                stdout=(
                    f"8.8.8.8 from {client_ip} "
                    "via 10.8.0.1 dev tun0 table 200\n"
                ),
            )

        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(wireguard_status.time, "time", lambda: now)
    monkeypatch.setattr(wireguard_status, "safe_run", fake_safe_run)
    monkeypatch.setattr(
        wireguard_status,
        "settings",
        SimpleNamespace(route_test_ip="8.8.8.8"),
    )
    monkeypatch.setattr(
        wireguard_status,
        "load_wireguard_profiles",
        lambda: [],
    )

    response = wireguard_status.get_wireguard_status()

    assert response.ok is True
    assert len(response.peers) == 2

    first = response.peers[0]

    assert first.ip == "10.10.0.5"
    assert first.status == "online"
    assert first.latest_handshake_age_seconds == 30
    assert first.transfer_rx_bytes == 1000
    assert first.transfer_tx_bytes == 2000
    assert first.persistent_keepalive_seconds == 25
    assert first.route_probe_ok is True
    assert "dev tun0 table 200" in (first.route_probe or "")

    second = response.peers[1]

    assert second.ip == "10.10.0.6"
    assert second.status == "never"
    assert second.latest_handshake_age_seconds is None


def test_wireguard_status_handles_command_error(monkeypatch):
    from tv_vpn_panel import wireguard_status

    monkeypatch.setattr(
        wireguard_status,
        "safe_run",
        lambda cmd, timeout=5.0: completed(
            cmd,
            stderr="Operation not permitted",
            returncode=1,
        ),
    )

    response = wireguard_status.get_wireguard_status()

    assert response.ok is False
    assert response.peers == []
    assert response.error == "Operation not permitted"
