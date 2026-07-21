"""Compatibility target for the ``graphgraph-mcp`` console script.

The canonical entry point is ``graphgraph.mcp:main`` (see ``[project.scripts]``
in ``pyproject.toml``). Console-script launchers generated *before* that rename
embed ``from graphgraph.mcp_server import main``, so this module must keep
existing until every environment that installed graphgraph has been
reinstalled -- otherwise `graphgraph-mcp` fails with ``ModuleNotFoundError``.

Known consumers of the old path: the project ``.mcp.json`` resolves
``graphgraph-mcp`` out of ``.venv/Scripts``, which cannot be regenerated while
a graphgraph process is running (Windows holds the launcher open).

Safe to delete once `uv sync` / `pip install -e .` has been re-run in every
environment listed by `uv tool list` and on PATH.
"""

from .mcp import dispatch, main

__all__ = ["dispatch", "main"]
