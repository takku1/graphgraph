from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    try:
        return version("graphgraph")
    except PackageNotFoundError:
        return "0.1.0+source"
