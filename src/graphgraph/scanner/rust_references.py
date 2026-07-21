"""Soundness gates for Rust reference edges."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility.
    import tomli as tomllib

from ..graph.core import Edge, Node

_TYPE_REFERENCE_PROVENANCE = "tree_sitter_type_reference"
_DEPENDENCY_SECTIONS = ("dependencies", "dev-dependencies", "build-dependencies")
_RUST_TYPE_PATH = r"(?:[A-Za-z_][A-Za-z0-9_]*::)*([A-Z][A-Za-z0-9_]*)"


@dataclass(frozen=True)
class RustReferenceReceipt:
    candidates: int = 0
    rejected_qualified_suffix: int = 0
    rejected_unreachable_crate: int = 0


def filter_rust_reference_edges(
    root: Path,
    active_paths: set[str],
    nodes: dict[str, Node],
    edges: list[Edge],
) -> tuple[list[Edge], RustReferenceReceipt]:
    """Reject syntactically invalid and architecturally impossible Rust references.

    Qualified enum variants such as ``Effect::Read`` name ``Effect`` as the
    type; the trailing ``Read`` is not a type use. Cross-crate references are
    additionally accepted only when the target package is reachable through
    the source package's Cargo dependency graph.
    """
    workspace = _CargoWorkspace.load(root, active_paths)
    source_cache: dict[str, str] = {}
    excerpt_cache: dict[str, str] = {}
    next_line_by_node = _next_symbol_lines(nodes)
    enum_nodes: dict[str, list[Node]] = {}
    enum_variants: dict[str, frozenset[str]] = {}
    for node in nodes.values():
        if node.kind == "enum" and node.path.endswith(".rs"):
            enum_nodes.setdefault(node.label, []).append(node)
    kept: list[Edge] = []
    candidates = 0
    rejected_suffix = 0
    rejected_dependency = 0

    for edge in edges:
        source = nodes.get(edge.source)
        target = nodes.get(edge.target)
        if (
            edge.type != "references"
            or source is None
            or target is None
            or not source.path.endswith(".rs")
            or not target.path.endswith(".rs")
        ):
            kept.append(edge)
            continue

        candidates += 1
        if edge.provenance == _TYPE_REFERENCE_PROVENANCE:
            excerpt = excerpt_cache.get(source.id)
            if excerpt is None:
                source_text = source_cache.get(source.path)
                if source_text is None:
                    try:
                        source_text = (root / source.path).read_text(
                            encoding="utf-8",
                            errors="replace",
                        )
                    except OSError:
                        source_text = ""
                    source_cache[source.path] = source_text
                excerpt = _definition_excerpt(
                    source_text,
                    source,
                    next_line_by_node.get(source.id),
                )
                excerpt_cache[source.id] = excerpt
            glob_variant = _is_glob_imported_variant(
                excerpt,
                target.label,
                enum_nodes,
                enum_variants,
                source_cache,
                root,
                next_line_by_node,
            )
            if excerpt and not _supports_type_reference(
                excerpt,
                target.label,
                glob_variant=glob_variant,
            ):
                rejected_suffix += 1
                continue

        if not workspace.can_reference(source.path, target.path):
            rejected_dependency += 1
            continue
        kept.append(edge)

    return kept, RustReferenceReceipt(
        candidates=candidates,
        rejected_qualified_suffix=rejected_suffix,
        rejected_unreachable_crate=rejected_dependency,
    )


@dataclass(frozen=True)
class _CargoWorkspace:
    package_by_root: dict[tuple[str, ...], str]
    dependencies: dict[str, frozenset[str]]

    @classmethod
    def load(cls, root: Path, active_paths: set[str]) -> _CargoWorkspace:
        packages: dict[tuple[str, ...], str] = {}
        raw_dependencies: dict[str, set[str]] = {}
        for rel in sorted(path for path in active_paths if Path(path).name == "Cargo.toml"):
            try:
                data = tomllib.loads((root / rel).read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                continue
            package = data.get("package", {})
            name = str(package.get("name") or "").replace("-", "_")
            if not name:
                continue
            package_root = Path(rel).parent
            root_parts = () if package_root == Path(".") else package_root.parts
            packages[root_parts] = name
            raw_dependencies[name] = _manifest_dependencies(data)
        known = set(packages.values())
        dependencies = {
            package: frozenset(dep for dep in deps if dep in known)
            for package, deps in raw_dependencies.items()
        }
        return cls(packages, dependencies)

    def can_reference(self, source_path: str, target_path: str) -> bool:
        source_package = self._package_for_path(source_path)
        target_package = self._package_for_path(target_path)
        if not source_package or not target_package or source_package == target_package:
            return True
        frontier = [source_package]
        visited = {source_package}
        while frontier:
            package = frontier.pop()
            for dependency in self.dependencies.get(package, ()):
                if dependency == target_package:
                    return True
                if dependency not in visited:
                    visited.add(dependency)
                    frontier.append(dependency)
        return False

    def _package_for_path(self, raw_path: str) -> str | None:
        parts = Path(raw_path).parts
        matches = [
            (len(root_parts), package)
            for root_parts, package in self.package_by_root.items()
            if parts[: len(root_parts)] == root_parts
        ]
        return max(matches, default=(0, None))[1]


def _manifest_dependencies(data: dict[str, object]) -> set[str]:
    dependencies: set[str] = set()

    def add_sections(table: object) -> None:
        if not isinstance(table, dict):
            return
        for section in _DEPENDENCY_SECTIONS:
            values = table.get(section, {})
            if not isinstance(values, dict):
                continue
            for alias, specification in values.items():
                package = (
                    specification.get("package")
                    if isinstance(specification, dict)
                    else None
                )
                dependencies.add(str(package or alias).replace("-", "_"))

    add_sections(data)
    targets = data.get("target", {})
    if isinstance(targets, dict):
        for target in targets.values():
            add_sections(target)
    return dependencies


def _next_symbol_lines(nodes: dict[str, Node]) -> dict[str, int]:
    by_path: dict[str, list[tuple[int, str]]] = {}
    for node in nodes.values():
        if node.path.endswith(".rs") and node.line is not None:
            by_path.setdefault(node.path, []).append((node.line, node.id))
    next_lines: dict[str, int] = {}
    for located in by_path.values():
        located.sort()
        for index, (_line, node_id) in enumerate(located[:-1]):
            next_lines[node_id] = located[index + 1][0]
    return next_lines


def _definition_excerpt(text: str, node: Node, next_line: int | None) -> str:
    if not text or node.line is None:
        return ""
    lines = text.splitlines()
    start = max(0, node.line - 1)
    end = next_line - 1 if next_line is not None else len(lines)
    excerpt_lines = lines[start:end]
    depth = 0
    opened = False
    bounded: list[str] = []
    for line in excerpt_lines:
        bounded.append(line)
        depth += line.count("{") - line.count("}")
        opened = opened or "{" in line
        if opened and depth <= 0:
            break
    return "\n".join(bounded)


def _rust_type_names(text: str) -> set[str]:
    head = text.split("{", 1)[0]
    names = {
        match.group(1)
        for match in re.finditer(r"\b([A-Z][A-Za-z0-9_]*)\s*::", text)
    }
    # In the signature, a single colon starts a parameter type annotation.
    # Applying this to the whole body mistakes struct fields such as
    # `kind: SymbolAccessKind::Read` for a type path ending in `Read`.
    names.update(
        match.group(1)
        for match in re.finditer(
            rf"(?<!:):\s*(?:&\s*)?{_RUST_TYPE_PATH}\b",
            head,
        )
    )
    # Local type annotations are unambiguous when introduced by `let`.
    names.update(
        match.group(1)
        for match in re.finditer(
            rf"\blet\s+(?:mut\s+)?[A-Za-z_][A-Za-z0-9_]*\s*:"
            rf"\s*(?:&\s*)?{_RUST_TYPE_PATH}\b",
            text,
        )
    )
    # Parentheses, commas, references, and generic brackets are type contexts
    # in the signature. In the body they are also enum-pattern contexts:
    # `(Read(x), Write(y))`; applying this pattern there caused cycle-five's
    # false edges.
    names.update(
        match.group(1)
        for match in re.finditer(
            rf"(?:[&<,(\[])\s*{_RUST_TYPE_PATH}\b",
            head,
        )
    )
    names.update(
        match.group(1)
        for match in re.finditer(
            r"->\s*(?:Result\s*<\s*)?(?:Option\s*<\s*)?([A-Z][A-Za-z0-9_]*)\b",
            head,
        )
    )
    return names


def _supports_type_reference(
    text: str,
    label: str,
    *,
    glob_variant: bool,
) -> bool:
    escaped = re.escape(label)
    if not re.search(rf"\b{escaped}\b", text):
        return False
    if label in _rust_type_names(text):
        return True
    # A remaining unqualified capitalized value is commonly a unit/tuple
    # struct constructor (`Box::new(RedundancyAdvisor)`), which is a real
    # reference to that struct. The important exception is a glob-imported
    # enum variant: `use Effect::*; ... Read(x)` names the enum's variant, not
    # an unrelated struct called Read.
    has_unqualified = bool(re.search(rf"(?<!:)\b{escaped}\b", text))
    if has_unqualified and glob_variant:
        return False
    return has_unqualified


def _is_glob_imported_variant(
    text: str,
    label: str,
    enum_nodes: dict[str, list[Node]],
    enum_variants: dict[str, frozenset[str]],
    source_cache: dict[str, str],
    root: Path,
    next_line_by_node: dict[str, int],
) -> bool:
    imported_enums = {
        match.group(1)
        for match in re.finditer(
            r"\buse\s+(?:[A-Za-z_][A-Za-z0-9_]*::)*"
            r"([A-Z][A-Za-z0-9_]*)::\*\s*;",
            text,
        )
    }
    for enum_name in imported_enums:
        variants = enum_variants.get(enum_name)
        if variants is None:
            found: set[str] = set()
            for enum_node in enum_nodes.get(enum_name, ()):
                source_text = source_cache.get(enum_node.path)
                if source_text is None:
                    try:
                        source_text = (root / enum_node.path).read_text(
                            encoding="utf-8",
                            errors="replace",
                        )
                    except OSError:
                        source_text = ""
                    source_cache[enum_node.path] = source_text
                excerpt = _definition_excerpt(
                    source_text,
                    enum_node,
                    next_line_by_node.get(enum_node.id),
                )
                found.update(_enum_variant_names(excerpt))
            variants = frozenset(found)
            enum_variants[enum_name] = variants
        if label in variants:
            return True
    return False


def _enum_variant_names(text: str) -> set[str]:
    if "{" not in text:
        return set()
    body = text.split("{", 1)[1].rsplit("}", 1)[0]
    return {
        match.group(1)
        for match in re.finditer(
            r"(?:^|,)\s*(?:#\[[^\]]+\]\s*)*([A-Z][A-Za-z0-9_]*)\b",
            body,
            re.MULTILINE,
        )
    }
