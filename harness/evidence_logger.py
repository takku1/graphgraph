#!/usr/bin/env python3
"""
evidence_logger.py — Mochi-Swarm & Locus compliant JSONL logger for RSS Back-Channel B.
Appends append-only evidence events to .measure/<component>/log.jsonl
"""

import os
import sys
import json
import datetime
from typing import Dict, Any, Optional

EVIDENCE_STAGES = [
    "Unknown", "Observed", "Sampled", "Inferred", "Measured", "Proved", "Refuted"
]

def log_event(
    component: str,
    event_type: str,
    metrics: Dict[str, Any],
    evidence_stage: str = "Measured",
    branch: str = "main",
    verdict: Optional[str] = None,
    reason: Optional[str] = None,
    log_dir: str = ".measure"
) -> str:
    if evidence_stage not in EVIDENCE_STAGES:
        raise ValueError(f"Invalid EvidenceStage: {evidence_stage}. Must be one of {EVIDENCE_STAGES}")

    comp_dir = os.path.join(log_dir, component)
    os.makedirs(comp_dir, exist_ok=True)
    log_file = os.path.join(comp_dir, "log.jsonl")

    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event_type": event_type,
        "component": component,
        "branch": branch,
        "evidence_stage": evidence_stage,
        "metrics": metrics,
    }
    if verdict:
        entry["verdict"] = verdict
    if reason:
        entry["reason"] = reason

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return log_file

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python evidence_logger.py <component> <event_type> '<metrics_json>' [evidence_stage] [branch]")
        sys.exit(1)

    comp = sys.argv[1]
    ev_type = sys.argv[2]
    mets = json.loads(sys.argv[3])
    stage = sys.argv[4] if len(sys.argv) > 4 else "Measured"
    br = sys.argv[5] if len(sys.argv) > 5 else "main"

    path = log_event(comp, ev_type, mets, stage, br)
    print(f"[EVIDENCE] Logged entry to {path}")
