"""Ranking of how firmly a finding is backed.

Sampled checks must never be presented as formal proof. The variants below are
ordered by strength of claim; two of them are terminal qualifiers rather than
rungs.
"""


class ConfidenceLadder:
    """Ranks how firmly a finding is backed, from direct sighting up to formal proof."""

    Observed = "observed"
    Inferred = "inferred"
    Sampled = "sampled"
    Proved = "proved"
    Measured = "measured"
    Refuted = "refuted"
    Unknown = "unknown"
