from __future__ import annotations

import re

from ..graph.core import Policy, Query


def path_matches(pattern: str, path: str) -> bool:
    if pattern == "**":
        return True
    if "**" not in pattern:
        return path == pattern
    # `pattern.split("**", 1)[0]` used to be the whole match: for a trailing
    # wildcard like "src/**" that's a correct prefix check, but for a
    # leading/middle wildcard like "**/tests/**" the text before the first
    # "**" is "", and path.startswith("") is True for every path -- so a
    # policy scoped to "**/tests/**" silently matched the entire repo instead
    # of just paths containing "tests/". Treat every "**" segment as a
    # wildcard run and require the literal segments around it to actually
    # appear, in order.
    segments = pattern.split("**")
    regex = ".*".join(re.escape(segment) for segment in segments)
    return re.fullmatch(regex, path) is not None


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
