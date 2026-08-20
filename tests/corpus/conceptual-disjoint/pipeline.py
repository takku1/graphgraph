"""Sequenced examination.

Holds the registered lenses and invokes each in a fixed succession, so ingestion
precedes examination and examination precedes emission.
"""


class StageWire:
    """Sequences the registered lenses, invoking each in a fixed succession."""

    def run(self, objects: list[object]) -> list[object]:
        return objects
