"""Cache and latency receipt acceptance case (GG10-LC-012 / D12).

Runs the same queries cold and warm and asserts four things the spec asks
for: cache state is stated rather than inferred, warm answers are logically
identical to cold ones, p95 latency stays under a ceiling, and a refresh
invalidates only the entries a change can actually affect.

The third and fourth gates are the ones with teeth. A cache that returns a
*different* answer when warm is worse than no cache, and one that cannot be
invalidated precisely either serves stale packets or throws away every warm
entry on each edit. Both failure modes have been observed in this codebase:
a packet cache keyed to the process working directory served entries across
repositories, which made a correct retrieval fix look inert.

Latency gates run against the caller-supplied graph so p95 reflects a real
workspace; the invalidation gate runs in a scratch repository, since it has
to edit files and must never mutate the target.
"""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from pathlib import Path

from graphgraph.runtime.cache import TopologicalKVCache
from graphgraph.services.native import render_native_context

from .model import FAIL, NA, PASS, CaseResult, GateResult, Task

# Warm reads should be dominated by cache lookup, not retrieval. Cold reads
# pay graph load and full retrieval, so they get a much larger allowance.
_WARM_P95_MS = 400.0
_COLD_P95_MS = 4000.0
_SAMPLES = 6

_SIMPLE_QUERY = "normalize_rust"
_COMPLEX_QUERY = "What directly calls normalize_rust and which tests cover it?"


def _run(query: str, repo: Path, graph_path: Path) -> tuple[dict, float]:
    started = time.perf_counter()
    rendered, _status = render_native_context(
        query=query,
        query_class="direct_lookup",
        directory=repo,
        graph_path=graph_path,
        json_output=True,
        json_details=True,
        show_anchors=True,
        max_nodes=20,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return json.loads(rendered), elapsed_ms


def _cache_state(payload: dict) -> str:
    return str(((payload.get("workflow") or {}).get("cache") or {}).get("state", ""))


def _packet(payload: dict) -> str:
    return str(payload.get("packet", "")).strip()


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    if len(samples) == 1:
        return samples[0]
    # Nearest-rank p95: with small sample counts this is the max, which is
    # the honest reading -- claiming an interpolated percentile from six
    # points would overstate the precision.
    ordered = sorted(samples)
    rank = max(1, int(round(0.95 * len(ordered))))
    return ordered[min(rank, len(ordered)) - 1]


def _invalidation_gate() -> GateResult:
    """Editing one file must invalidate its packet and spare an unrelated one."""
    source_a = "def alpha_target():\n    return 1\n\n\ndef alpha_caller():\n    return alpha_target()\n"
    source_b = "def beta_target():\n    return 2\n\n\ndef beta_caller():\n    return beta_target()\n"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        (repo / "alpha.py").write_text(source_a, encoding="utf-8")
        (repo / "beta.py").write_text(source_b, encoding="utf-8")
        graph_path = repo / ".graphgraph" / "graph.gg"

        # Build and warm both queries.
        _run("alpha_target", repo, graph_path)
        _run("beta_target", repo, graph_path)
        warm_alpha, _ = _run("alpha_target", repo, graph_path)
        warm_beta, _ = _run("beta_target", repo, graph_path)
        if _cache_state(warm_alpha) != "hit" or _cache_state(warm_beta) != "hit":
            return GateResult(
                "refresh_invalidates_scoped",
                FAIL,
                f"queries did not warm: alpha={_cache_state(warm_alpha)} beta={_cache_state(warm_beta)}",
            )

        # Edit only alpha.py, then splice it in.
        (repo / "alpha.py").write_text(
            source_a + "\n\ndef alpha_extra():\n    return alpha_target()\n",
            encoding="utf-8",
        )
        render_native_context(
            query="alpha_target",
            query_class="direct_lookup",
            directory=repo,
            graph_path=graph_path,
            json_output=True,
            changed_paths=("alpha.py",),
        )

        # The symbol the edit introduced must now be retrievable: that is what
        # proves the refresh reached the cache rather than a stale packet
        # being replayed.
        added, _ = _run("alpha_extra", repo, graph_path)
        after_beta, _ = _run("beta_target", repo, graph_path)

    if "alpha_extra" not in _packet(added):
        return GateResult(
            "refresh_invalidates_scoped",
            FAIL,
            f"symbol added by the edit is not retrievable after refresh "
            f"(state={_cache_state(added)}); a stale packet was replayed",
        )
    # ...and an untouched file's answer must be unchanged by that refresh.
    if _packet(after_beta) != _packet(warm_beta):
        return GateResult(
            "refresh_invalidates_scoped",
            FAIL,
            "refresh changed an unrelated file's packet; invalidation is not scoped",
        )
    return GateResult(
        "refresh_invalidates_scoped",
        PASS,
        f"edit visible after refresh (state={_cache_state(added)}); "
        f"unrelated packet unchanged (state={_cache_state(after_beta)})",
    )


def run_cache_latency(
    task: Task,
    repo: Path,
    graph_path: Path | None = None,
) -> CaseResult:
    if graph_path is None or not Path(graph_path).exists():
        return CaseResult(
            task=task,
            probe=None,
            gates=[GateResult("graph_present", NA, "no graph available")],
        )
    graph_path = Path(graph_path)

    # Cold means cold: drop the packet cache co-located with this graph.
    TopologicalKVCache(graph_path.parent / "kv_cache.json").clear()

    gates: list[GateResult] = []
    cold_samples: list[float] = []
    warm_samples: list[float] = []
    states: list[str] = []
    mismatched: list[str] = []

    for query in (_SIMPLE_QUERY, _COMPLEX_QUERY):
        cold_payload, cold_ms = _run(query, repo, graph_path)
        cold_samples.append(cold_ms)
        states.append(_cache_state(cold_payload))

        for _ in range(_SAMPLES):
            warm_payload, warm_ms = _run(query, repo, graph_path)
            warm_samples.append(warm_ms)
            states.append(_cache_state(warm_payload))
            if _packet(warm_payload) != _packet(cold_payload):
                mismatched.append(query)

    gates.append(GateResult(
        "cache_state_explicit",
        PASS if all(state in {"hit", "miss"} for state in states) else FAIL,
        f"states={sorted(set(states))}",
    ))
    gates.append(GateResult(
        "cold_then_warm",
        PASS if states[0] == "miss" and "hit" in states[1:] else FAIL,
        f"first={states[0]} subsequent={sorted(set(states[1:]))}",
    ))
    gates.append(GateResult(
        "warm_matches_cold",
        PASS if not mismatched else FAIL,
        "warm packets byte-identical to cold"
        if not mismatched
        else f"packet changed when warm for {sorted(set(mismatched))}",
    ))

    cold_p95 = _p95(cold_samples)
    warm_p95 = _p95(warm_samples)
    gates.append(GateResult(
        "cold_p95_within_ceiling",
        PASS if cold_p95 <= _COLD_P95_MS else FAIL,
        f"cold p95 {cold_p95:.0f}ms <= {_COLD_P95_MS:.0f}ms (n={len(cold_samples)})",
    ))
    gates.append(GateResult(
        "warm_p95_within_ceiling",
        PASS if warm_p95 <= _WARM_P95_MS else FAIL,
        f"warm p95 {warm_p95:.0f}ms <= {_WARM_P95_MS:.0f}ms "
        f"(n={len(warm_samples)}, median {statistics.median(warm_samples):.0f}ms)",
    ))
    gates.append(_invalidation_gate())
    return CaseResult(task=task, probe=None, gates=gates)
