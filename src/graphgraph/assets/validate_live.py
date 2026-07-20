from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _graphgraph_python() -> Path | None:
    """Find the interpreter that owns the installed GraphGraph launcher."""
    launcher_text = shutil.which("graphgraph")
    if not launcher_text:
        return None
    launcher = Path(launcher_text).resolve()
    candidates = (
        launcher.parent / "python.exe",
        launcher.parent / "python",
        launcher.parent.parent / "python.exe",
        launcher.parent.parent / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    try:
        first_line = launcher.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return None
    if first_line.startswith("#!"):
        candidate = Path(first_line[2:].strip().strip('"'))
        if candidate.is_file():
            return candidate
    return None


def _run() -> int:
    try:
        from graphgraph.acceptance.live_validation import main
    except ModuleNotFoundError as exc:
        if exc.name != "graphgraph":
            raise
        owning_python = _graphgraph_python()
        if owning_python is None:
            raise SystemExit(
                f"{sys.executable} cannot import graphgraph and no installed GraphGraph "
                "interpreter was found. Run this script with the Python environment "
                "that owns the `graphgraph` command."
            ) from exc
        return subprocess.call(
            [str(owning_python), "-m", "graphgraph.acceptance.live_validation", *sys.argv[1:]]
        )
    return main()

if __name__ == "__main__":
    raise SystemExit(_run())
