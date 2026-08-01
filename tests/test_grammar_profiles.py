"""Checks the per-language grammar profiles against the grammars themselves.

The union tables these replaced could not be validated: there was nothing to
ask "does this grammar actually define that node type," which is why
`record_struct_declaration` sat in the definition table for cycles without any
installed C# grammar defining it.
"""

from __future__ import annotations

import unittest

from graphgraph.scanner.frontends.grammars import (
    _UNCLAIMED_BY_INTENT,
    _UNIVERSAL_CALLS,
    GRAMMARS,
    SUFFIX_LANGUAGE,
    UNION_PROFILE,
    profile_for_language,
    profile_for_suffix,
)
from graphgraph.scanner.frontends.languages import _language_for_name


def _named_node_kinds(language_name: str) -> set[str] | None:
    language = _language_for_name(language_name)
    if language is None:
        return None
    return {
        language.node_kind_for_id(index)
        for index in range(language.node_kind_count)
        if language.node_kind_for_id(index) and language.node_kind_is_named(index)
    }


class GrammarProfileValidationTest(unittest.TestCase):
    def test_every_declared_node_type_exists_in_its_grammar(self) -> None:
        # The property the union could not have. Entries deliberately retained
        # against grammar-version drift are exempted by name, so that "kept on
        # purpose" and "typo nobody noticed" stay distinguishable.
        exempt = {_UNIVERSAL_CALLS}
        unclaimed: dict[str, set[str]] = {}
        for language, profile in _UNCLAIMED_BY_INTENT.items():
            unclaimed[language] = (
                set(profile.definitions)
                | profile.names
                | profile.calls
                | profile.path_qualified_calls
            )

        missing: list[str] = []
        for language, profile in GRAMMARS.items():
            kinds = _named_node_kinds(language)
            if kinds is None:
                continue  # grammar not installed in this environment
            declared = (
                set(profile.definitions)
                | profile.names
                | profile.calls
                | profile.path_qualified_calls
            )
            declared -= _UNIVERSAL_CALLS
            declared -= unclaimed.get(language, set())
            for node_type in sorted(declared - kinds):
                missing.append(f"{language}: {node_type}")
        self.assertEqual(
            [], missing,
            "profile declares node types the installed grammar does not define; "
            "either the name is wrong or it belongs in _UNCLAIMED_BY_INTENT",
        )
        self.assertTrue(exempt)  # keeps the exemption set referenced and visible

    def test_every_suffix_maps_to_a_profile(self) -> None:
        for suffix, language in SUFFIX_LANGUAGE.items():
            self.assertIn(
                language, GRAMMARS,
                f"{suffix} maps to '{language}', which has no grammar profile",
            )

    def test_union_is_the_superset_of_every_profile(self) -> None:
        # The migration's whole safety argument: per-language tables are
        # subsets of the union, so narrowing a lookup cannot admit anything new.
        for language, profile in GRAMMARS.items():
            with self.subTest(language=language):
                for node_type, kind in profile.definitions.items():
                    self.assertEqual(
                        kind, UNION_PROFILE.definitions.get(node_type),
                        f"{language} maps {node_type} differently from the union",
                    )
                self.assertLessEqual(profile.names, UNION_PROFILE.names)
                self.assertLessEqual(profile.calls, UNION_PROFILE.calls)
                self.assertLessEqual(
                    profile.path_qualified_calls, UNION_PROFILE.path_qualified_calls
                )
                self.assertLessEqual(profile.self_aliases, UNION_PROFILE.self_aliases)
                self.assertLessEqual(
                    profile.variable_sigils, UNION_PROFILE.variable_sigils
                )

    def test_unknown_language_and_suffix_fall_back_to_the_union(self) -> None:
        # An unrecognised suffix must behave exactly as it did before profiles
        # existed, which means the union and not an empty profile.
        self.assertIs(UNION_PROFILE, profile_for_language(None))
        self.assertIs(UNION_PROFILE, profile_for_language("cobol"))
        self.assertIs(UNION_PROFILE, profile_for_suffix(".cobol"))

    def test_suffix_lookup_is_case_insensitive(self) -> None:
        self.assertIs(profile_for_suffix(".PY"), profile_for_suffix(".py"))

    def test_module_means_different_things_per_language(self) -> None:
        # The concrete reason these tables are per-language. `module` is a
        # Ruby module, a TypeScript namespace, and the root node of every
        # Python file; the union had to pick one meaning for all three.
        for language in ("ruby", "typescript", "python"):
            self.assertEqual("class", GRAMMARS[language].definitions.get("module"))
        self.assertIsNone(GRAMMARS["rust"].definitions.get("module"))
        self.assertIsNone(GRAMMARS["go"].definitions.get("module"))

    def test_php_keeps_its_bare_callee_name_node(self) -> None:
        # PHP names a bare callee `name` rather than `identifier`; dropping it
        # silently removed every PHP call edge once already.
        self.assertIn("name", GRAMMARS["php"].names)

    def test_retained_entries_are_absent_from_installed_grammars(self) -> None:
        # If one of these reappears in a grammar, the exemption is obsolete and
        # the entry should move into the profile proper.
        for language, profile in _UNCLAIMED_BY_INTENT.items():
            kinds = _named_node_kinds(language)
            if kinds is None:
                continue
            declared = set(profile.definitions) | profile.calls | profile.names
            for node_type in sorted(declared & kinds):
                self.fail(
                    f"{language}: '{node_type}' is now defined by the installed "
                    "grammar; move it out of _UNCLAIMED_BY_INTENT"
                )


