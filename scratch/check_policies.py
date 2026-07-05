import csv
from pathlib import Path

csv_path = Path("benchmarks/context_graph/out/real_projects/frontier_policy_results.csv")
if not csv_path.exists():
    print("CSV not found")
    exit(1)

by_policy = {}
with csv_path.open(encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for r in reader:
        p = r["policy"]
        by_policy.setdefault(p, []).append(r)

for p, rows in sorted(by_policy.items()):
    ans = sum(1 for r in rows if r["answerable"].lower() == "true")
    print(f"{p}: {ans}/{len(rows)}")
