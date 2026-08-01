"""Per-language grammar profiles: which node types mean definition, name, call.

This replaces four global union tables that were shared by every language at
once. The union worked -- it is what shipped 15 languages -- but it has three
properties worth losing:

1. **A node type could only mean one thing.** `module` maps to `class`, which
   is right for Ruby and defensible for a TypeScript namespace. It is also the
   *root node of every Python file*. Nothing bad happens today, because the
   root has no name child and the collector skips it, but that is an accident
   of an unrelated check rather than a decision anyone made.
2. **It could not be validated.** There was no way to ask "does this grammar
   actually have that node type," so `record_struct_declaration` sat in the
   definition table without any installed grammar defining it. Per-language
   profiles can be checked against the grammars themselves, and
   `tests/test_grammar_profiles.py` does exactly that.
3. **Adding a language meant editing shared Python.** Now it is one entry here.

## How the split was derived, and why it is behaviour-preserving

Each profile is `(union & node kinds the installed grammar defines)`. A node
type the grammar does not define can never appear in a file of that language,
so removing it from that language's profile cannot change any output. That is
what makes this migration provably a no-op rather than a careful one -- see
`tests/corpus/polyglot.snapshot`.

Entries that **no** installed grammar claims are kept, assigned to the language
that owns them by intent (`_UNCLAIMED_BY_INTENT`). tree-sitter-ruby merged
`command` and `command_call` into `call`, and the C# grammar never had
`record_struct_declaration`. Dropping them would silently break anyone pinned
to a grammar version that still emits them, and keeping them costs one dict
entry that never matches. Grammar versions are not ours to assume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class GrammarProfile:
    """What one grammar's node types and binding forms mean to the extractor."""

    definitions: Mapping[str, str] = field(default_factory=dict)
    names: frozenset[str] = frozenset()
    calls: frozenset[str] = frozenset()
    path_qualified_calls: frozenset[str] = frozenset()

    # Names that denote the enclosing instance, bound to the owning type when
    # resolving a member call inside a method body. This was previously a chain
    # of `suffix in {...}` tests that knew about `self` (Python, Rust), `cls`
    # (Python) and `this` (TS/JS, C#, Java, C++) -- and therefore silently gave
    # Swift, PHP, Kotlin, Scala and Ruby no enclosing-instance binding at all.
    # Swift's `self.Handle()` and PHP's `$this->Handle()` both went unresolved
    # for exactly that reason.
    self_aliases: frozenset[str] = frozenset()

    # Sigils a variable reference may carry. PHP writes `$this`, which fails a
    # bare `[A-Za-z_]\w*` identifier test, so every PHP receiver was thrown
    # away before resolution could see it -- reported as `complex_expression`,
    # a bucket meaning "receiver text discarded", which was accurate and
    # entirely unhelpful.
    variable_sigils: frozenset[str] = frozenset()

    # Declarative field visibility. Language adapters emit field facts; these
    # values describe how those facts are spelled and which surrounding type
    # scopes make them visible. Resolution policy therefore stays out of the
    # per-language extractors and out of suffix ladders in the edge builder.
    field_receiver_prefixes: tuple[str, ...] = ()
    bare_field_receivers: bool = False
    inherited_field_receivers: bool = False

    def strip_sigil(self, name: str) -> str:
        """Return *name* without a leading sigil this language permits."""
        if name[:1] in self.variable_sigils:
            return name[1:]
        return name


# Node types no installed grammar defines, kept against grammar-version drift.
# Listed separately from the profiles so that a future validation run can tell
# "deliberately retained" apart from "typo nobody noticed".
_UNCLAIMED_BY_INTENT: Mapping[str, GrammarProfile] = {
    # tree-sitter-ruby consolidated parenthesis-free calls into `call`.
    "ruby": GrammarProfile(calls=frozenset({"command", "command_call"})),
    # Never present in tree-sitter-c-sharp; `record_declaration` covers
    # `record struct` in the grammar as installed.
    "csharp": GrammarProfile(definitions=MappingProxyType({"record_struct_declaration": "struct"})),
}

# `method_call` was carried as a "misc grammars" catch-all and is claimed by no
# grammar and no specific language. It is applied to every profile so that
# behaviour is bit-for-bit what the union produced.
_UNIVERSAL_CALLS = frozenset({"method_call"})


def _profile(
    definitions: Mapping[str, str],
    names: frozenset[str],
    calls: frozenset[str],
    path_qualified_calls: frozenset[str] = frozenset(),
    self_aliases: frozenset[str] = frozenset(),
    variable_sigils: frozenset[str] = frozenset(),
    field_receiver_prefixes: tuple[str, ...] = (),
    bare_field_receivers: bool = False,
    inherited_field_receivers: bool = False,
) -> GrammarProfile:
    return GrammarProfile(
        definitions=MappingProxyType(dict(definitions)),
        names=names,
        calls=calls | _UNIVERSAL_CALLS,
        path_qualified_calls=path_qualified_calls,
        self_aliases=self_aliases,
        variable_sigils=variable_sigils,
        field_receiver_prefixes=field_receiver_prefixes,
        bare_field_receivers=bare_field_receivers,
        inherited_field_receivers=inherited_field_receivers,
    )


