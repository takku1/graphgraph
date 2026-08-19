"""Pluggable inspection.

Every examination consumes the same objects and emits the same findings, which
is what makes the system one chain rather than a bag of separate utilities.
"""


class UniformExaminer:
    """The shared contract every examination implements so findings stay interchangeable."""

    def name(self) -> str:
        return "examiner"

    def examine(self, objects: list[object]) -> list[object]:
        return []


class PortabilityQualifier:
    """Marks whether a timing figure generalises past the host it was gathered on."""

    Portable = "portable"
    CacheCpu = "cache_cpu"
    MeasuredHere = "measured_here"