class EnclosingInstanceBindingTest(unittest.TestCase):
    """Resolution of `self` / `this` / `$this` receivers, per language.

    Which name denotes the enclosing instance used to be a chain of
    `suffix in {...}` tests covering Python, Rust, TS/JS, C#, Java and C++.
    Swift, PHP, Kotlin, Scala and Ruby were absent from it, so a `self.m()` or
    `$this->m()` call inside a method could not resolve to its own class.
    """

    def _scan(self, files: dict[str, str]):
        import tempfile
        from pathlib import Path

        from graphgraph.scanner.core import scan_directory

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, body in files.items():
                (root / name).write_text(body, encoding="utf-8")
            graph = scan_directory(root, depth="symbols", frontend="tree_sitter", docs=False)
            return {
                (edge.source, edge.target)
                for edge in graph.edges
                if edge.type == "calls"
            }

    def test_php_this_arrow_call_resolves_to_its_own_class(self) -> None:
        calls = self._scan({"svc.php": (
            "<?php\n"
            "class Service {\n"
            "    function Handle() { return 2; }\n"
            "    function Run() { return $this->Handle(); }\n"
            "}\n"
        )})
        self.assertIn(
            ("svc_php__Service__Run", "svc_php__Service__Handle"),
            calls,
            "PHP `$this->Handle()` did not resolve to the enclosing class",
        )

    def test_swift_self_call_resolves_to_its_own_class(self) -> None:
        calls = self._scan({"Svc.swift": (
            "class Service {\n"
            "    func Handle() -> Int { return 2 }\n"
            "    func Run() -> Int { return self.Handle() }\n"
            "}\n"
        )})
        self.assertIn(
            ("Svc_swift__Service__Run", "Svc_swift__Service__Handle"),
            calls,
            "Swift `self.Handle()` did not resolve to the enclosing class",
        )

    def test_an_untyped_receiver_does_not_bind_to_the_enclosing_class(self) -> None:
        # The precision half. Binding self-aliases must not degrade into
        # "any unresolved receiver means the enclosing type", which would
        # invent an edge for every call on an unknown object.
        calls = self._scan({"svc.php": (
            "<?php\n"
            "class Other { function Handle() { return 9; } }\n"
            "class Service {\n"
            "    function Handle() { return 2; }\n"
            "    function RunOther($other) { return $other->Handle(); }\n"
            "}\n"
        )})
        self.assertNotIn(
            ("svc_php__Service__RunOther", "svc_php__Service__Handle"),
            calls,
            "an untyped receiver was bound to the enclosing class",
        )
        self.assertNotIn(
            ("svc_php__Service__RunOther", "svc_php__Other__Handle"),
            calls,
            "an untyped receiver was guessed at a same-named method elsewhere",
        )

    def test_php_receiver_text_survives_the_identifier_filter(self) -> None:
        # `$this` fails a bare [A-Za-z_]\w* test, and the receiver was dropped
        # before resolution -- then reported as `complex_expression`, a bucket
        # meaning "receiver text discarded".
        from graphgraph.scanner.frontends.languages import (
            _parse_with_timeout,
            _parser_for_suffix,
        )
        from graphgraph.scanner.frontends.syntax import _call_sites_in_range

        source = b"<?php\nclass S {\n  function h() { return 1; }\n  function r() { return $this->h(); }\n}\n"
        parser = _parser_for_suffix(".php")
        if parser is None:
            self.skipTest("php grammar not installed")
        tree = _parse_with_timeout(parser, source, 0)
        sites = _call_sites_in_range(
            tree.root_node, source, 0, len(source), suffix=".php"
        )
        receivers = {site.receiver for site in sites if site.name == "h"}
        self.assertIn("$this", receivers, f"PHP receiver was discarded: {receivers}")

    def test_every_language_with_methods_declares_a_self_alias(self) -> None:
        # C and Go are the deliberate exceptions: C has no methods, and a Go
        # method names its own receiver (`func (s Service)`) rather than using
        # a fixed keyword.
        for language, profile in GRAMMARS.items():
            if language in {"c", "go"}:
                continue
            with self.subTest(language=language):
                self.assertTrue(
                    profile.self_aliases,
                    f"{language} declares no enclosing-instance name, so a "
                    "member call on it cannot resolve to its own class",
                )


if __name__ == "__main__":
    unittest.main()
