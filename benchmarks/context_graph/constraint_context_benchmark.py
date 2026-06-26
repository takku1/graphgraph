from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from protocol_benchmark import OUT, ROOT, get_token_counter


CONSTRAINT_OUT = OUT / "constraints"
RESULTS_CSV = CONSTRAINT_OUT / "constraint_context_results.csv"
SUMMARY_MD = CONSTRAINT_OUT / "constraint_context_summary.md"
POLICIES_JSON = CONSTRAINT_OUT / "policy_records.json"


POLICIES = [
    {
        "id": "P001",
        "kind": "frontend_visual",
        "priority": "must",
        "applies_to": ["src/ui/**", "src/components/**", "app/**/*.tsx"],
        "task_tags": ["frontend", "design", "css"],
        "compact": "UI: use approved color tokens, 8px max card radius, no decorative gradient blobs.",
        "content": (
            "Frontend UI must use approved color tokens, restrained spacing, cards at 8px radius or less, "
            "and no decorative gradient blobs. Text must not overlap controls on mobile or desktop."
        ),
    },
    {
        "id": "P002",
        "kind": "frontend_accessibility",
        "priority": "must",
        "applies_to": ["src/ui/**", "src/components/**", "app/**/*.tsx"],
        "task_tags": ["frontend", "accessibility"],
        "compact": "A11Y: controls need labels, focus states, contrast, and keyboard access.",
        "content": (
            "Interactive controls need accessible names, visible focus states, sufficient contrast, and keyboard access. "
            "Icon-only buttons must expose tooltips or aria labels."
        ),
    },
    {
        "id": "P003",
        "kind": "api_contract",
        "priority": "must",
        "applies_to": ["src/api/**", "server/**", "routes/**"],
        "task_tags": ["api", "backend"],
        "compact": "API: preserve response shape and error codes unless migration docs are updated.",
        "content": (
            "API handlers must preserve public response shape, status codes, and error identifiers unless a migration "
            "document and compatibility note are updated in the same change."
        ),
    },
    {
        "id": "P004",
        "kind": "security",
        "priority": "must",
        "applies_to": ["src/auth/**", "server/auth/**", "routes/auth/**"],
        "task_tags": ["auth", "security", "backend"],
        "compact": "SEC: never log secrets; token changes need expiry, revocation, and audit coverage.",
        "content": (
            "Authentication code must not log tokens, passwords, or signing secrets. Token changes need expiry, "
            "revocation, and audit-log coverage."
        ),
    },
    {
        "id": "P005",
        "kind": "testing",
        "priority": "should",
        "applies_to": ["tests/**", "src/**", "server/**", "routes/**"],
        "task_tags": ["test", "bugfix", "backend", "frontend"],
        "compact": "TEST: changed behavior needs focused regression tests near the owning module.",
        "content": (
            "Behavior changes should include focused regression tests near the owning module. Shared contracts need "
            "tests at the boundary, not only at the implementation."
        ),
    },
    {
        "id": "P006",
        "kind": "llm_answer_values",
        "priority": "must",
        "applies_to": ["**"],
        "task_tags": ["answering", "agent"],
        "compact": "LLM: cite local evidence, state uncertainty, avoid inventing files or edges.",
        "content": (
            "When answering from project context, cite local evidence, state uncertainty clearly, and do not invent "
            "files, nodes, dependencies, APIs, or graph edges."
        ),
    },
]


TASKS = [
    {
        "id": "frontend_button",
        "question": "Update the billing settings button styling.",
        "paths": ["src/components/BillingButton.tsx"],
        "tags": ["frontend", "design"],
        "expected_policies": ["P001", "P002", "P005"],
    },
    {
        "id": "auth_token",
        "question": "Change token refresh behavior.",
        "paths": ["server/auth/tokens.py"],
        "tags": ["auth", "security", "backend"],
        "expected_policies": ["P003", "P004", "P005"],
    },
    {
        "id": "api_error",
        "question": "Adjust API error handling for export jobs.",
        "paths": ["routes/export.py"],
        "tags": ["api", "backend", "bugfix"],
        "expected_policies": ["P003", "P005"],
    },
    {
        "id": "general_question",
        "question": "Explain how the graph packet is assembled.",
        "paths": ["benchmarks/context_graph/protocol_benchmark.py"],
        "tags": ["answering", "agent"],
        "expected_policies": ["P006"],
    },
]


