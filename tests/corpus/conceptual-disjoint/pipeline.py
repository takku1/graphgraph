"""Discovery stages in order.

A single structure wires the discovery stages together so each lens
runs after ingestion and before emission.
"""


class StageWire:
    """The orchestrator that sequences registered inspection lenses."""

    def run(self, objects: list[object]) -> list[object]:
        return objects
