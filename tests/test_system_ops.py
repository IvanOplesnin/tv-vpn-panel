from __future__ import annotations

from subprocess import CompletedProcess
from types import SimpleNamespace


def test_dry_run_skips_mutating_network_commands(monkeypatch):
    from tv_vpn_panel import system_ops

    calls: list[list[str]] = []
    monkeypatch.setattr(
        system_ops,
        "settings",
        SimpleNamespace(
            dry_run=True,
            table_id="200",
            allow_backend_refresh=True,
            backend_switch_script="/usr/local/sbin/vpn-backend-switch.sh",
        ),
    )
    monkeypatch.setattr(
        system_ops,
        "run_cmd",
        lambda cmd, **kwargs: calls.append(cmd) or CompletedProcess(cmd, 0, "", ""),
    )

    system_ops.enable_vpn_rule("192.168.50.10")
    system_ops.disable_vpn_rule("192.168.50.10")
    ok, message = system_ops.refresh_backend_route()

    assert calls == []
    assert ok is True
    assert "dry run" in message


def test_backend_state_detects_sing_box(monkeypatch):
    from tv_vpn_panel import system_ops

    monkeypatch.setattr(system_ops, "route_table_text", lambda: "default dev sbtun0 scope link")
    monkeypatch.setattr(system_ops, "settings", SimpleNamespace(table_id="200"))

    state = system_ops.get_backend_state()

    assert state.active == "sing-box"
    assert state.ok is True
    assert state.table_has_default is True
    assert state.default_route == "default dev sbtun0 scope link"
