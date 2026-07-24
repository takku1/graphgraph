"""Machine-oriented CLI serialization helpers."""

from __future__ import annotations

import json


def emit_json(payload: object, pretty: bool = False) -> None:
    """Print compact JSON unless a human explicitly requests indentation."""
    if pretty:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
