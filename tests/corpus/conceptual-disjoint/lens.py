"""Pluggable inspection.

Every analysis consumes the same objects and emits the same findings, which
is what makes the system one pipeline rather than a bag of tools. A new
lens of inspection is registered and applied uniformly.
"""


class UniformExaminer:
    """One registered analysis. Implementors are applied uniformly."""

    def name(self) -> str:
        return "examiner"

    def examine(self, objects: list[object]) -> list[object]:
        return []


class PortabilityQualifier:
    """Keeps a speed claim from being silently tied to one machine."""

    Portable = "portable"
    CacheCpu = "cache_cpu"
    MeasuredHere = "measured_here"
