"""Persistent Python type facts for exact incremental receiver re-joins.

Each source file contributes a finite set of facts and obligations.  Project
facts are the commutative join of those contributions, plus a bounded monotone
closure over package re-exports.  Incremental scheduling compares the old and
new project environments and uses the reverse obligation relation to identify
unchanged files whose receiver edges may have changed.
"""

from __future__ import annotations

import ast as py_ast
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .python import (
    _python_class_field_types,
    _python_module_global_facts,
    _python_module_return_facts,
)
from .type_facts import Evidence, TypeFact

FactKey = tuple[str, str, str]


ParentEdge = tuple[str, str, str]


@dataclass(frozen=True)
class PythonProjectTypeFacts:
    fields: Mapping[tuple[str, str], TypeFact]
    globals: Mapping[tuple[str, str], TypeFact]
    returns: Mapping[tuple[str, str], TypeFact]
    parents: tuple[ParentEdge, ...] = ()
    field_languages: Mapping[tuple[str, str], str] = field(default_factory=dict)

    def keyed(self) -> dict[FactKey, TypeFact]:
        result = {("field", owner, field): fact for (owner, field), fact in self.fields.items()}
        result.update({("global", module, name): fact for (module, name), fact in self.globals.items()})
        result.update({("return", module, name): fact for (module, name), fact in self.returns.items()})
        return result


@dataclass(frozen=True)
class AffectedTypeFactFiles:
    files: frozenset[str] = frozenset()
    changed_facts: int = 0
    affected_obligations: int = 0


def _fact_to_data(fact: TypeFact) -> dict[str, Any]:
    return {
        "types": sorted(fact.types),
        "evidence": [[item.kind, item.source] for item in fact.evidence],
    }


def _fact_from_data(data: object) -> TypeFact:
    if not isinstance(data, dict):
        return TypeFact()
    raw_types = data.get("types", [])
    raw_evidence = data.get("evidence", [])
    types = frozenset(str(item) for item in raw_types if isinstance(item, str))
    evidence = tuple(
        sorted(
            Evidence(str(item[0]), str(item[1])) for item in raw_evidence if isinstance(item, list) and len(item) == 2
        )
    )
    return TypeFact(types, evidence)


