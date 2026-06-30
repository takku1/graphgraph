from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

SCRIPTS = [
    "format_benchmark.py",
    "protocol_benchmark.py",
    "interpretability_benchmark.py",
    "bitpack_benchmark.py",
    "packet_roundtrip_validator.py",
    "source_route_benchmark.py",
    "constraint_context_benchmark.py",
    "model_reasoning_benchmark.py",
    "prompt_preflight.py",
    "adaptive_policy_report.py",
    "final_packet_benchmark.py",
    "live_graph_shape.py",
    "search_hot_path_benchmark.py",
    "minmax_analysis.py",
    "adaptive_threshold_sweep.py",
    "mathematical_limit_search.py",
    "real_project_packet_balance.py",
    "hop_frontier_benchmark.py",
    "adaptive_hop_policy_benchmark.py",
    "token_proxy_calibration.py",
    "real_project_answerability_limit.py",
    "dynamic_budget_benchmark.py",
    "planner_fit_benchmark.py",
    "frontier_policy_benchmark.py",
    "doc_code_pairing_benchmark.py",
    "integration_inventory.py",
]


def main() -> None:
    for script in SCRIPTS:
        path = ROOT / script
        print(f"\n=== {script} ===", flush=True)
        subprocess.run([sys.executable, str(path)], cwd=ROOT.parent.parent, check=True)


if __name__ == "__main__":
    main()
