"""Project package discovery and bounded runtime probes."""

from __future__ import annotations

import os
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib


def _resolve_cargo_workspace_members(
    directory: Path,
    workspace: dict[str, object],
) -> list[str]:
    """Expand Cargo workspace member globs and apply excludes deterministically."""
    patterns = [
        str(pattern).replace("\\", "/").strip("/")
        for pattern in workspace.get("members", ())
        if str(pattern).strip()
    ]
    excludes = [
        str(pattern).replace("\\", "/").strip("/")
        for pattern in workspace.get("exclude", ())
        if str(pattern).strip()
    ]
    root = directory.resolve()
    members: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        try:
            candidates = (
                tuple(sorted(directory.glob(pattern), key=lambda path: path.as_posix()))
                if any(marker in pattern for marker in "*?[")
                else (directory / pattern,)
            )
        except (OSError, ValueError):
            continue
        for candidate in candidates:
            member_dir = candidate.parent if candidate.name == "Cargo.toml" else candidate
            if not (member_dir / "Cargo.toml").is_file():
                continue
            try:
                relative = member_dir.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            if any(
                relative == excluded or fnmatchcase(relative, excluded)
                for excluded in excludes
            ):
                continue
            normalized = relative or "."
            if normalized not in seen:
                members.append(normalized)
                seen.add(normalized)
    return members


def _read_package_status(directory: Path) -> dict[str, object]:
    pyproject = directory / "pyproject.toml"
    cargo_manifest = directory / "Cargo.toml"
    src_layout = (directory / "src").is_dir()
    package: dict[str, object] = {
        "ecosystem": "python" if pyproject.exists() else "",
        "ecosystems": ["python"] if pyproject.exists() else [],
        "pyproject": str(pyproject) if pyproject.exists() else "",
        "cargo_manifest": str(cargo_manifest) if cargo_manifest.exists() else "",
        "name": "",
        "version": "",
        "module": "",
        "scripts": {},
        "src_layout": src_layout,
        "import_hint": (
            "Set PYTHONPATH=src or install the package editable before direct "
            "python -m probes."
            if src_layout
            else ""
        ),
    }
    if cargo_manifest.exists():
        try:
            cargo = tomllib.loads(cargo_manifest.read_text(encoding="utf-8"))
            cargo_package = cargo.get("package") or {}
            workspace = cargo.get("workspace") or {}
            member_patterns = [str(member) for member in workspace.get("members", ())]
            rust = {
                "kind": "workspace" if workspace else "package",
                "name": str(cargo_package.get("name") or directory.name),
                "version": str(cargo_package.get("version") or ""),
                "members": _resolve_cargo_workspace_members(directory, workspace),
                "member_patterns": member_patterns,
                "exclude_patterns": [
                    str(member) for member in workspace.get("exclude", ())
                ],
            }
            package["rust"] = rust
            ecosystems = list(package["ecosystems"])
            ecosystems.append("rust")
            package["ecosystems"] = ecosystems
            package["ecosystem"] = "mixed" if pyproject.exists() else "rust"
            if not pyproject.exists():
                package["name"] = rust["name"]
                package["version"] = rust["version"]
        except Exception as exc:  # noqa: BLE001 - status reports parse failures.
            package["cargo_error"] = f"failed to parse Cargo.toml: {exc}"
    if not pyproject.exists():
        return package
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - status reports parse failures.
        package["error"] = f"failed to parse pyproject.toml: {exc}"
        return package

    project = data.get("project") or {}
    if isinstance(project, dict):
        name = str(project.get("name") or "")
        package["name"] = name
        package["version"] = str(project.get("version") or "")
        package["module"] = name.replace("-", "_") if name else ""
        scripts = project.get("scripts") or {}
        if isinstance(scripts, dict):
            package["scripts"] = {str(key): str(value) for key, value in scripts.items()}
    return package


def _run_package_probes(
    directory: Path, package: dict[str, object]
) -> list[dict[str, object]]:
    module = str(package.get("module") or "")
    if not module:
        return []

    probes: list[dict[str, object]] = []
    commands = (
        ("module_help", [sys.executable, "-m", module, "--help"]),
        ("import", [sys.executable, "-c", f"import {module}; print({module}.__file__)"]),
    )
    raw_env = os.environ.copy()
    raw_env.pop("PYTHONPATH", None)
    for name, args in commands:
        probes.append(
            _run_probe(
                name=f"raw_{name}",
                args=args,
                directory=directory,
                env=raw_env,
                env_label="raw",
            )
        )

    if package.get("src_layout"):
        src_env = os.environ.copy()
        src_path = str(directory / "src")
        existing = src_env.get("PYTHONPATH")
        src_env["PYTHONPATH"] = (
            src_path if not existing else src_path + os.pathsep + existing
        )
        for name, args in commands:
            probes.append(
                _run_probe(
                    name=f"src_{name}",
                    args=args,
                    directory=directory,
                    env=src_env,
                    env_label="PYTHONPATH=src",
                )
            )

    scripts = package.get("scripts") or {}
    if isinstance(scripts, dict):
        env = os.environ.copy()
        if package.get("src_layout"):
            env["PYTHONPATH"] = str(directory / "src")
        for script_name, target in sorted(scripts.items()):
            module_name = str(target).split(":", 1)[0].strip()
            if not module_name:
                continue
            probes.append(
                _run_probe(
                    name=f"script_target_import:{script_name}",
                    args=[
                        sys.executable,
                        "-c",
                        f"import {module_name}; print({module_name}.__file__)",
                    ],
                    directory=directory,
                    env=env,
                    env_label=(
                        "PYTHONPATH=src" if package.get("src_layout") else "raw"
                    ),
                )
            )
    return probes


def _run_probe(
    *,
    name: str,
    args: list[str],
    directory: Path,
    env: dict[str, str],
    env_label: str,
) -> dict[str, object]:
    try:
        proc = subprocess.run(
            args,
            cwd=directory,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
        output = (proc.stdout or "").strip().splitlines()
        return {
            "name": name,
            "env": env_label,
            "command": " ".join(args),
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "output": output[:5],
        }
    except Exception as exc:  # noqa: BLE001 - probes report execution failures.
        return {
            "name": name,
            "env": env_label,
            "command": " ".join(args),
            "ok": False,
            "error": str(exc),
        }


def _runtime_notes(probes: list[dict[str, object]]) -> list[str]:
    by_name = {str(probe.get("name")): probe for probe in probes}
    notes: list[str] = []
    raw_import = by_name.get("raw_import")
    src_import = by_name.get("src_import")
    if raw_import and src_import and not raw_import.get("ok") and src_import.get("ok"):
        notes.append(
            "Package imports only when PYTHONPATH includes src; install editable "
            "or export PYTHONPATH=src."
        )
    raw_module = by_name.get("raw_module_help")
    src_module = by_name.get("src_module_help")
    if raw_module and src_module and not raw_module.get("ok") and src_module.get("ok"):
        notes.append("python -m module works only with src on PYTHONPATH.")
    for probe in probes:
        name = str(probe.get("name") or "")
        if name.startswith("script_target_import:") and not probe.get("ok"):
            notes.append(f"Console script target import failed: {name.split(':', 1)[1]}.")
    return notes


__all__ = [
    "_read_package_status",
    "_resolve_cargo_workspace_members",
    "_run_package_probes",
    "_run_probe",
    "_runtime_notes",
]