# The three spellings of "the object this method was called on".
_SELF = frozenset({"self"})
_THIS = frozenset({"this"})


_IDENT = frozenset({"identifier"})
_C_NAMES = frozenset({"field_identifier", "identifier", "type_identifier"})
_JS_NAMES = frozenset({"identifier", "property_identifier", "shorthand_property_identifier"})
_TS_NAMES = _JS_NAMES | {"type_identifier"}

GRAMMARS: Mapping[str, GrammarProfile] = {
    "c": _profile(
        {"function_definition": "function", "struct_specifier": "struct"},
        _C_NAMES,
        frozenset({"call_expression"}),
    ),
    "cpp": _profile(
        {
            "class_specifier": "class",
            "function_definition": "function",
            "struct_specifier": "struct",
        },
        _C_NAMES,
        frozenset({"call_expression"}),
        # Namespace::function(...) and Class::static_method(...) name a
        # lexically fixed target, unlike receiver.method(...).
        frozenset({"qualified_identifier"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this->",),
        bare_field_receivers=True,
        inherited_field_receivers=True,
    ),
    "csharp": _profile(
        {
            "class_declaration": "class",
            "constructor_declaration": "method",
            "enum_declaration": "enum",
            "interface_declaration": "interface",
            "method_declaration": "method",
            "record_declaration": "class",
            "record_struct_declaration": "struct",  # retained: see module docstring
            "struct_declaration": "struct",
        },
        _IDENT,
        frozenset({"invocation_expression"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this.",),
        bare_field_receivers=True,
        inherited_field_receivers=True,
    ),
    "go": _profile(
        {
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": "type",
        },
        _C_NAMES,
        frozenset({"call_expression"}),
    ),
    "java": _profile(
        {
            "class_declaration": "class",
            "constructor_declaration": "method",
            "enum_declaration": "enum",
            "interface_declaration": "interface",
            "method_declaration": "method",
            "record_declaration": "class",
        },
        frozenset({"identifier", "type_identifier"}),
        frozenset({"method_invocation"}),
        frozenset({"scoped_identifier"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this.",),
        bare_field_receivers=True,
        inherited_field_receivers=True,
    ),
    "javascript": _profile(
        {
            "class": "class",
            "class_declaration": "class",
            "function_declaration": "function",
            "method_definition": "method",
        },
        _JS_NAMES,
        frozenset({"call_expression"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this.",),
        inherited_field_receivers=True,
    ),
    "kotlin": _profile(
        {
            "class_declaration": "class",
            "function_declaration": "function",
            "object_declaration": "class",
        },
        frozenset({"identifier", "simple_identifier", "type_identifier"}),
        frozenset({"call_expression"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this.",),
        inherited_field_receivers=True,
    ),
    "php": _profile(
        {
            "class_declaration": "class",
            "enum_declaration": "enum",
            "function_definition": "function",
            "interface_declaration": "interface",
            "method_declaration": "method",
            "trait_declaration": "trait",
        },
        # PHP names a bare callee `name`, not `identifier`; without it calls
        # parsed but never reached resolution.
        frozenset({"name"}),
        frozenset({
            "function_call_expression",
            "member_call_expression",
            "scoped_call_expression",
        }),
        self_aliases=frozenset({"$this"}),
        variable_sigils=frozenset({"$"}),
        field_receiver_prefixes=("$this->",),
        inherited_field_receivers=True,
    ),
    "python": _profile(
        {
            "class_definition": "class",
            "function_definition": "function",
            # The root node of every Python file. Inert: it has no name child,
            # so the definition collector skips it. Retained because removing
            # it would be a behaviour change, not a cleanup -- but it is the
            # clearest example of why these tables belong per-language.
            "module": "class",
        },
        _IDENT,
        frozenset({"call"}),
        self_aliases=frozenset({"self", "cls"}),
        field_receiver_prefixes=("self.",),
        inherited_field_receivers=True,
    ),
    "ruby": _profile(
        {
            "class": "class",
            # A top-level `def` parses as `method`, not `function`. An
            # ownerless method is a free function under another name.
            "method": "method",
            "module": "class",
            "singleton_method": "method",
        },
        frozenset({"constant", "identifier"}),
        frozenset({"call"}) | _UNCLAIMED_BY_INTENT["ruby"].calls,
        self_aliases=_SELF,
        field_receiver_prefixes=("self.",),
        inherited_field_receivers=True,
    ),
    "rust": _profile(
        {
            "enum_item": "enum",
            "function_item": "function",
            "function_signature_item": "method",
            "struct_item": "struct",
            "trait_item": "trait",
        },
        _C_NAMES,
        frozenset({"call_expression"}),
        frozenset({"scoped_identifier"}),
        self_aliases=_SELF,
        field_receiver_prefixes=("self.",),
    ),
    "scala": _profile(
        {
            "class_definition": "class",
            "function_declaration": "function",
            "function_definition": "function",
            "object_definition": "class",
            "trait_definition": "trait",
        },
        frozenset({"identifier", "type_identifier"}),
        frozenset({"call_expression"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this.",),
        inherited_field_receivers=True,
    ),
    "swift": _profile(
        {
            "class_declaration": "class",
            "function_declaration": "function",
            "protocol_declaration": "interface",
        },
        frozenset({"identifier", "simple_identifier", "type_identifier"}),
        frozenset({"call_expression"}),
        self_aliases=_SELF,
        field_receiver_prefixes=("self.",),
        inherited_field_receivers=True,
    ),
    "tsx": _profile(
        {
            "class": "class",
            "class_declaration": "class",
            "enum_declaration": "enum",
            "function_declaration": "function",
            "interface_declaration": "interface",
            "method_definition": "method",
            "module": "class",
        },
        _TS_NAMES,
        frozenset({"call_expression"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this.",),
        inherited_field_receivers=True,
    ),
    "typescript": _profile(
        {
            "class": "class",
            "class_declaration": "class",
            "enum_declaration": "enum",
            "function_declaration": "function",
            "interface_declaration": "interface",
            "method_definition": "method",
            "module": "class",
        },
        _TS_NAMES,
        frozenset({"call_expression"}),
        self_aliases=_THIS,
        field_receiver_prefixes=("this.",),
        inherited_field_receivers=True,
    ),
}


# Source suffix -> grammar name. Lives here rather than in `languages.py`
# because it is the same kind of fact as the profiles above, and because
# `syntax.py` needs it: `languages.py` imports *from* `syntax.py`, so the
# dependency could not run the other way.
SUFFIX_LANGUAGE: Mapping[str, str] = MappingProxyType({
    ".py": "python",
    ".rs": "rust",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".scala": "scala",
    ".swift": "swift",
})


def profile_for_language(language: str | None) -> GrammarProfile:
    """Profile for a language name, or the permissive union when unknown."""
    if language is None:
        return UNION_PROFILE
    return GRAMMARS.get(language, UNION_PROFILE)


def profile_for_suffix(suffix: str) -> GrammarProfile:
    """Profile for a source suffix, or the union for an unrecognised one.

    Falling back to the union rather than to an empty profile keeps an
    unrecognised suffix behaving exactly as it did before profiles existed.
    """
    return profile_for_language(SUFFIX_LANGUAGE.get(suffix.casefold()))


def _union() -> GrammarProfile:
    """Every profile merged.

    Kept because several callers legitimately do not know the language:
    `platform/cpg.py` walks nodes it was handed, and the regex extractor has no
    grammar at all. Those paths get exactly the behaviour they had before, and
    the union is now *derived* from the per-language tables rather than being
    the thing the per-language tables were carved out of.
    """
    definitions: dict[str, str] = {}
    names: set[str] = set()
    calls: set[str] = set()
    path_qualified: set[str] = set()
    self_aliases: set[str] = set()
    variable_sigils: set[str] = set()
    field_receiver_prefixes: set[str] = set()
    bare_field_receivers = False
    inherited_field_receivers = False
    for profile in GRAMMARS.values():
        definitions.update(profile.definitions)
        names |= profile.names
        calls |= profile.calls
        path_qualified |= profile.path_qualified_calls
        self_aliases |= profile.self_aliases
        variable_sigils |= profile.variable_sigils
        field_receiver_prefixes.update(profile.field_receiver_prefixes)
        bare_field_receivers = bare_field_receivers or profile.bare_field_receivers
        inherited_field_receivers = (
            inherited_field_receivers or profile.inherited_field_receivers
        )
    for profile in _UNCLAIMED_BY_INTENT.values():
        definitions.update(profile.definitions)
        names |= profile.names
        calls |= profile.calls
        path_qualified |= profile.path_qualified_calls
    return GrammarProfile(
        definitions=MappingProxyType(definitions),
        names=frozenset(names),
        calls=frozenset(calls),
        path_qualified_calls=frozenset(path_qualified),
        self_aliases=frozenset(self_aliases),
        variable_sigils=frozenset(variable_sigils),
        field_receiver_prefixes=tuple(sorted(field_receiver_prefixes)),
        bare_field_receivers=bare_field_receivers,
        inherited_field_receivers=inherited_field_receivers,
    )


UNION_PROFILE = _union()
