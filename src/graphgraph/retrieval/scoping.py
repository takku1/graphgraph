"""Query normalization, scope filters, and test-node detection shared across retrieval."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ..graph.core import Graph
from ..planning.budgets import plan_terms

_NOISE_PATTERNS = [
    re.compile(r"```[\s\S]*?```"),  # markdown code blocks
    re.compile(r"Sender\s*\(untrusted metadata\)\s*:\s*", re.IGNORECASE),  # untrusted sender prefix
    re.compile(r"\[[\w\s:\-]+UTC\]\s*", re.IGNORECASE),  # timestamp logs
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

# Kinds a test runner can execute. A node on a test path only becomes a test
# case if it is one of these; file, field, and local nodes are not.
TEST_CASE_KINDS = {"function", "method"}

STRUCTURAL_RELATIONS = {
    "calls",
    "imports",
    "imports_from",
    "reads",
    "writes",
    "uses",
    "implements",
    "tests",
    "configures",
    "returns",
    "defines",
    "data_flow",
    "control_flow",
    "formalizes",
    "implements_algorithm",
    "uses_semantic_operator",
    "performs_semantic_operation",
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
    return tuple(
        sorted(
            {
                node.path.replace("\\", "/").strip("/")
                for node in graph.nodes.values()
                if node.active
                and node.path
                and Path(node.path).suffix.casefold() in {".md", ".mdx", ".rst", ".txt", ".html", ".htm"}
                and node.path.replace("\\", "/").strip("/").casefold() in normalized_query
            }
        )
    )


def _package_scope(path: str) -> str:
    parts = path.replace("\\", "/").strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"crates", "packages", "apps", "libs", "modules"}:
        return "/".join(parts[:2])
    if len(parts) >= 2 and parts[0] == "src":
        return "/".join(parts[:2]) if len(parts) >= 3 else "src"
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


@lru_cache(maxsize=16384)
def _is_test_path(path: str) -> bool:
    """Identify test files without promoting production modules by name alone.

    Memoized: a pure function of the path string, and retrieval asks it about
    the same paths repeatedly -- one warm query issued 28,962 calls.
    """
    normalized = path.replace("\\", "/").strip("/").casefold()
    parts = tuple(part for part in normalized.split("/") if part)
    if not parts:
        return False
    directories, name = parts[:-1], parts[-1]
    if set(directories) & {"test", "tests", "__tests__"}:
        return True
    if name.endswith(".cs") and (
        any(part.endswith((".test", ".tests")) for part in directories)
        or name.endswith(("test.cs", "tests.cs"))
    ):
        return True
    if re.search(
        r"\.(?:test|spec)\.(?:py|js|jsx|ts|tsx|mjs|cjs)$",
        name,
    ) or name.endswith(("_test.go", "_spec.rb")):
        return True
    # Python permits root-level test_*.py and *_test.py files. Inside `src/`,
    # however, that spelling is also a legitimate production module name
    # (for example retrieval/test_recommendations.py), so require stronger
    # structural evidence there.
    python_convention = name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))
    return python_convention and "src" not in directories


def _is_test_material(node: object) -> bool:
    """True for anything that lives in test code: files, fields, locals, cases.

    This is the breadth a *production* query needs. Test material should not
    anchor or outrank production code when the question is about production
    behavior, and that applies to the test file node itself just as much as to
    the cases inside it.
    """
    facts = {str(fact).casefold() for fact in (getattr(node, "facts", ()) or ())}
    if facts & {"role:test", "rust_attribute:test"}:
        return True
    parent = str(getattr(node, "parent", ""))
    owner = parent.rsplit("__", 1)[-1]
    if owner.endswith(("Test", "Tests", "Spec", "Specs")):
        return str(getattr(node, "kind", "")) in TEST_CASE_KINDS
    path = str(getattr(node, "path", ""))
    kind = str(getattr(node, "kind", ""))
    if _is_test_path(path) and kind not in NON_STRUCTURAL_KINDS:
        return True
    source = str(getattr(node, "source", ""))
    line = getattr(node, "line", None)
    return bool(source and isinstance(line, int) and _source_declares_rust_test(source, line))


def _is_test_node(node: object) -> bool:
    """True only for an executable test case.

    Narrower than :func:`_is_test_material` on purpose. A test *file* node, and
    the fields and locals declared inside it, share the path but are not
    independently runnable; counting them as test cases inflates affected-test
    evidence with things no runner can execute.
    """
    if not _is_test_material(node):
        return False
    if str(getattr(node, "kind", "")) in TEST_CASE_KINDS:
        return True
    # Scanner-marked test facts identify a case even when the node kind is
    # language-specific rather than `function`/`method`.
    facts = {str(fact).casefold() for fact in (getattr(node, "facts", ()) or ())}
    return bool(facts & {"role:test", "rust_attribute:test"})


def _is_runnable_test_node(node: object) -> bool:
    """Return whether a test-evidence node is independently executable."""
    if not _is_test_node(node):
        return False
    facts = {str(fact).casefold() for fact in (getattr(node, "facts", ()) or ())}
    if facts & {"role:test", "rust_attribute:test"}:
        return True
    path = str(getattr(node, "path", "")).replace("\\", "/").casefold()
    if path.endswith(".py"):
        # Test modules also contain fixtures, decorators, and nested helpers.
        # Pytest's default runnable function/method contract is ``test*``;
        # explicit scanner facts above remain authoritative for custom schemes.
        return str(getattr(node, "label", "")).casefold().startswith("test")
    return True


@lru_cache(maxsize=512)
def _rust_source_lines(source: str) -> tuple[str, ...]:
    """Read one Rust source once, memoized by path.

    ``_source_declares_rust_test`` is keyed on (source, line) because each
    symbol asks about its own line, so a file containing 40 test functions
    produced 40 distinct cache keys and 40 re-reads of the same file. Caching
    the read separately collapses those to one.
    """
    path = Path(source)
    if path.suffix.casefold() != ".rs" or not path.is_file():
        return ()
    try:
        return tuple(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return ()


# Keyed per symbol, so the working set is the Rust symbol count rather than a
# fixed quantity; entries are one bool. `_rust_source_lines` above is left small
# on purpose -- it holds whole file contents, so its bound is a memory ceiling.
@lru_cache(maxsize=131072)
def _source_declares_rust_test(source: str, line: int) -> bool:
    """Recover inline-test identity for graphs built before test-role IR facts."""
    lines = _rust_source_lines(source)
    if not lines:
        return False
    start = max(0, line - 5)
    end = min(len(lines), line + 1)
    declaration_prefix = "\n".join(lines[start:end])
    return bool(
        re.search(
            r"#\s*\[\s*(?:tokio::)?test(?:\s*\([^]]*\))?\s*\]",
            declaration_prefix,
        )
    )


def _qualified_query_symbols(query: str) -> tuple[tuple[str, str], ...]:
    pairs = re.findall(
        r"\b([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)\b",
        query,
    )
    # JavaScript/TypeScript/Python use dot-qualified identities (`res.send`)
    # where Rust/C++ use `Type::member`. A same-stem file such as
    # `test/res.send.js` must not outrank the actual callable definition.
    pairs.extend(
        re.findall(
            r"\b([A-Za-z_$][A-Za-z0-9_$]*)\.([A-Za-z_$][A-Za-z0-9_$]*)\b",
            query,
        )
    )
    return tuple(dict.fromkeys(pairs))