def _snapshot_contributions(snapshot: Mapping[str, Any]) -> dict[FactKey, TypeFact]:
    result: dict[FactKey, TypeFact] = {}
    for row_name, kind in (
        ("fields", "field"),
        ("globals", "global"),
        ("returns", "return"),
    ):
        rows = snapshot.get(row_name, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                continue
            key = (kind, str(row[0]), str(row[1]))
            result[key] = result.get(key, TypeFact()).join(_fact_from_data(row[2]))
    return result


def _snapshot_obligations(snapshot: Mapping[str, Any]) -> frozenset[FactKey]:
    raw_rows = snapshot.get("obligations", [])
    if not isinstance(raw_rows, list):
        return frozenset()
    return frozenset(tuple(str(part) for part in row) for row in raw_rows if isinstance(row, list) and len(row) == 3)


def _snapshot_parents(snapshot: Mapping[str, Any]) -> frozenset[ParentEdge]:
    raw_rows = snapshot.get("parents", [])
    if not isinstance(raw_rows, list):
        return frozenset()
    return frozenset(
        (str(row[0]), str(row[1]), str(row[2]))
        for row in raw_rows
        if isinstance(row, list) and len(row) == 3 and all(row)
    )


def _python_parent_edges(module: py_ast.Module) -> tuple[ParentEdge, ...]:
    edges: list[ParentEdge] = []
    for node in module.body:
        if not isinstance(node, py_ast.ClassDef):
            continue
        for base in node.bases:
            name = _ast_type_name(base)
            if name:
                edges.append(("python", node.name, name))
    return tuple(sorted(set(edges)))


def _ast_type_name(node: py_ast.AST) -> str:
    if isinstance(node, py_ast.Name):
        return node.id
    if isinstance(node, py_ast.Attribute):
        return node.attr
    return ""


def _snapshot_reexports(
    snapshot: Mapping[str, Any],
) -> frozenset[tuple[FactKey, FactKey]]:
    raw_rows = snapshot.get("reexports", [])
    if not isinstance(raw_rows, list):
        return frozenset()
    result: set[tuple[FactKey, FactKey]] = set()
    for row in raw_rows:
        if not isinstance(row, list) or len(row) != 4:
            continue
        package, imported_module, imported_name, local_name = map(str, row)
        for kind in ("global", "return"):
            result.add(
                (
                    (kind, imported_module, imported_name),
                    (kind, package, local_name),
                )
            )
    return frozenset(result)


class PersistentPythonTypeIndex:
    """Mutable finite relation used only while planning one scan.

    The serialized form lives at manifest scope.  Updating one file removes
    and adds only rows owned by that file, recomputes the forward-reachable
    re-export subgraph, then looks changed keys up in the reverse obligation
    relation.
    """

    def __init__(
        self,
        *,
        contributions: Mapping[FactKey, Mapping[str, TypeFact]] | None = None,
        obligations: Mapping[FactKey, Iterable[str]] | None = None,
        reexports: Mapping[tuple[FactKey, FactKey], Iterable[str]] | None = None,
        project: Mapping[FactKey, TypeFact] | None = None,
    ) -> None:
        self.contributions = {key: dict(by_file) for key, by_file in (contributions or {}).items()}
        self.obligations = {key: set(files) for key, files in (obligations or {}).items()}
        self.reexports = {edge: set(files) for edge, files in (reexports or {}).items()}
        self.parents: dict[ParentEdge, set[str]] = {}
        self.field_languages: dict[tuple[str, str], str] = {}
        self.project = dict(project or {})
        self.reexport_outgoing: dict[FactKey, set[FactKey]] = defaultdict(set)
        self.reexport_incoming: dict[FactKey, set[FactKey]] = defaultdict(set)
        for source, target in self.reexports:
            self.reexport_outgoing[source].add(target)
            self.reexport_incoming[target].add(source)
        self.field_keys_by_name: dict[str, set[FactKey]] = defaultdict(set)
        for key in self.contributions:
            if key[0] == "field":
                self.field_keys_by_name[key[2]].add(key)

    @classmethod
    def from_snapshots(
        cls,
        snapshots: Mapping[str, Mapping[str, Any]],
    ) -> PersistentPythonTypeIndex:
        index = cls()
        for rel, snapshot in snapshots.items():
            index._add_file(rel, snapshot)
        index._recompute_all()
        return index

    @classmethod
    def from_data(cls, data: object) -> PersistentPythonTypeIndex:
        if not isinstance(data, dict):
            return cls()
        contributions: dict[FactKey, dict[str, TypeFact]] = {}
        for row in data.get("contributions", []):
            if not isinstance(row, list) or len(row) != 4 or not isinstance(row[3], list):
                continue
            key = (str(row[0]), str(row[1]), str(row[2]))
            contributions[key] = {
                str(item[0]): _fact_from_data(item[1]) for item in row[3] if isinstance(item, list) and len(item) == 2
            }
        obligations = {
            (str(row[0]), str(row[1]), str(row[2])): {str(rel) for rel in row[3]}
            for row in data.get("obligations", [])
            if isinstance(row, list) and len(row) == 4 and isinstance(row[3], list)
        }
        reexports = {
            (
                (str(row[0]), str(row[1]), str(row[2])),
                (str(row[3]), str(row[4]), str(row[5])),
            ): {str(rel) for rel in row[6]}
            for row in data.get("reexports", [])
            if isinstance(row, list) and len(row) == 7 and isinstance(row[6], list)
        }
        project = {
            (str(row[0]), str(row[1]), str(row[2])): _fact_from_data(row[3])
            for row in data.get("project", [])
            if isinstance(row, list) and len(row) == 4
        }
        index = cls(
            contributions=contributions,
            obligations=obligations,
            reexports=reexports,
            project=project,
        )
        for row in data.get("parents", []):
            if not isinstance(row, list) or len(row) != 4 or not isinstance(row[3], list):
                continue
            index.parents[(str(row[0]), str(row[1]), str(row[2]))] = {
                str(rel) for rel in row[3]
            }
        for row in data.get("field_languages", []):
            if not isinstance(row, list) or len(row) != 3:
                continue
            index.field_languages[(str(row[0]), str(row[1]))] = str(row[2])
        return index

    def to_data(self) -> dict[str, Any]:
        return {
            "contributions": [
                [
                    *key,
                    [[rel, _fact_to_data(fact)] for rel, fact in sorted(by_file.items())],
                ]
                for key, by_file in sorted(self.contributions.items())
            ],
            "obligations": [[*key, sorted(files)] for key, files in sorted(self.obligations.items())],
            "reexports": [
                [*source, *target, sorted(files)] for (source, target), files in sorted(self.reexports.items())
            ],
            "project": [[*key, _fact_to_data(fact)] for key, fact in sorted(self.project.items())],
            "parents": [[*edge, sorted(files)] for edge, files in sorted(self.parents.items())],
            "field_languages": [
                [owner, name, language]
                for (owner, name), language in sorted(self.field_languages.items())
            ],
        }

    def _add_file(self, rel: str, snapshot: Mapping[str, Any]) -> None:
        language = str(snapshot.get("language") or "python")
        for key, fact in _snapshot_contributions(snapshot).items():
            self.contributions.setdefault(key, {})[rel] = fact
            if key[0] == "field":
                self.field_keys_by_name[key[2]].add(key)
                self.field_languages[(key[1], key[2])] = language
        for key in _snapshot_obligations(snapshot):
            self.obligations.setdefault(key, set()).add(rel)
        for edge in _snapshot_reexports(snapshot):
            owners = self.reexports.setdefault(edge, set())
            if not owners:
                source, target = edge
                self.reexport_outgoing[source].add(target)
                self.reexport_incoming[target].add(source)
            owners.add(rel)
        for edge in _snapshot_parents(snapshot):
            self.parents.setdefault(edge, set()).add(rel)

    def _drop_owned(self, table: dict, key: object, rel: str) -> bool:
        owners = table.get(key)
        if owners is None:
            return False
        owners.discard(rel) if isinstance(owners, set) else owners.pop(rel, None)
        if owners:
            return False
        table.pop(key, None)
        return True

    def _forget_field_key(self, key: FactKey) -> None:
        self.field_keys_by_name[key[2]].discard(key)
        if not self.field_keys_by_name[key[2]]:
            self.field_keys_by_name.pop(key[2], None)
        self.field_languages.pop((key[1], key[2]), None)

    def _forget_reexport(self, edge: tuple[FactKey, FactKey]) -> None:
        source, target = edge
        self.reexport_outgoing[source].discard(target)
        self.reexport_incoming[target].discard(source)
        if not self.reexport_outgoing[source]:
            self.reexport_outgoing.pop(source, None)
        if not self.reexport_incoming[target]:
            self.reexport_incoming.pop(target, None)

    def _remove_file(self, rel: str, snapshot: Mapping[str, Any]) -> None:
        for key in _snapshot_contributions(snapshot):
            if self._drop_owned(self.contributions, key, rel) and key[0] == "field":
                self._forget_field_key(key)
        for key in _snapshot_obligations(snapshot):
            self._drop_owned(self.obligations, key, rel)
        for edge in _snapshot_reexports(snapshot):
            if self._drop_owned(self.reexports, edge, rel):
                self._forget_reexport(edge)
        for edge in _snapshot_parents(snapshot):
            self._drop_owned(self.parents, edge, rel)

    def _direct_fact(self, key: FactKey) -> TypeFact:
        result = TypeFact()
        for fact in self.contributions.get(key, {}).values():
            result = result.join(fact)
        return result

    def _recompute_all(self) -> None:
        self.project = {key: fact for key in self.contributions if (fact := self._direct_fact(key)).types}
        self._fixed_point(set(self.contributions) | {target for _source, target in self.reexports})

    def _fixed_point(self, keys: set[FactKey]) -> None:
        for key in keys:
            direct = self._direct_fact(key)
            if direct.types:
                self.project[key] = direct
            else:
                self.project.pop(key, None)
        # A finite powerset lattice reaches a fixpoint after at most one new
        # evidence item per key.  The worklist only revisits outgoing targets
        # when a source value actually grows.
        queue = deque(sorted(keys))
        queued = set(keys)
        while queue:
            key = queue.popleft()
            queued.discard(key)
            joined = self._direct_fact(key)
            for source in self.reexport_incoming.get(key, ()):
                joined = joined.join(self.project.get(source, TypeFact()))
            prior = self.project.get(key, TypeFact())
            if joined == prior:
                continue
            if joined.types:
                self.project[key] = joined
            else:
                self.project.pop(key, None)
            for target in self.reexport_outgoing.get(key, ()):
                if target not in keys:
                    continue
                if target not in queued:
                    queue.append(target)
                    queued.add(target)

    def update(
        self,
        old_snapshots: Mapping[str, Mapping[str, Any]],
        new_snapshots: Mapping[str, Mapping[str, Any]],
        changed_files: Iterable[str],
    ) -> frozenset[FactKey]:
        seeds: set[FactKey] = set()
        changed_files = tuple(changed_files)
        for rel in changed_files:
            old = old_snapshots.get(rel, {})
            new = new_snapshots.get(rel, {})
            old_edges = _snapshot_reexports(old)
            new_edges = _snapshot_reexports(new)
            seeds.update(_snapshot_contributions(old))
            seeds.update(_snapshot_contributions(new))
            seeds.update(target for _source, target in old_edges | new_edges)
            self._remove_file(rel, old)
            self._add_file(rel, new)

        affected_keys = set(seeds)
        queue = deque(seeds)
        while queue:
            source = queue.popleft()
            for target in self.reexport_outgoing.get(source, ()):
                if target not in affected_keys:
                    affected_keys.add(target)
                    queue.append(target)
        old_project = {
            key: self.project.get(key, TypeFact())
            for key in affected_keys
        }
        self._fixed_point(affected_keys)
        return frozenset(
            key
            for key in affected_keys
            if old_project[key] != self.project.get(key, TypeFact())
        )

    def affected_files(
        self,
        changed_keys: Iterable[FactKey],
        *,
        excluded_files: Iterable[str],
    ) -> AffectedTypeFactFiles:
        changed = frozenset(changed_keys)
        excluded = frozenset(excluded_files)
        files: set[str] = set()
        matched_pairs: set[tuple[str, FactKey]] = set()
        for key in changed:
            consumers = set(self.obligations.get(key, ()))
            if key[0] == "field":
                consumers.update(self.obligations.get(("field", "", key[2]), ()))
            for rel in consumers - excluded:
                files.add(rel)
                matched_pairs.add((rel, key))
        return AffectedTypeFactFiles(
            files=frozenset(files),
            changed_facts=len(changed),
            affected_obligations=len(matched_pairs),
        )

    def context_for_files(
        self,
        snapshots: Mapping[str, Mapping[str, Any]],
        files: Iterable[str],
    ) -> PythonProjectTypeFacts:
        requested: set[FactKey] = set()
        for rel in files:
            for key in _snapshot_obligations(snapshots.get(rel, {})):
                if key[0] != "field":
                    requested.add(key)
                    continue
                requested.update(self.field_keys_by_name.get(key[2], ()))
        fields: dict[tuple[str, str], TypeFact] = {}
        globals_: dict[tuple[str, str], TypeFact] = {}
        returns: dict[tuple[str, str], TypeFact] = {}
        for kind, left, right in requested:
            fact = self.project.get((kind, left, right), TypeFact())
            if not fact.types:
                continue
            target = fields if kind == "field" else globals_ if kind == "global" else returns
            target[(left, right)] = fact
        return PythonProjectTypeFacts(
            fields,
            globals_,
            returns,
            parents=tuple(sorted(self.parents)),
            field_languages=dict(self.field_languages),
        )


def _python_import_relations(
    module: py_ast.Module, rel: str
) -> tuple[set[tuple[str, str, str, str]], set[FactKey]]:
    reexports: set[tuple[str, str, str, str]] = set()
    obligations: set[FactKey] = set()
    is_package = rel.rsplit("/", 1)[-1] == "__init__.py"
    package_name = rel.rsplit("/", 1)[0].rsplit("/", 1)[-1] if "/" in rel else ""
    for node in module.body:
        if not isinstance(node, py_ast.ImportFrom) or not node.module:
            continue
        imported_module = node.module.rsplit(".", 1)[-1]
        for alias in node.names:
            if alias.name == "*":
                continue
            obligations.add(("global", imported_module, alias.name))
            obligations.add(("return", imported_module, alias.name))
            if is_package and package_name:
                reexports.add(
                    (
                        package_name,
                        imported_module,
                        alias.name,
                        alias.asname or alias.name,
                    )
                )
    for node in py_ast.walk(module):
        if isinstance(node, py_ast.Attribute):
            obligations.add(("field", "", node.attr))
    return reexports, obligations


def _parse_module(source: str) -> py_ast.Module | None:
    try:
        return py_ast.parse(source)
    except (IndentationError, SyntaxError, ValueError, RecursionError):
        return None


def python_file_type_snapshot(source: str, rel: str) -> dict[str, Any]:
    """Return one compact, JSON-safe file contribution."""
    if not rel.casefold().endswith(".py"):
        return {}
    module = _parse_module(source)
    if module is None:
        return {
            "fields": [],
            "globals": [],
            "returns": [],
            "reexports": [],
            "obligations": [],
            "parents": [],
        }

    field_rows = []
    for (owner, field), type_name in sorted(_python_class_field_types(source).items()):
        fact = TypeFact.from_evidence(
            type_name,
            Evidence("field_type", f"{rel}:{owner}.{field}"),
        )
        field_rows.append([owner, field, _fact_to_data(fact)])

    module_name = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    global_rows = [
        [module_name, name, _fact_to_data(fact)]
        for name, fact in sorted(_python_module_global_facts(source, rel).items())
    ]
    return_rows = [
        [module_name, name, _fact_to_data(fact)]
        for name, fact in sorted(_python_module_return_facts(source, rel).items())
    ]

    reexports, obligations = _python_import_relations(module, rel)

    return {
        "fields": field_rows,
        "globals": global_rows,
        "returns": return_rows,
        "reexports": [list(row) for row in sorted(reexports)],
        "obligations": [list(row) for row in sorted(obligations)],
        "parents": [list(row) for row in _python_parent_edges(module)],
        "language": "python",
    }


def _field_languages(
    snapshots: Mapping[str, Mapping[str, Any]],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for snapshot in snapshots.values():
        language = str(snapshot.get("language") or "python")
        rows = snapshot.get("fields", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                continue
            result[(str(row[0]), str(row[1]))] = language
    return result


def _joined_rows(
    snapshots: Mapping[str, Mapping[str, Any]],
    row_name: str,
) -> dict[tuple[str, str], TypeFact]:
    result: dict[tuple[str, str], TypeFact] = {}
    for snapshot in snapshots.values():
        rows = snapshot.get(row_name, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) != 3:
                continue
            key = (str(row[0]), str(row[1]))
            result[key] = result.get(key, TypeFact()).join(_fact_from_data(row[2]))
    return result


def _reexport_rows(
    snapshots: Mapping[str, Mapping[str, Any]],
) -> tuple[tuple[str, str, str, str], ...]:
    rows: set[tuple[str, str, str, str]] = set()
    for snapshot in snapshots.values():
        raw_rows = snapshot.get("reexports", [])
        if not isinstance(raw_rows, list):
            continue
        rows.update(tuple(str(part) for part in row) for row in raw_rows if isinstance(row, list) and len(row) == 4)
    return tuple(sorted(rows))


def _join_reexports(
    direct: Mapping[tuple[str, str], TypeFact],
    reexports: Iterable[tuple[str, str, str, str]],
) -> dict[tuple[str, str], TypeFact]:
    result = dict(direct)
    rows = tuple(reexports)
    # Every productive round adds evidence to at least one of the finite
    # package-symbol keys.  The explicit row bound prevents malformed cyclic
    # manifests from turning persistence into an unbounded fixpoint.
    for _round in range(len(rows) + 1):
        changed = False
        for package, imported_module, imported_name, local_name in rows:
            source_fact = result.get((imported_module, imported_name), TypeFact())
            key = (package, local_name)
            joined = result.get(key, TypeFact()).join(source_fact)
            if joined != result.get(key, TypeFact()):
                result[key] = joined
                changed = True
        if not changed:
            break
    return result


def join_python_project_type_facts(
    snapshots: Mapping[str, Mapping[str, Any]],
) -> PythonProjectTypeFacts:
    """Join all active file contributions into one deterministic environment."""
    reexports = _reexport_rows(snapshots)
    parents: set[ParentEdge] = set()
    for snapshot in snapshots.values():
        parents.update(_snapshot_parents(snapshot))
    return PythonProjectTypeFacts(
        fields=_joined_rows(snapshots, "fields"),
        globals=_join_reexports(_joined_rows(snapshots, "globals"), reexports),
        returns=_join_reexports(_joined_rows(snapshots, "returns"), reexports),
        parents=tuple(sorted(parents)),
        field_languages=_field_languages(snapshots),
    )


def frontend_file_type_snapshot(source: str, rel: str) -> dict[str, Any]:
    """Language-neutral per-file fact contribution for incremental re-join.

    Python stays on the AST snapshot. Other languages parse once with the
    same tree-sitter frontends the extractor uses, then emit field and parent
    rows. Parser failures produce an empty contribution rather than aborting
    the scan.
    """

    if rel.casefold().endswith(".py"):
        return python_file_type_snapshot(source, rel)

    from pathlib import Path

    from ..source_ir import SourceIR
    from .edges import _file_field_types
    from .languages import _SUFFIX_LANGUAGE, _parser_for_suffix
    from .syntax import _collect_defs

    path = Path(rel)
    suffix = path.suffix.lower()
    parser = _parser_for_suffix(suffix)
    if parser is None or not source.strip():
        return {}
    language = _SUFFIX_LANGUAGE.get(suffix, suffix.lstrip(".") or "unknown")
    posix = rel.replace("\\", "/")
    ir = SourceIR(path, posix, posix, source)
    try:
        tree = parser.parse(ir.text_bytes)
    except Exception:
        return {}
    root = tree.root_node
    defs = _collect_defs(ir, root, ir.text_bytes)
    field_rows = []
    for (owner, field_name), type_name in sorted(_file_field_types(ir, defs, root).items()):
        if not type_name:
            continue
        fact = TypeFact.from_evidence(
            type_name,
            Evidence("field_type", f"{posix}:{owner}.{field_name}"),
        )
        field_rows.append([owner, field_name, _fact_to_data(fact)])
    parents = [
        [language, definition.name, base]
        for definition in defs
        if definition.kind in {"class", "interface", "struct", "trait", "type"}
        for base in definition.extra
        if base
    ]
    return {
        "fields": field_rows,
        "globals": [],
        "returns": [],
        "reexports": [],
        "obligations": [list(row) for row in sorted(_member_field_obligations(root, ir.text_bytes))],
        "parents": parents,
        "language": language,
    }


_MEMBER_NODE_TYPES = frozenset(
    {
        "attribute",
        "member_expression",
        "member_access_expression",
        "field_expression",
        "field_access",
        "selector_expression",
        "navigation_expression",
        "qualified_identifier",
    }
)


def _member_field_obligations(root: Any, text: bytes) -> frozenset[FactKey]:
    """Field names read at member-access sites, used to wake consumers.

    Keyed like Python's ``("field", "", attr)`` so a changed ``X.store`` fact
    promotes any file that reads ``.store``, in any language.
    """

    names: set[str] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        children = list(getattr(node, "named_children", ()))
        stack.extend(children)
        if getattr(node, "type", "") not in _MEMBER_NODE_TYPES:
            continue
        field_name = ""
        for child in reversed(children):
            child_type = getattr(child, "type", "")
            if child_type in {"identifier", "property_identifier", "field_identifier", "type_identifier"}:
                field_name = text[int(child.start_byte) : int(child.end_byte)].decode(
                    "utf-8", errors="replace"
                )
                break
        if field_name and field_name.isidentifier():
            names.add(field_name)
    return frozenset(("field", "", name) for name in names)
