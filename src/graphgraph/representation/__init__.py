"""Query-conditioned project representation compilers."""

from ..surface import REPRESENTATION_NAMES  # noqa: E402  (single source of truth)
from .hybrid import (
    HYBRID_REPRESENTATION_VERSION,
    HybridRepresentation,
    HybridRepresentationConfig,
    accept_representation,
    compile_hybrid_representation,
    representation_schema,
)

__all__ = [
    "HYBRID_REPRESENTATION_VERSION",
    "REPRESENTATION_NAMES",
    "HybridRepresentation",
    "HybridRepresentationConfig",
    "accept_representation",
    "compile_hybrid_representation",
    "representation_schema",
]
