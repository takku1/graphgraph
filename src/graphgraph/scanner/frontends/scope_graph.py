"""Language-partitioned scope bindings with nearest-scope resolution.

Frontends emit facts into this model; they do not decide which declaration is
visible at a use site. Resolution walks explicit scope edges breadth-first, so
the nearest binding wins, equal-distance conflicts join to ``ambiguous``, and
cycles terminate without guessing. The model is deliberately small: lexical
and module scopes can be added as producers migrate, while type/inheritance
scopes already replace the former unpartitioned owner dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass

from .type_facts import TypeFact


@dataclass(frozen=True, order=True)
class ScopeId:
    """Stable identity for one scope within a language stratum."""

    language: str
    kind: str
    name: str


def type_scope(language: str, owner: str) -> ScopeId:
    """Return the type scope that owns fields and inherited members."""

    return ScopeId(language, "type", owner)


@dataclass(frozen=True)
class BindingResolution:
    """The nearest fact for a name and the scopes that supplied it."""

    fact: TypeFact = TypeFact()
    distance: int | None = None
    scopes: tuple[ScopeId, ...] = ()


@dataclass(frozen=True)
class RankedBinding:
    """A fact plus its evidence-strength tier within one lexical scope."""

    fact: TypeFact
    priority: int


class BindingEnvironment:
    """One lexical scope with explicit strong-over-weak evidence precedence.

    Higher-priority evidence replaces lower-priority evidence. Equal-priority
    facts join in the monotone lattice, so a genuine conflict becomes
    ambiguous and projects to no receiver type.
    """

    def __init__(self) -> None:
        self._bindings: dict[str, RankedBinding] = {}

    def bind(self, name: str, fact: TypeFact, *, priority: int) -> None:
        if not name or not fact.types:
            return
        current = self._bindings.get(name)
        if current is None or priority > current.priority:
            self._bindings[name] = RankedBinding(fact, priority)
        elif priority == current.priority:
            self._bindings[name] = RankedBinding(current.fact.join(fact), priority)

    def bind_types(
        self,
        types: dict[str, str],
        *,
        evidence_kind: str,
        evidence_source: str,
        priority: int,
    ) -> None:
        from .type_facts import Evidence

        for name, type_name in types.items():
            self.bind(
                name,
                TypeFact.from_evidence(
                    type_name,
                    Evidence(evidence_kind, evidence_source),
                ),
                priority=priority,
            )

    @property
    def facts(self) -> dict[str, TypeFact]:
        return {
            name: ranked.fact
            for name, ranked in sorted(self._bindings.items())
        }

    @property
    def concrete_types(self) -> dict[str, str]:
        return {
            name: concrete
            for name, ranked in sorted(self._bindings.items())
            if (concrete := ranked.fact.concrete) is not None
        }


class ScopeGraph:
    """Finite declarations plus directed visibility edges between scopes."""

    def __init__(self) -> None:
        self._bindings: dict[ScopeId, dict[str, TypeFact]] = {}
        self._parents: dict[ScopeId, list[ScopeId]] = {}

    def add_binding(self, scope: ScopeId, name: str, fact: TypeFact) -> None:
        """Join evidence for ``name`` declared directly in ``scope``."""

        if not name or not fact.types:
            return
        bindings = self._bindings.setdefault(scope, {})
        bindings[name] = bindings.get(name, TypeFact()).join(fact)

    def add_parent(self, scope: ScopeId, parent: ScopeId) -> None:
        """Add an ordered visibility edge, ignoring duplicates and self-loops."""

        if scope == parent:
            return
        parents = self._parents.setdefault(scope, [])
        if parent not in parents:
            parents.append(parent)

    def ancestors(self, scope: ScopeId, *, max_depth: int = 64) -> tuple[ScopeId, ...]:
        """Return ancestors nearest-first, bounded and cycle-safe."""

        return tuple(
            ancestor
            for layer in self.ancestor_layers(scope, max_depth=max_depth)
            for ancestor in layer
        )

    def ancestor_layers(
        self,
        scope: ScopeId,
        *,
        max_depth: int = 64,
    ) -> tuple[tuple[ScopeId, ...], ...]:
        """Return equal-distance ancestor layers without arbitrary tie-breaking."""

        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        visited = {scope}
        frontier = tuple(self._parents.get(scope, ()))
        layers: list[tuple[ScopeId, ...]] = []
        depth = 1
        while frontier and depth <= max_depth:
            layer = tuple(sorted(set(frontier) - visited))
            if not layer:
                break
            visited.update(layer)
            layers.append(layer)
            frontier = tuple(
                parent
                for current in layer
                for parent in self._parents.get(current, ())
            )
            depth += 1
        return tuple(layers)

    def visible_bindings(
        self,
        scope: ScopeId,
        *,
        include_start: bool = True,
        max_depth: int = 64,
    ) -> dict[str, BindingResolution]:
        """Resolve every visible binding with nearest-scope precedence.

        All declarations at the same distance join before the search proceeds.
        An ambiguous nearest fact therefore abstains instead of falling through
        to a convenient declaration farther away.
        """

        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        frontier = (scope,) if include_start else tuple(self._parents.get(scope, ()))
        distance = 0 if include_start else 1
        visited = {scope} if not include_start else set()
        resolved: dict[str, BindingResolution] = {}
        while frontier and distance <= max_depth:
            layer: list[ScopeId] = []
            for candidate in frontier:
                if candidate in visited:
                    continue
                visited.add(candidate)
                layer.append(candidate)

            facts: dict[str, TypeFact] = {}
            sources: dict[str, list[ScopeId]] = {}
            for candidate in layer:
                for name, fact in self._bindings.get(candidate, {}).items():
                    if name in resolved:
                        continue
                    facts[name] = facts.get(name, TypeFact()).join(fact)
                    sources.setdefault(name, []).append(candidate)
            for name in sorted(facts):
                resolved[name] = BindingResolution(
                    facts[name],
                    distance,
                    tuple(sorted(sources[name])),
                )

            next_frontier: list[ScopeId] = []
            for candidate in layer:
                next_frontier.extend(self._parents.get(candidate, ()))
            frontier = tuple(next_frontier)
            distance += 1
        return resolved

    def resolve_binding(
        self,
        scope: ScopeId,
        name: str,
        *,
        include_start: bool = True,
        max_depth: int = 64,
    ) -> BindingResolution:
        """Resolve one name through the same bounded nearest-scope algorithm."""

        return self.visible_bindings(
            scope,
            include_start=include_start,
            max_depth=max_depth,
        ).get(name, BindingResolution())
