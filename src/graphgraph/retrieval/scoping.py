"""Query normalization, scope filters, and test-node detection shared across retrieval."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..graph.core import Graph
from ..planning.budgets import plan_terms

_NOISE_PATTERNS = [
    re.compile(r"```[\s\S]*?```"),                          # markdown code blocks
    re.compile(r"Sender\s*\(untrusted metadata\)\s*:\s*", re.IGNORECASE),  # untrusted sender prefix
    re.compile(r"\[[\w\s:\-]+UTC\]\s*", re.IGNORECASE),     # timestamp logs
]

def sanitize_query(query: str) -> str:
    """Strip upstream system noise and logs to preserve pure query search intent."""
    text = query or ""
    for pat in _NOISE_PATTERNS:
        text = pat.sub("", text)
    return text.strip()

_AFFECTED_ANCHOR_INTENT = re.compile(
    r"\b(?:if|affected|affecting|impact|impacted|changes?|changed|changing|"
    r"which|what|tests?|should|runs?|running|cover|covers|covered|exercise|"
    r"validate|validates|directly|cases?|do|does|they|them|their|exact|cargo|"
    r"commands?|smallest|every|all|one)\b",
    re.I,
)

def structural_anchor_query(query: str, query_class: str) -> str:
    """Remove planner vocabulary that can collide with unrelated symbols."""
    if query_class != "affected_tests":
        return query
    cleaned = _AFFECTED_ANCHOR_INTENT.sub(" ", query)
    return " ".join(plan_terms(cleaned)) or query

STRUCTURAL_QUERY_CLASSES = {"blast_radius", "multi_hop_path", "reverse_lookup", "affected_tests"}

SESSION_CONTEXT_QUERY_CLASSES = {"subsystem_summary", "spreading_activation"}

NON_STRUCTURAL_KINDS = {"concept", "section", "paragraph", "markdown", "rst", "html", "text"}

STRUCTURAL_RELATIONS = {
    "calls", "imports", "imports_from", "reads", "writes", "uses", "implements",
    "tests", "configures", "returns", "defines", "data_flow", "control_flow",
    "formalizes", "implements_algorithm", "uses_semantic_operator", "performs_semantic_operation",
}

_ORDERED_DOC_QUERY = re.compile(
    r"\b(before|after|next|previous|prior|ordered|phase|phases|stage|stages|"
    r"step|steps|sequence|roadmap|backlog|milestone)\b",
    re.I,
)

_ENUMERATED_DOC_QUERY = re.compile(r"\b(stage|stages|phase|phases|step|steps|sequence)\b", re.I)

_FLOW_ORIENTATION_QUERY = re.compile(
    r"\b(flow|flows|path|pipeline|call chain|data flow|control flow)\b",
    re.I,
)

_TEST_EVIDENCE_QUERY = re.compile(
    r"\b(?:tests?|test\s+coverage|covered\s+by)\b",
    re.I,
)

def _path_in_scopes(path: str, scopes: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    return any(
        normalized == scope.replace("\\", "/").strip("/")
        or normalized.startswith(scope.replace("\\", "/").strip("/") + "/")
        for scope in scopes
    )

def _explicit_document_paths(graph: Graph, query: str) -> tuple[str, ...]:
    """Resolve graph-known document paths embedded in natural-language input."""
    normalized_query = query.replace("\\", "/").casefold()
    return tuple(sorted({
        node.path.replace("\\", "/").strip("/")
        for node in graph.nodes.values()
        if node.active
        and node.path
        and Path(node.path).suffix.casefold() in {".md", ".mdx", ".rst", ".txt", ".html", ".htm"}
        and node.path.replace("\\", "/").strip("/").casefold() in normalized_query
    }))

def _package_scope(path: str) -> str:
    parts = path.replace("\\", "/").strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"crates", "packages", "apps", "libs", "modules"}:
        return "/".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "src":
        return "/".join(parts[:2]) if len(parts) >= 3 else "src"
    return "/".join(parts[:-1]) if len(parts) > 1 else ""

def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/").casefold()
    name = normalized.rsplit("/", 1)[-1]
    return "/tests/" in f"/{normalized}" or name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".spec.ts"))

def _is_test_node(node: object) -> bool:
    facts = {
        str(fact).casefold()
        for fact in (getattr(node, "facts", ()) or ())
    }
    if facts & {"role:test", "rust_attribute:test"}:
        return True
    if _is_test_path(str(getattr(node, "path", ""))) and str(
        getattr(node, "kind", "")
    ) in {"function", "method"}:
        return True
    source = str(getattr(node, "source", ""))
    line = getattr(node, "line", None)
    return bool(
        source
        and isinstance(line, int)
        and _source_declares_rust_test(source, line)
    )

@lru_cache(maxsize=8192)
def _source_declares_rust_test(source: str, line: int) -> bool:
    """Recover inline-test identity for graphs built before test-role IR facts."""
    path = Path(source)
    if path.suffix.casefold() != ".rs" or not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    start = max(0, line - 5)
    end = min(len(lines), line + 1)
    declaration_prefix = "\n".join(lines[start:end])
    return bool(re.search(
        r"#\s*\[\s*(?:tokio::)?test(?:\s*\([^]]*\))?\s*\]",
        declaration_prefix,
    ))

def _qualified_query_symbols(query: str) -> tuple[tuple[str, str], ...]:
    return tuple(dict.fromkeys(
        (owner, member)
        for owner, member in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)\b", query)
    ))
