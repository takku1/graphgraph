"""Structural guard: no language the scanner parses may be invisible upstream.

This file exists because of a specific failure shape, not a hypothetical one.
The scanner extracted every symbol in a real 108-file Go application
correctly, and the atlas still reported **zero** entry points and 17 of its
61 test files -- because `_test.go` was missing from a literal suffix tuple
and no rule knew what a Go binary looks like. The first fix was one more
hand-written Go branch, which would have left Java, C#, Ruby, PHP, Kotlin,
Scala, Swift, C, and C++ failing in exactly the same way, each discoverable
only by someone happening to scan one.

These tests make that class of gap fail here instead of in the field: adding
a language to the scanner without declaring its conventions breaks the build.
"""

from __future__ import annotations

import unittest

from graphgraph.scanner.frontends.grammars import SUFFIX_LANGUAGE
from graphgraph.services.ecosystems import (
    ECOSYSTEMS,
    LANGUAGE_CONVENTIONS,
    entry_point_kind,
    is_test_path,
)


class LanguageCoverageGuardTest(unittest.TestCase):
    def test_every_scanner_language_declares_conventions(self) -> None:
        scanner_languages = set(SUFFIX_LANGUAGE.values())
        missing = sorted(scanner_languages - set(LANGUAGE_CONVENTIONS))
        self.assertEqual(
            missing,
            [],
            "languages the scanner parses but services/ecosystems.py does not "
            f"describe: {missing}. Add a LanguageConventions entry so the atlas "
            "can see this language's tests and entry points.",
        )

    def test_no_convention_describes_a_language_the_scanner_cannot_parse(self) -> None:
        # The reverse direction: a stale entry for a language that was removed
        # is dead configuration that will quietly never match anything.
        scanner_languages = set(SUFFIX_LANGUAGE.values())
        extra = sorted(set(LANGUAGE_CONVENTIONS) - scanner_languages)
        self.assertEqual(extra, [], f"conventions for unparsed languages: {extra}")

    def test_every_ecosystem_maps_to_parsed_languages(self) -> None:
        scanner_languages = set(SUFFIX_LANGUAGE.values())
        for spec in ECOSYSTEMS:
            unknown = sorted(set(spec.languages) - scanner_languages)
            self.assertEqual(unknown, [], f"{spec.name} claims unparsed languages: {unknown}")

    def test_every_ecosystem_is_recognizable_and_runnable(self) -> None:
        for spec in ECOSYSTEMS:
            with self.subTest(ecosystem=spec.name):
                self.assertTrue(
                    spec.manifests or spec.manifest_suffixes,
                    f"{spec.name} has no manifest marker, so it can never be detected",
                )
                self.assertTrue(spec.test_command, f"{spec.name} declares no test command")
                self.assertTrue(spec.test_command_basis, f"{spec.name} test command has no basis")

    def test_ecosystem_names_are_unique(self) -> None:
        names = [spec.name for spec in ECOSYSTEMS]
        self.assertEqual(sorted(names), sorted(set(names)))


