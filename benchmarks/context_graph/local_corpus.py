"""Shared local-repo corpus definitions for real-project benchmarks.

Reuses the same on-disk projects already scanned by
``cross_repo_anchor_stress.py`` (``DEFAULT_PROJECT_PATHS`` / ``LOCAL_PROJECT_PATHS``
/ ``RESOURCES_ROOT``) so the storage backend bake-off and snippet-usefulness
benchmark share one corpus instead of each hardcoding project lists. No
network access or cloning is needed: every path here is already checked out
locally under ``C:\\Users\\dcarn\\aiprojects``.

Tiers are sized by source-file count (see repo audit in the session that
added this file) so the "large" tier can be scanned with an explicit node cap
without the whole bake-off stalling on multi-thousand-file math libraries.
"""

from __future__ import annotations

from pathlib import Path

AIPROJECTS_ROOT = Path(r"C:\Users\dcarn\aiprojects")
RESOURCES_ROOT = AIPROJECTS_ROOT / "resources"

# Own projects: small/medium, fast to scan, no cap needed.
OWN_PROJECT_NAMES: tuple[str, ...] = (
    "graphgraph",
    "contextminer",
    "chess",
    "slotmachine",
    "locus",
    "gamemechanic",
)

# resources/*: small/medium tier (roughly <2500 source files), no cap needed.
#
# crewAI is deliberately excluded: it's a ~20k-file monorepo (multiple nested
# packages plus several fully-duplicated versioned doc snapshots under
# docs/v1.x.x/) containing 30k-40k-line generated JSON "doc" files
# (docs/docs.json, lib/crewai-tools/tool.specs.json). With docs=True the doc
# extraction path spent 10+ minutes on it without finishing, wildly out of
# line with every other repo of comparable raw file count -- a real scanner
# perf edge case on pathological doc dumps, but out of scope for the storage
# backend bake-off this corpus feeds. Revisit if scanner doc-extraction gets
# a size guard.
RESOURCES_SMALL_MEDIUM_NAMES: tuple[str, ...] = (
    "requests",
    "flask",
    "regex",
    "express",
    "graphify",
    "langgraph",
    "redis",
    "sympy",
    "z3",
    "lean",
)

# resources/*: large tier (multi-thousand source files) - always scan these
# with an explicit --scan-max-nodes / max_nodes cap.
RESOURCES_LARGE_NAMES: tuple[str, ...] = (
    "mathlib4",
    "lean4",
)

DEFAULT_LARGE_TIER_MAX_NODES = 12000


def _existing(root: Path, names: tuple[str, ...]) -> list[Path]:
    return [root / name for name in names if (root / name).exists()]


def own_project_paths() -> list[Path]:
    return _existing(AIPROJECTS_ROOT, OWN_PROJECT_NAMES)


def small_medium_resource_paths() -> list[Path]:
    return _existing(RESOURCES_ROOT, RESOURCES_SMALL_MEDIUM_NAMES)


def large_resource_paths() -> list[Path]:
    return _existing(RESOURCES_ROOT, RESOURCES_LARGE_NAMES)


def small_medium_paths() -> list[Path]:
    """Own projects + small/medium resources: the fast, uncapped tier."""
    return own_project_paths() + small_medium_resource_paths()


def all_tiered_paths() -> list[tuple[Path, str]]:
    """Every corpus path paired with its tier name ('small_medium' or 'large')."""
    tiered = [(p, "small_medium") for p in small_medium_paths()]
    tiered += [(p, "large") for p in large_resource_paths()]
    return tiered
