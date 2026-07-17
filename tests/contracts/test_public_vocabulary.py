from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_active_tree_has_no_removed_vocabulary() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_public_vocabulary.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
