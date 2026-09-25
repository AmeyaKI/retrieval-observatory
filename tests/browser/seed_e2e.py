"""Seed the two databases the browser suite reads, model-free.

    python tests/browser/seed_e2e.py DIR [--port 4100]

1. ``retobs demo`` writes the baseline and validation runs plus ``demo_manifest.json`` into
   ``DIR/demo`` (DB ``DIR/demo/demo.db``; it holds no integration, so Connect shows its guided steps).
2. The plain-Python fixture project (``proj_a``) is copied to ``DIR/project`` and wired through the
   real CLI: ``retobs integrate --phase plan``, ``--phase apply``, the plan's scenario commands,
   ``--phase verify``, then the plan's benchmark command so the record links a first investigation.
   The verified record lands in ``DIR/project/.retobs/results.db``.

Prints the ``retobs serve`` command that serves both databases (the demo database first).

With ``RETOBS_REQUIRE_INSTALLED=1`` (the release workflow sets it when seeding from the built wheel)
the script fails unless ``retrieval_observatory`` imports from this interpreter's environment
(``sys.prefix``) rather than a source checkout, so checkout imports cannot mask packaging defects.
Leave it unset for developer use with an editable install.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "fixtures"))
from integration_projects import materialize  # noqa: E402

PLAN = "retobs/integration-plan.json"


def _run(argv: list[str], cwd: Path) -> str:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0:
        raise SystemExit(f"`{shlex.join(argv)}` failed in {cwd}:\n{completed.stderr[-3000:]}")
    return completed.stdout


def _retobs(*args: str) -> list[str]:
    return [sys.executable, "-m", "retrieval_observatory.cli", *args]


def _command(command: str) -> list[str]:
    """A plan command (`python …` or `retobs …`) run with this interpreter."""
    argv = shlex.split(command)
    if argv[0] == "python":
        return [sys.executable, *argv[1:]]
    if argv[0] == "retobs":
        return _retobs(*argv[1:])
    raise SystemExit(f"unexpected plan command: {command}")


def _require_installed_import(cwd: Path) -> None:
    """Assert the seeding subprocesses import the installed package, probed with their own form and cwd."""
    if os.environ.get("RETOBS_REQUIRE_INSTALLED") != "1":
        return
    probe = "import retrieval_observatory, sys; print(retrieval_observatory.__file__); print(sys.prefix)"
    module_file, prefix = (Path(line).resolve() for line in _run([sys.executable, "-c", probe], cwd=cwd).splitlines())
    if prefix not in module_file.parents:
        raise SystemExit(f"RETOBS_REQUIRE_INSTALLED=1 but retrieval_observatory imports from {module_file}, outside {prefix}")


def seed(directory: Path) -> tuple[Path, Path]:
    directory = directory.resolve()
    demo_dir, project = directory / "demo", directory / "project"
    for path in (demo_dir, project):
        if path.exists():
            shutil.rmtree(path)
    directory.mkdir(parents=True, exist_ok=True)
    # `python -m` puts the cwd on sys.path, so no seeding subprocess runs from the checkout.
    _require_installed_import(directory)

    demo_db = demo_dir / "demo.db"
    _run(_retobs("demo", "--output-dir", str(demo_dir), "--db", str(demo_db)), cwd=directory)

    shutil.move(str(materialize("proj_a", directory / "_fixture")), project)
    shutil.rmtree(directory / "_fixture")
    _run(_retobs("integrate", str(project), "--phase", "plan", "--output", PLAN), cwd=project)
    _run(_retobs("integrate", str(project), "--phase", "apply", "--plan", PLAN), cwd=project)
    plan = json.loads((project / PLAN).read_text(encoding="utf-8"))["plan"]
    for scenario in plan["scenarios"]:
        _run(_command(scenario["command"]), cwd=project)
    verified = json.loads(_run(_retobs("integrate", str(project), "--phase", "verify", "--plan", PLAN), cwd=project))
    if verified["status"] != "ready":
        raise SystemExit(f"integration verify is {verified['status']}: {verified['errors']}")
    benchmark = next(action for action in plan["actions"] if action["kind"] == "benchmark_setup")
    _run(_command(benchmark["command"]), cwd=project)
    return demo_db, project / ".retobs" / "results.db"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--port", type=int, default=4100)
    args = parser.parse_args()
    demo_db, project_db = seed(args.directory)
    print(f"retobs serve --db {demo_db},{project_db} --port {args.port}")
    print(f"RETOBS_E2E_URL=http://127.0.0.1:{args.port} python -m pytest tests/browser -q")


if __name__ == "__main__":
    main()
