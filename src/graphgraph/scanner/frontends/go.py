"""Go receiver-type inference.

Go binds methods to a receiver rather than nesting them in the type, so a
`e.Run()` call resolves only when `e`'s type is known. These patterns cover the
declaration shapes that name a type outright. Inference that would require
following a function's return type is deliberately excluded: a wrong receiver
type produces a wrong edge, and this extractor's contract is to drop evidence
rather than invent it.
"""

from __future__ import annotations

import re

# `e := Engine{}` / `e := &Engine{}` / `e := pkg.Engine{}` -- composite literal.
_GO_COMPOSITE_LITERAL = re.compile(
    r"\b([A-Za-z_]\w*)\s*:=\s*&?\s*(?:[a-z]\w*\.)?([A-Z]\w*)\s*\{"
)

# `var e Engine` / `var e *Engine` / `var e pkg.Engine`.
_GO_VAR_DECLARATION = re.compile(
    r"\bvar\s+([A-Za-z_]\w*)\s+\*?(?:[a-z]\w*\.)?([A-Z]\w*)\b"
)

# `func (r Engine) M(a Engine, b *Widget)` -- typed parameters and receiver.
# Restricted to the signature, so a composite literal in the body cannot be
# misread as a parameter declaration.
_GO_TYPED_BINDING = re.compile(
    r"\b([A-Za-z_]\w*)\s+\*?(?:[a-z]\w*\.)?([A-Z]\w*)\s*(?=[,)])"
)


# `x := NewEngine()` / `x, err := pkg.Open()` -- a local bound to a call's
# result. The `(` is what separates this from the composite-literal form above;
# `for i := 0` and `x := y` have no call to type from.
_GO_CALL_ASSIGNMENT = re.compile(
    r"\b(?P<variable>[A-Za-z_]\w*)\s*(?:,\s*[A-Za-z_]\w*\s*)*:=\s*"
    r"(?:[A-Za-z_]\w*\.)?(?P<function>[A-Za-z_]\w*)\s*\("
)

# A single nominal type: `Engine`, `*Engine`, `pkg.Engine`. Slices, maps and
# channels deliberately fail to match -- `[]*Widget` does not own `Widget`'s
# methods, so binding it would manufacture a wrong edge.
_GO_NOMINAL_TYPE = re.compile(r"^\*?(?:[a-z]\w*\.)?([A-Z]\w*)$")


def go_return_type_name(result_text: str) -> str:
    """The nominal type a Go signature's result names, or "" when it names none.

    Go declares results explicitly, so this is a read of the signature rather
    than an inference about the body -- the distinction this module's contract
    turns on. Multi-value results are reduced to their first component, which
    is what `w, err := Open()` binds; the trailing `error`/`ok` conventionally
    carries no methods worth resolving.
    """
    text = result_text.strip()
    if not text:
        return ""
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].split(",", 1)[0].strip()
    match = _GO_NOMINAL_TYPE.match(text)
    return match.group(1) if match else ""


def go_local_call_return_types(body: str, return_types: dict[str, str]) -> dict[str, str]:
    """Receivers typed by the declared result of the function they were bound to.

    `x := NewEngine()` is how Go idiomatically binds almost every local, and it
    was the tool's single largest unresolved shape: `:=` was only understood in
    its composite-literal form (`x := Engine{}`). Only names with one concrete
    return type repo-wide appear in *return_types*, so an overloaded or
    ambiguous name still resolves to nothing rather than to a guess -- the same
    rule Rust and TypeScript already apply here.
    """
    inferred: dict[str, str] = {}
    for match in _GO_CALL_ASSIGNMENT.finditer(body):
        return_type = return_types.get(match.group("function"), "")
        if return_type:
            inferred.setdefault(match.group("variable"), return_type)
    return inferred


def go_local_types(body: str) -> dict[str, str]:
    """Receiver types bound in one Go function body.

    Only nominal types are returned: a leading capital distinguishes a declared
    type from a builtin such as `int` or `string`, which own no methods in the
    graph. Pointer and package qualifiers are stripped because `Engine`,
    `*Engine` and `pkg.Engine` name the same owner for method matching.
    """
    result: dict[str, str] = {}
    signature = body.split("{", 1)[0]
    for name, type_name in _GO_TYPED_BINDING.findall(signature):
        result.setdefault(name, type_name)
    for pattern in (_GO_COMPOSITE_LITERAL, _GO_VAR_DECLARATION):
        for name, type_name in pattern.findall(body):
            result.setdefault(name, type_name)
    return result
