"""Packet token accounting for the acceptance harness.

The spec measures packet tokens with both ``cl100k_base`` and ``o200k_base`` and
lets the *worse* value control the gate. When ``tiktoken`` is unavailable we fall
back to GraphGraph's deterministic proxy and mark the count imprecise, so a
receipt never claims a real-tokenizer measurement it did not compute.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from graphgraph.packets import estimate_tokens

_ENCODINGS = ("cl100k_base", "o200k_base")


@lru_cache(maxsize=4)
def _encoder(name: str):
    import tiktoken

    return tiktoken.get_encoding(name)


@dataclass(frozen=True)
class TokenCount:
    """Controlling token count plus its per-encoding breakdown."""

    controlling: int
    precise: bool
    per_encoding: tuple[tuple[str, int], ...]

    @property
    def detail(self) -> str:
        if not self.precise:
            return f"proxy~{self.controlling}"
        return " ".join(f"{name}={value}" for name, value in self.per_encoding)


def count_tokens(text: str) -> TokenCount:
    """Return the worst real-encoder token count, or the labelled proxy."""
    try:
        import tiktoken  # noqa: F401
    except Exception:
        proxy = estimate_tokens(text)
        return TokenCount(proxy, precise=False, per_encoding=(("proxy", proxy),))
    per = tuple((name, len(_encoder(name).encode(text))) for name in _ENCODINGS)
    return TokenCount(max(v for _n, v in per), precise=True, per_encoding=per)
