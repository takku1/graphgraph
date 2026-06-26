from __future__ import annotations

from .core import Policy, Query


def path_matches(pattern: str, path: str) -> bool:
    if pattern == "**":
        return True
    if "**" in pattern:
        return path.startswith(pattern.split("**", 1)[0])
    return path == pattern


def policy_applies(policy: Policy, query: Query) -> bool:
    path_hit = any(path_matches(pattern, path) for pattern in policy.applies_to for path in query.paths)
    tag_hit = bool(set(policy.task_tags) & set(query.tags))
    return path_hit and tag_hit


def select_policies(policies: list[Policy], query: Query) -> list[Policy]:
    return [policy for policy in policies if policy_applies(policy, query)]


def render_policy_packet(policies: list[Policy], compact: bool = True) -> str:
    if compact:
        return "\n".join(f"{policy.id}:{policy.priority}:{policy.compact}" for policy in policies)
    return "\n".join(f"{policy.id} [{policy.kind}] {policy.priority}: {policy.content}" for policy in policies)
