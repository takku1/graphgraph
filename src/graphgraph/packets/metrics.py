from __future__ import annotations

import re


def estimate_tokens(text: str) -> int:
    """Return GraphGraph's cheap deterministic packet-token proxy."""
    return len(re.findall(r"\w+|[^\s\w]", text))
