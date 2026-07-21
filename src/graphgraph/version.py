from __future__ import annotations


def package_version() -> str:
    # Imported lazily: importlib.metadata drags in email, zipfile and csv,
    # which cost ~27ms at interpreter start. Every CLI invocation imports
    # this module for `--version`, but almost none of them call it.
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("graphgraph")
    except PackageNotFoundError:
        return "0.1.0+source"
