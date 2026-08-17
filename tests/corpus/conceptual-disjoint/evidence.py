"""How sure a conclusion is allowed to be.

Sampled checks must never be presented as a proof. The variants are ordered
by strength of claim; two of them are terminal qualifiers rather than rungs
on the confidence ladder.
"""


class ConfidenceLadder:
    """How well-supported a conclusion is."""

    Observed = "observed"
    Inferred = "inferred"
    Sampled = "sampled"
    Proved = "proved"
    Measured = "measured"
    Refuted = "refuted"
    Unknown = "unknown"
