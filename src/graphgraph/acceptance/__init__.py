"""Black-box acceptance harness for the GraphGraph 10/11 spec.

This package turns the canonical Locus regression cases
(``docs/bugs/2026-07-19-graphgraph-10-11-acceptance-spec.md``) into executable,
sealed-ground-truth gate checks. It drives GraphGraph only through its public
retrieval surface and never injects expected node IDs, golden paths, or fixture
answers as retrieval seeds — ground truth is used solely to *score* the packet
that was already produced.

Entry point::

    graphgraph platform acceptance --repo ../locus
"""

from .model import CaseResult, GateResult, GroundTruth, ProbeResult, Task
from .runner import run_case, run_probe
from .tokens import TokenCount, count_tokens

__all__ = [
    "CaseResult",
    "GateResult",
    "GroundTruth",
    "ProbeResult",
    "Task",
    "TokenCount",
    "count_tokens",
    "run_case",
    "run_probe",
]
