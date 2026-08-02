"""Small, explicit external API summaries used as receiver evidence.

Summaries describe semantics that syntax alone cannot recover.  They are
package-qualified and opt-in; an arbitrary same-named local helper never gains
the summarized behavior.
"""

from __future__ import annotations

import re

_ID = r"[A-Za-z_$][\w$]*"
_REQUIRE_BINDING = re.compile(
    rf"(?:\b(?:const|let|var)\s+|,\s*)({_ID})\s*=\s*require\(\s*['\"]([^'\"]+)['\"]\s*\)"
)
_IMPORT_DEFAULT = re.compile(
    rf"\bimport\s+({_ID})\s+from\s+['\"]([^'\"]+)['\"]"
)
_IMPORT_NAMESPACE = re.compile(
    rf"\bimport\s+\*\s+as\s+({_ID})\s+from\s+['\"]([^'\"]+)['\"]"
)

_EXTERNAL_TYPE_PREFIX = "external::"

# Default exports whose call copies enumerable/member descriptors from the
# second argument into the first.  Each entry is an external package identity,
# not a helper-name heuristic.
JAVASCRIPT_PROPERTY_COPY_PACKAGES = frozenset(
    {
        "merge-descriptors",
        "object-assign",
    }
)

# Package-qualified nominal APIs.  This is deliberately a tiny registry of
# version-stable public contracts; unknown packages and methods abstain.
JAVASCRIPT_EXTERNAL_TYPE_METHODS: dict[tuple[str, str], frozenset[str]] = {
    ("router", "Router"): frozenset({"handle", "route", "use"}),
}

# Callable package exports whose returned application object follows the
# structural request/response registration protocol detected in-project.
JAVASCRIPT_HANDLER_PACKAGES = frozenset({"express"})


def javascript_property_copy_helpers(text: str) -> frozenset[str]:
    helpers: set[str] = set()
    for pattern in (_REQUIRE_BINDING, _IMPORT_DEFAULT):
        for alias, package in pattern.findall(text):
            if package in JAVASCRIPT_PROPERTY_COPY_PACKAGES:
                helpers.add(alias)
    return frozenset(helpers)


def javascript_external_type_bindings(text: str) -> dict[str, tuple[str, str]]:
    """Map local constructor names to package-qualified summarized types."""
    result: dict[str, tuple[str, str]] = {}
    for pattern in (_REQUIRE_BINDING, _IMPORT_DEFAULT):
        for alias, package in pattern.findall(text):
            key = (package, alias)
            if key in JAVASCRIPT_EXTERNAL_TYPE_METHODS:
                result[alias] = key
    return result


def javascript_external_module_bindings(text: str) -> dict[str, str]:
    """Return import aliases proven to cross the repository boundary.

    This is syntax-level provenance, not a guessed API catalog. A non-relative
    CommonJS/ESM specifier names a package or runtime module, so calls on that
    namespace (and on the result of invoking it) cannot target a coincidentally
    same-named method in the current repository.
    """
    result: dict[str, str] = {}
    for pattern in (_REQUIRE_BINDING, _IMPORT_DEFAULT, _IMPORT_NAMESPACE):
        for alias, specifier in pattern.findall(text):
            if specifier.startswith((".", "/")):
                continue
            package = specifier.split("/", 1)[0]
            if package.startswith("@"):  # scoped npm package: @scope/name
                parts = specifier.split("/")
                package = "/".join(parts[:2]) if len(parts) >= 2 else specifier
            result.setdefault(alias, package)
    return result


def javascript_external_receiver_types(
    text: str,
    module_bindings: dict[str, str] | None = None,
) -> dict[str, str]:
    """Bind external module aliases and locals assigned from invoking them."""
    modules = module_bindings if module_bindings is not None else javascript_external_module_bindings(text)
    result = {
        alias: f"{_EXTERNAL_TYPE_PREFIX}{package}::module"
        for alias, package in modules.items()
    }
    for local, callee in re.findall(
        rf"\b(?:const|let|var)\s+({_ID})\s*=\s*"
        rf"(?:(?:module\.)?exports\s*=\s*)?(?:await\s+)?({_ID})\s*\(",
        text,
    ):
        if package := modules.get(callee):
            result.setdefault(local, f"{_EXTERNAL_TYPE_PREFIX}{package}::return")
    return result


def javascript_external_receiver(type_name: str) -> tuple[str, str] | None:
    """Decode a receiver type backed directly by import/value-flow facts."""
    if not type_name.startswith(_EXTERNAL_TYPE_PREFIX):
        return None
    encoded = type_name[len(_EXTERNAL_TYPE_PREFIX) :]
    package, separator, value_kind = encoded.partition("::")
    if not separator or not package or value_kind not in {"module", "return"}:
        return None
    return package, value_kind


def javascript_external_method(
    type_name: str,
    method: str,
    bindings: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    binding = bindings.get(type_name)
    if binding is None:
        return None
    methods = JAVASCRIPT_EXTERNAL_TYPE_METHODS.get(binding, frozenset())
    return binding if method in methods else None


__all__ = [
    "JAVASCRIPT_PROPERTY_COPY_PACKAGES",
    "JAVASCRIPT_EXTERNAL_TYPE_METHODS",
    "JAVASCRIPT_HANDLER_PACKAGES",
    "javascript_external_method",
    "javascript_external_module_bindings",
    "javascript_external_receiver",
    "javascript_external_receiver_types",
    "javascript_external_type_bindings",
    "javascript_property_copy_helpers",
]
