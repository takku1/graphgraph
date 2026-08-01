"""Deterministic document-authority signal for retrieval ranking.

Retrieval should prefer *current* operational and architecture docs over dated
findings and exploratory research when both mention a term (graybox T10). This
derives an authority tier for each doc from the one place that already
classifies them -- the ``docs/README.md`` index (T09) -- so there is a single
source of truth: a doc's section in the map *is* its authority.

The signal is deterministic and self-contained: it computes a tier and a
recency key from paths and the README, with no dependency on retrieval. A
caller wires ``authority_rank`` + ``document_recency`` into ranking as a
tiebreaker; this module only decides the ordering, not how it is applied.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

# Ordered most- to least-authoritative. `current` = how the tool works now;
# `historical` = superseded but preserved measurements; `notes` = scratch.
AUTHORITY_TIERS = ("current", "reference", "research", "historical", "notes", "generated")
_TIER_RANK = {tier: len(AUTHORITY_TIERS) - index for index, tier in enumerate(AUTHORITY_TIERS)}

# Keyword in a README `## ` section title -> tier. First match wins, so order
# matters only where titles could overlap (none do today).
_SECTION_TIER = (
    ("operational", "current"),
    ("architecture", "current"),
    ("findings", "historical"),
    ("comparison", "reference"),
    ("research", "research"),
)

_MD_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)#]+\.md)")
_DATE_PREFIX = re.compile(r"(\d{4}-\d{2}-\d{2})")
_CYCLE = re.compile(r"cycle[-_ ]?(\d+)", re.IGNORECASE)


def _section_tier(title: str) -> str | None:
    lowered = title.casefold()
    for keyword, tier in _SECTION_TIER:
        if keyword in lowered:
            return tier
    return None


def parse_authority_map(readme_text: str) -> dict[str, str]:
    """Map each README-linked doc (relative to docs/) to its section's tier."""
    mapping: dict[str, str] = {}
    tier: str | None = None
    for line in readme_text.splitlines():
        header = re.match(r"^##\s+(.*)$", line)
        if header:
            tier = _section_tier(header.group(1))
            continue
        if tier is None:
            continue
        for target in _MD_LINK.findall(line):
            mapping.setdefault(target.strip().replace("\\", "/"), tier)
    return mapping


@lru_cache(maxsize=8)
def _repo_authority_map(readme_path: str) -> tuple[tuple[str, str], ...]:
    try:
        text = Path(readme_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()  # absent or unreadable index: every doc falls back to "current"
    return tuple(parse_authority_map(text).items())


@lru_cache(maxsize=8)
def _authority_lookup(readme_path: str) -> dict[str, str]:
    """Read-only tier lookup, built once per index rather than per query node.

    `document_authority` is a per-node tiebreaker, so it runs once for every
    docs node in a search. Resolving the default path and testing it for
    existence on each of those calls put ~930 filesystem syscalls in front of a
    single query: the expensive read was cached, but the guard around it was
    not. Both are now hoisted, leaving this a dict lookup.
    """
    return dict(_repo_authority_map(readme_path))


@lru_cache(maxsize=1)
def _default_docs_readme() -> str:
    return str(Path(__file__).resolve().parents[3] / "docs" / "README.md")


def document_authority(rel_path: str, *, docs_readme: Path | None = None) -> str:
    """Authority tier of a doc, addressed relative to the docs/ directory.

    ``notes/`` is always scratch. Otherwise the tier comes from the README
    section that links the doc; an indexed-but-unclassified doc defaults to
    ``current`` (it is reachable, so it is at least live reference).
    """
    normalized = rel_path.replace("\\", "/").lstrip("./")
    first = normalized.split("/", 1)[0]
    if first == "notes":
        return "notes"
    readme = str(docs_readme) if docs_readme is not None else _default_docs_readme()
    return _authority_lookup(readme).get(normalized, "current")


def authority_rank(tier: str) -> int:
    """Higher = more authoritative. Unknown tiers rank below every known tier."""
    return _TIER_RANK.get(tier, 0)


def document_recency(rel_path: str) -> tuple[str, int]:
    """A sort key preferring newer dated docs, then higher cycle numbers.

    ``findings/2026-07-22-graybox-cycle3-*`` -> (``2026-07-22``, 3). Undated docs
    sort as the empty date, so recency only ever *breaks ties* between dated
    peers (for example, later gray-box cycles over earlier ones).
    """
    name = rel_path.replace("\\", "/").rsplit("/", 1)[-1]
    date_match = _DATE_PREFIX.search(name)
    cycle_match = _CYCLE.search(name)
    return (date_match.group(1) if date_match else "", int(cycle_match.group(1)) if cycle_match else 0)


def authority_sort_key(rel_path: str, *, docs_readme: Path | None = None) -> tuple[int, str, int]:
    """Descending-authority sort key: (tier rank, date, cycle), higher first."""
    tier = document_authority(rel_path, docs_readme=docs_readme)
    date, cycle = document_recency(rel_path)
    return (authority_rank(tier), date, cycle)
