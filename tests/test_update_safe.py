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