class TestFileRecognitionTest(unittest.TestCase):
    """One real, conventional test path per language, and its production twin.

    The production twin matters as much as the test path: a rule broad enough
    to match every file would pass the first assertion and be useless.
    """

    CASES = (
        ("python", "pkg/test_api.py", "pkg/api.py"),
        ("python", "pkg/api_test.py", "pkg/api.py"),
        ("go", "internal/app/run_test.go", "internal/app/run.go"),
        ("javascript", "src/router.test.js", "src/router.js"),
        ("javascript", "src/router.spec.js", "src/router.js"),
        ("typescript", "src/store.test.ts", "src/store.ts"),
        ("tsx", "src/App.test.tsx", "src/App.tsx"),
        ("java", "src/main/java/com/example/AppTest.java", "src/main/java/com/example/App.java"),
        ("csharp", "src/ServiceTests.cs", "src/Service.cs"),
        ("ruby", "lib/parser_spec.rb", "lib/parser.rb"),
        ("ruby", "lib/parser_test.rb", "lib/parser.rb"),
        ("php", "src/ClientTest.php", "src/Client.php"),
        ("kotlin", "src/ViewModelTest.kt", "src/ViewModel.kt"),
        ("scala", "src/ParserSpec.scala", "src/Parser.scala"),
        ("swift", "Sources/ClientTests.swift", "Sources/Client.swift"),
        ("c", "src/parser_test.c", "src/parser.c"),
        ("cpp", "src/engine_test.cpp", "src/engine.cpp"),
    )

    def test_conventional_test_paths_are_recognized(self) -> None:
        for language, test_path, _production in self.CASES:
            with self.subTest(language=language, path=test_path):
                self.assertTrue(is_test_path(test_path), f"{test_path} should read as test material")

    def test_production_paths_are_not_mistaken_for_tests(self) -> None:
        for language, _test_path, production in self.CASES:
            with self.subTest(language=language, path=production):
                self.assertFalse(is_test_path(production), f"{production} is production code")

    def test_rust_relies_on_the_shared_test_directory_rule(self) -> None:
        # Rust unit tests are inline `#[cfg(test)]` modules with no filename
        # convention; integration tests live in `tests/`. Declaring a fake
        # Rust filename suffix would be inventing a convention.
        self.assertTrue(is_test_path("tests/integration.rs"))
        self.assertFalse(is_test_path("src/lib.rs"))
        self.assertEqual(LANGUAGE_CONVENTIONS["rust"].test_suffixes, ())


class EntryPointRecognitionTest(unittest.TestCase):
    def test_symbol_and_path_conventions_both_resolve(self) -> None:
        cases = (
            ("cmd/widget/main.go", "main", "function", "go_entry"),
            ("src/main.rs", "main", "function", "rust_entry"),
            ("src/main/java/com/example/App.java", "main", "method", "java_entry"),
            ("src/Program.cs", "Main", "method", "csharp_entry"),
            ("src/app.kt", "main", "function", "kotlin_entry"),
            ("Sources/main.swift", "run", "function", "swift_entry"),
        )
        for path, label, kind, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(entry_point_kind(path, label, kind), expected)

    def test_ordinary_symbols_are_not_entry_points(self) -> None:
        cases = (
            ("internal/app/run.go", "Run", "function"),
            ("src/lib.rs", "helper", "function"),
            # A `main`-named *class* is not an executable entry point; only a
            # callable is.
            ("src/main/java/com/example/App.java", "main", "class"),
            # A language with no declared main symbol must not guess one.
            ("src/parser.rb", "main", "function"),
        )
        for path, label, kind in cases:
            with self.subTest(path=path, label=label):
                self.assertEqual(entry_point_kind(path, label, kind), "")

    def test_conventional_main_functions_do_not_flood_precise_ecosystems(self) -> None:
        # Caught on real repositories the first time this registry ran: keying
        # Python on `def main()` turned 40+ benchmark scripts in this project
        # into "entry points", and keying Rust on `fn main` promoted build.rs
        # and every examples/*.rs alongside the real src/main.rs. Both
        # languages declare their entry point somewhere exact -- Python in
        # [project.scripts], Rust at src/main.rs -- so the loose symbol rule
        # is strictly worse than no rule.
        loose = (
            ("benchmarks/some_benchmark.py", "main", "function"),
            ("scripts/relocate.py", "main", "function"),
            ("crates/app/build.rs", "main", "function"),
            ("crates/app/examples/demo.rs", "main", "function"),
        )
        for path, label, kind in loose:
            with self.subTest(path=path):
                self.assertEqual(entry_point_kind(path, label, kind), "")
        # ...while the precise signals still resolve.
        self.assertEqual(entry_point_kind("crates/app/src/main.rs", "main", "function"), "rust_entry")
        self.assertEqual(entry_point_kind("pkg/__main__.py", "run", "function"), "python_entry")

    def test_unknown_suffix_yields_no_entry_point(self) -> None:
        self.assertEqual(entry_point_kind("build/main.unknownext", "main", "function"), "")


if __name__ == "__main__":
    unittest.main()
