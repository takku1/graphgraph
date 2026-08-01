"""Checks the per-language grammar profiles against the grammars themselves.

The union tables these replaced could not be validated: there was nothing to
ask "does this grammar actually define that node type," which is why
`record_struct_declaration` sat in the definition table for cycles without any
installed C# grammar defining it.
"""

from __future__ import annotations

import unittest

from graphgraph.scanner.frontends.grammars import (
    GRAMMARS,
    SUFFIX_LANGUAGE,
    UNION_PROFILE,
    _UNCLAIMED_BY_INTENT,
    _UNIVERSAL_CALLS,
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


if __name__ == "__main__":
    unittest.main()
