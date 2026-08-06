"""Declarative per-language project conventions.

The scanner understands every language in
:data:`graphgraph.scanner.frontends.grammars.SUFFIX_LANGUAGE`. Everything the
atlas and status layers want to *say* about a scanned project — which
ecosystem it belongs to, where its executable entry points are, which of its
files are tests, and how a caller would run them — used to be one hand-written
branch per ecosystem, and only four ecosystems ever got a branch.

The consequence was not a cosmetic gap. A real 108-file Go application
reported **zero** entry points and 17 of its 61 test files, because
``_test.go`` was missing from a literal suffix tuple and no rule knew that a
package-level ``func main`` is a Go binary — while the scan underneath had
extracted every one of those symbols correctly. Adding Go by hand would have
left Java, C#, Ruby, PHP, Kotlin, Scala, Swift, C, and C++ failing in exactly
the same way, discoverable only by someone happening to scan one.

So the conventions live here as data, and
``tests/test_project_conventions.py`` asserts that every language the scanner
parses has an entry in :data:`LANGUAGE_CONVENTIONS`. A language cannot be
added to the scanner and stay silently invisible to this layer: the guard
fails first.

Two deliberate limits:

* Manifest *parsing* is genuinely per-format (TOML, JSON, line-oriented
  ``go.mod``, XML) and is not unified here. What the registry owns is the
  mapping from manifest filename to ecosystem, plus the ecosystem's test
  command. An ecosystem with no bespoke parser still gets detected, still
  reports its test command, and still contributes its languages — it just
  does not populate a name/version, which is honest rather than invented.
* A convention is a *candidate*, not proof. Everything derived from this
  table is reported with a confidence/basis field, the same way the rest of
  the atlas reports evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..scanner.frontends.grammars import SUFFIX_LANGUAGE


@dataclass(frozen=True)
class LanguageConventions:
    """How one language names its tests and its executable entry point.

    ``test_suffixes``/``test_prefixes`` match the *filename*, not the path;
    directory-based detection (``tests/``, ``spec/``) is language-agnostic and
    handled separately by the caller, so a language that only uses a test
    directory (Rust, whose unit tests are inline ``#[cfg(test)]`` modules with
    no filename convention at all) correctly declares no filename patterns
    rather than a made-up one.

    ``main_symbols`` is deliberately restricted to languages where the symbol
    is the *language-mandated* program entry (Go's ``func main``, Java's
    ``public static void main``, C's ``int main``) -- there is exactly one per
    binary and finding it is a fact.

    It is empty for languages whose entry point is declared somewhere more
    precise, even though a ``main`` function is common there. Python is the
    clearest case: ``def main()`` is a widespread *style* convention, so
    keying on it turned every benchmark script in this repository into an
    "entry point" (40+ rows of noise) while ``[project.scripts]`` in the
    manifest already gave the exact, authoritative answer. Rust is the same
    shape: ``src/main.rs`` is the crate binary, while ``build.rs`` and
    ``examples/*.rs`` also define ``fn main`` and are not what "where do I
    start?" means. A weaker signal that fires more often is not more coverage,
    it is a worse answer -- so the precise rule wins and the loose one is
    declined.

    ``main_paths`` are filename conventions that mark an entry point
    regardless of symbol (Rust's ``src/main.rs``, Swift's ``main.swift``).
    """

    test_suffixes: tuple[str, ...] = ()
    test_prefixes: tuple[str, ...] = ()
    main_symbols: tuple[str, ...] = ()
    main_paths: tuple[str, ...] = ()


#: Keyed by the scanner's own language names (``SUFFIX_LANGUAGE`` values).
#: Guarded for completeness by ``tests/test_project_conventions.py``.
LANGUAGE_CONVENTIONS: dict[str, LanguageConventions] = {
    "python": LanguageConventions(
        test_suffixes=("_test.py",),
        test_prefixes=("test_",),
        # No `main` symbol rule: `[project.scripts]` is authoritative and
        # exact, while `def main()` is a style convention that matches every
        # standalone script. See LanguageConventions.
        main_paths=("__main__.py",),
    ),
    "rust": LanguageConventions(
        # Unit tests are inline `#[cfg(test)]` modules; integration tests live
        # in `tests/`, which the shared directory rule already covers. No
        # filename convention exists, and inventing one would be wrong.
        # No `main` symbol rule either: build.rs and examples/*.rs define one
        # without being the crate's entry point.
        main_paths=("src/main.rs",),
    ),
    "javascript": LanguageConventions(
        test_suffixes=(".test.js", ".spec.js", ".test.jsx", ".spec.jsx"),
    ),
    "typescript": LanguageConventions(
        test_suffixes=(".test.ts", ".spec.ts"),
    ),
    "tsx": LanguageConventions(
        test_suffixes=(".test.tsx", ".spec.tsx"),
    ),
    "go": LanguageConventions(
        test_suffixes=("_test.go",),
        main_symbols=("main",),
    ),
    "java": LanguageConventions(
        test_suffixes=("Test.java", "Tests.java", "TestCase.java"),
        main_symbols=("main",),
    ),
    "c": LanguageConventions(
        test_suffixes=("_test.c",),
        test_prefixes=("test_",),
        main_symbols=("main",),
    ),
    "cpp": LanguageConventions(
        test_suffixes=("_test.cpp", "_test.cc", "_test.cxx"),
        test_prefixes=("test_",),
        main_symbols=("main",),
    ),
    "csharp": LanguageConventions(
        test_suffixes=("Test.cs", "Tests.cs"),
        main_symbols=("Main",),
    ),
    "ruby": LanguageConventions(
        test_suffixes=("_spec.rb", "_test.rb"),
    ),
    "php": LanguageConventions(
        test_suffixes=("Test.php",),
    ),
    "kotlin": LanguageConventions(
        test_suffixes=("Test.kt", "Tests.kt"),
        main_symbols=("main",),
    ),
    "scala": LanguageConventions(
        test_suffixes=("Spec.scala", "Test.scala"),
        main_symbols=("main",),
    ),
    "swift": LanguageConventions(
        test_suffixes=("Test.swift", "Tests.swift"),
        main_paths=("main.swift",),
    ),
}


@dataclass(frozen=True)
class EcosystemSpec:
    """One package ecosystem: how to recognize it and how to test it.

    ``parsed`` marks the ecosystems that have a bespoke manifest reader in
    :mod:`graphgraph.services.runtime_probes`. The rest are detected by
    manifest presence alone — enough to name the ecosystem and offer a test
    command, without claiming a name/version nobody parsed.
    """

    name: str
    manifests: tuple[str, ...]
    languages: tuple[str, ...] = ()
    test_command: str = ""
    test_command_basis: str = ""
    test_command_confidence: str = "manifest_default"
    parsed: bool = False
    #: Manifests matched by suffix rather than exact filename (``.csproj``).
    manifest_suffixes: tuple[str, ...] = field(default_factory=tuple)


ECOSYSTEMS: tuple[EcosystemSpec, ...] = (
    EcosystemSpec(
        "python", ("pyproject.toml",), ("python",),
        "python -m pytest", "Python package with indexed test files", "candidate", parsed=True,
    ),
    EcosystemSpec(
        "npm", ("package.json",), ("javascript", "typescript", "tsx"),
        # The exact `scripts.test` value wins when present; runtime_probes
        # reads it, and the caller prefers it over this fallback.
        "npm test", "package.json", "manifest_default", parsed=True,
    ),
    EcosystemSpec(
        "rust", ("Cargo.toml",), ("rust",),
        "cargo test", "Cargo.toml package", parsed=True,
    ),
    EcosystemSpec(
        "go", ("go.mod",), ("go",),
        "go test ./...", "go.mod module", parsed=True,
    ),
    EcosystemSpec(
        "maven", ("pom.xml",), ("java", "kotlin", "scala"),
        "mvn test", "pom.xml",
    ),
    EcosystemSpec(
        "gradle", ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"),
        ("java", "kotlin", "scala"), "gradle test", "Gradle build script",
    ),
    EcosystemSpec(
        "dotnet", (), ("csharp",), "dotnet test", ".NET project/solution file",
        manifest_suffixes=(".sln", ".csproj", ".fsproj"),
    ),
    EcosystemSpec(
        "bundler", ("Gemfile",), ("ruby",),
        "bundle exec rake test", "Gemfile", "candidate",
    ),
    EcosystemSpec(
        "composer", ("composer.json",), ("php",),
        "composer test", "composer.json", "candidate",
    ),
    EcosystemSpec(
        "swiftpm", ("Package.swift",), ("swift",),
        "swift test", "Package.swift",
    ),
    EcosystemSpec(
        "sbt", ("build.sbt",), ("scala",),
        "sbt test", "build.sbt",
    ),
    EcosystemSpec(
        "cmake", ("CMakeLists.txt",), ("c", "cpp"),
        "ctest", "CMakeLists.txt", "candidate",
    ),
)

#: Directory names that mark test material in any language.
TEST_DIRECTORY_PARTS: frozenset[str] = frozenset({"spec", "specs", "test", "tests", "__tests__"})


def detect_ecosystems(directory) -> list[EcosystemSpec]:
    """Return every ecosystem whose manifest is present, in registry order."""
    found: list[EcosystemSpec] = []
    for spec in ECOSYSTEMS:
        if any((directory / manifest).exists() for manifest in spec.manifests):
            found.append(spec)
            continue
        if spec.manifest_suffixes:
            try:
                entries = list(directory.iterdir())
            except OSError:
                continue
            if any(
                entry.is_file() and entry.suffix.casefold() in spec.manifest_suffixes
                for entry in entries
            ):
                found.append(spec)
    return found


def is_test_filename(filename: str) -> bool:
    """Whether a bare filename matches any language's test-naming convention."""
    lowered = filename.casefold()
    for conventions in LANGUAGE_CONVENTIONS.values():
        if any(lowered.endswith(suffix.casefold()) for suffix in conventions.test_suffixes):
            return True
        if any(lowered.startswith(prefix.casefold()) for prefix in conventions.test_prefixes):
            return True
    return False


def is_test_path(path: str) -> bool:
    """Whether a repo-relative path is test material, by directory or filename."""
    normalized = path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts:
        return False
    if any(part.casefold() in TEST_DIRECTORY_PARTS for part in parts[:-1]):
        return True
    return is_test_filename(parts[-1])


def _language_for_path(path: str) -> str:
    suffix = PurePosixPath(path.replace("\\", "/")).suffix.casefold()
    return SUFFIX_LANGUAGE.get(suffix, "")


def entry_point_kind(path: str, label: str, kind: str) -> str:
    """Classify a node as an executable entry point, or return "".

    Two independent signals, both declared per language in
    :data:`LANGUAGE_CONVENTIONS`: a filename that *is* an entry point by
    convention (``src/main.rs``), or a callable whose name is the language's
    main symbol (``func main`` in Go, ``static void Main`` in C#).
    """
    language = _language_for_path(path)
    conventions = LANGUAGE_CONVENTIONS.get(language)
    if conventions is None:
        return ""
    normalized = path.replace("\\", "/")
    for main_path in conventions.main_paths:
        if normalized == main_path or normalized.endswith("/" + main_path):
            return f"{language}_entry"
    if kind in {"function", "method"} and label in conventions.main_symbols:
        return f"{language}_entry"
    return ""


__all__ = [
    "ECOSYSTEMS",
    "LANGUAGE_CONVENTIONS",
    "TEST_DIRECTORY_PARTS",
    "EcosystemSpec",
    "LanguageConventions",
    "detect_ecosystems",
    "entry_point_kind",
    "is_test_filename",
    "is_test_path",
]
