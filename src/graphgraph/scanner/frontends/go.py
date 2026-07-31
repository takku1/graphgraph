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