def path_matches(pattern: str, path: str) -> bool:
    if pattern == "**":
        return True
    prefix = pattern.split("**", 1)[0]
    return path.startswith(prefix)


def policy_applies(policy: dict, task: dict) -> bool:
    path_hit = any(path_matches(pattern, path) for pattern in policy["applies_to"] for path in task["paths"])
    tag_hit = bool(set(policy["task_tags"]) & set(task["tags"]))
    return path_hit and tag_hit


def render_policy(policy: dict, compact: bool) -> str:
    if compact:
        return f"{policy['id']}:{policy['priority']}:{policy['compact']}"
    return f"{policy['id']} [{policy['kind']}] {policy['priority']}: {policy['content']}"


def select_policies(task: dict, strategy: str) -> list[dict]:
    if strategy == "none":
        return []
    if strategy == "global_all":
        return POLICIES
    if strategy in {"scoped_verbose", "scoped_compact"}:
        return [policy for policy in POLICIES if policy_applies(policy, task)]
    raise ValueError(f"unknown strategy {strategy}")


def run() -> list[dict]:
    tokenizer, count_tokens = get_token_counter()
    CONSTRAINT_OUT.mkdir(parents=True, exist_ok=True)
    POLICIES_JSON.write_text(json.dumps(POLICIES, indent=2), encoding="utf-8")
    rows = []
    for task in TASKS:
        expected = set(task["expected_policies"])
        for strategy in ["none", "global_all", "scoped_verbose", "scoped_compact"]:
            selected = select_policies(task, strategy)
            compact = strategy == "scoped_compact"
            packet = "\n".join(render_policy(policy, compact=compact) for policy in selected)
            selected_ids = {policy["id"] for policy in selected}
            policy_recall = len(expected & selected_ids) / max(1, len(expected))
            irrelevant = len(selected_ids - expected) / max(1, len(selected_ids)) if selected_ids else 0.0
            rows.append(
                {
                    "task": task["id"],
                    "strategy": strategy,
                    "tokenizer": tokenizer,
                    "tokens": count_tokens(packet) if packet else 0,
                    "selected_policy_count": len(selected),
                    "expected_policy_count": len(expected),
                    "policy_recall": round(policy_recall, 4),
                    "irrelevant_policy_ratio": round(irrelevant, 4),
                    "selected_policies": " ".join(sorted(selected_ids)),
                    "expected_policies": " ".join(sorted(expected)),
                }
            )
    return rows


def avg(items: list[dict], key: str) -> float:
    return sum(float(item[key]) for item in items) / max(1, len(items))


def write(rows: list[dict]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["strategy"]].append(row)

    lines = [
        "# Constraint Context Benchmark",
        "",
        f"Tokenizer: `{rows[0]['tokenizer']}`",
        "",
        "This measures whether storing project standards, UI rules, security rules, and LLM answer values helps when policies are scoped instead of globally dumped.",
        "",
        "| Strategy | Avg tokens | Policy recall | Irrelevant policy ratio | Avg selected policies |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for strategy, items in sorted(grouped.items()):
        lines.append(
            f"| {strategy} | {avg(items, 'tokens'):.1f} | {avg(items, 'policy_recall'):.3f} | "
            f"{avg(items, 'irrelevant_policy_ratio'):.3f} | {avg(items, 'selected_policy_count'):.1f} |"
        )

    lines.extend(
        [
            "",
            "Read:",
            "",
            "- Storing standards has value when policies have scope metadata and are retrieved by path/task tags.",
            "- `global_all` is the anti-pattern: high recall, but repeated irrelevant policy tokens.",
            "- `scoped_compact` is the target shape for an LLM-facing constraint packet.",
            "- `llm_answer_values` should usually be a cached global prefix or a scoped answering policy, not repeated inside every graph packet.",
            "",
            f"CSV: `{RESULTS_CSV.relative_to(ROOT)}`",
            f"Policy records: `{POLICIES_JSON.relative_to(ROOT)}`",
        ]
    )
    SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run()
    write(rows)
    print(SUMMARY_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
