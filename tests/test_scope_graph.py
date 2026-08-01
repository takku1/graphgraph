from __future__ import annotations

import unittest

from graphgraph.scanner.frontends.scope_graph import (
    BindingEnvironment,
    ScopeGraph,
    type_scope,
)
from graphgraph.scanner.frontends.type_facts import Evidence, TypeFact, TypeState


def _fact(type_name: str, source: str) -> TypeFact:
    return TypeFact.from_evidence(type_name, Evidence("test", source))


class BindingEnvironmentTest(unittest.TestCase):
    def test_stronger_evidence_replaces_weaker_evidence(self) -> None:
        bindings = BindingEnvironment()
        bindings.bind("client", _fact("Fallback", "weak"), priority=10)
        bindings.bind("client", _fact("Declared", "strong"), priority=20)
        self.assertEqual("Declared", bindings.concrete_types["client"])

    def test_equal_strength_conflict_abstains(self) -> None:
        bindings = BindingEnvironment()
        bindings.bind("client", _fact("Left", "left"), priority=20)
        bindings.bind("client", _fact("Right", "right"), priority=20)
        self.assertEqual(TypeState.AMBIGUOUS, bindings.facts["client"].state)
        self.assertNotIn("client", bindings.concrete_types)


class ScopeGraphTest(unittest.TestCase):
    def test_languages_are_separate_strata(self) -> None:
        graph = ScopeGraph()
        graph.add_binding(type_scope("java", "Service"), "client", _fact("JavaClient", "j"))
        graph.add_binding(type_scope("csharp", "Service"), "client", _fact("CSharpClient", "c"))
        self.assertEqual(
            "JavaClient",
            graph.resolve_binding(type_scope("java", "Service"), "client").fact.concrete,
        )
        self.assertEqual(
            "CSharpClient",
            graph.resolve_binding(type_scope("csharp", "Service"), "client").fact.concrete,
        )

    def test_nearest_declaration_shadows_ancestor(self) -> None:
        graph = ScopeGraph()
        child = type_scope("csharp", "Child")
        parent = type_scope("csharp", "Parent")
        graph.add_parent(child, parent)
        graph.add_binding(parent, "client", _fact("ParentClient", "parent"))
        graph.add_binding(child, "client", _fact("ChildClient", "child"))
        resolution = graph.resolve_binding(child, "client")
        self.assertEqual("ChildClient", resolution.fact.concrete)
        self.assertEqual(0, resolution.distance)

    def test_equal_distance_parent_conflict_abstains(self) -> None:
        graph = ScopeGraph()
        child = type_scope("cpp", "Child")
        left = type_scope("cpp", "Left")
        right = type_scope("cpp", "Right")
        graph.add_parent(child, left)
        graph.add_parent(child, right)
        graph.add_binding(left, "client", _fact("LeftClient", "left"))
        graph.add_binding(right, "client", _fact("RightClient", "right"))
        resolution = graph.resolve_binding(child, "client")
        self.assertEqual(TypeState.AMBIGUOUS, resolution.fact.state)
        self.assertEqual(1, resolution.distance)
        self.assertEqual((left, right), resolution.scopes)
        self.assertEqual(((left, right),), graph.ancestor_layers(child))

    def test_cycles_are_bounded_and_do_not_repeat_scopes(self) -> None:
        graph = ScopeGraph()
        first = type_scope("python", "First")
        second = type_scope("python", "Second")
        graph.add_parent(first, second)
        graph.add_parent(second, first)
        graph.add_binding(second, "client", _fact("Client", "second"))
        self.assertEqual((second,), graph.ancestors(first))
        self.assertEqual(
            "Client",
            graph.resolve_binding(first, "client").fact.concrete,
        )


if __name__ == "__main__":
    unittest.main()
