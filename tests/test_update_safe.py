from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update-safe.sh"


def test_safe_updater_runs_candidate_checks_from_release_dir():
    script = SCRIPT.read_text(encoding="utf-8")

    assert '"${BUILD_DIR}/tests"' not in script
    assert script.count('cd "$BUILD_DIR"') >= 2
    assert "-m pytest" in script
    assert "\n            tests\n" in script
    assert "exec env" in script
    assert "for table in 200 201 202 203" in script
    assert "nft list set inet vpn_policy ru4_dst" in script
    assert "Panel restart changed selector table" in script


def test_browser_templates_do_not_put_token_in_urls():
    index = (ROOT / "tv_vpn_panel" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    wireguard = (
        ROOT / "tv_vpn_panel" / "templates" / "wireguard.html"
    ).read_text(encoding="utf-8")

    assert "?token=" not in index
    assert "?token=" not in wireguard
    assert "X-API-Token" in index
    assert "X-API-Token" in wireguard
