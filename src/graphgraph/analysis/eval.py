from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..concepts.doccode import is_code_like
from ..graph.core import Edge, Graph
from ..io import load_any
from ..packets import estimate_tokens
from ..packets.renderers import subsystem_node_order
from ..retrieval.anchors import packet_priority
from .calibration import calibration_report


@dataclass(frozen=True)
class EvalTask:
    query: str
    query_class: str
    expected_nodes: tuple[str, ...] = ()
    expected_edges: tuple[tuple[str, ...], ...] = ()
    expected_answerable: bool | None = None


@dataclass(frozen=True)
class EvalResult:
    query: str
    query_class: str
    node_recall: float | None
    edge_recall: float | None
    returned_nodes: int
    returned_edges: int
    token_estimate: int
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    scored: bool = True
    note: str = ""
    answerability_status: str = ""
    answerability_confidence: float | None = None
    expected_resolved_count: int = 0
    expected_unresolved_count: int = 0
    expected_unresolved: tuple[str, ...] = ()
    expected_answerable: bool | None = None


class EvalTasksError(ValueError):
    """The eval tasks file is unreadable, malformed, or empty of runnable tasks."""


def load_eval_tasks(path: Path) -> list[EvalTask]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalTasksError(f"could not read eval tasks from {path}: {exc}") from exc
    tasks = _iter_task_records(data)
    out: list[EvalTask] = []
    for task in tasks:
        query = task.get("query", task.get("question"))
        if not query:
            continue
        # `expected` is the obvious key to reach for, and reading only
        # `expected_nodes` silently produced an empty expectation set -- which
        # then scored as vacuously perfect. A harness that mis-reads its own
        # task file must not report a green number for it.
        expected_nodes = task.get("expected_nodes", task.get("expected", []))
        expected_edges = task.get("expected_edges", task.get("edges", []))
        expected_answerable = task.get("expected_answerable")
        if expected_answerable is not None and not isinstance(expected_answerable, bool):
            raise EvalTasksError(f"invalid expected_answerable for query {query!r}: expected true or false")
        out.append(
            EvalTask(
                query=str(query),
                # Default to routing, as `query` does. A hardcoded class made every
                # task in a suite classify identically regardless of its wording.
                query_class=str(task.get("query_class", "auto")),
                expected_nodes=tuple(str(item) for item in expected_nodes),
                expected_edges=tuple(tuple(str(part) for part in edge) for edge in expected_edges),
                expected_answerable=expected_answerable,
            )
        )
    if not out:
        # A benchmark over zero tasks would print an empty result and exit 0 --
        # one day reporting a "perfect" score on nothing. Refuse loudly instead:
        # the input was either an unrecognized schema or every task lacked a
        # 'query'. Callers all pass real suites, so this cannot be a legitimate
        # empty run.
        raise EvalTasksError(
            f"no runnable eval tasks in {path}: expected a JSON list of "
            '{"query": ...} objects (or {"tasks": [...]}), each with a "query" '
            'or "question" field'
        )
    return out


def _iter_task_records(data: object) -> list[dict[str, object]]:
    if isinstance(data, list):
        return [task for task in data if isinstance(task, dict)]
    if not isinstance(data, dict):
        return []
    tasks = data.get("tasks")
    if isinstance(tasks, list):
        return [task for task in tasks if isinstance(task, dict)]
    projects = data.get("projects")
    if isinstance(projects, dict):
        out: list[dict[str, object]] = []
        for project_tasks in projects.values():
            if isinstance(project_tasks, list):
                out.extend(task for task in project_tasks if isinstance(task, dict))
        return out
    return []


def evaluate_graph(
    graph_path: Path,
    tasks: list[EvalTask],
    max_nodes: int | None = None,
    *,
    source_mode: str = "auto",
) -> list[EvalResult]:
    # Import locally to preserve the lightweight analysis-module import path.
    # Evaluation must nevertheless execute the same compiler/source-planner
    # pipeline as `graphgraph query`; calling retrieve_context() directly made
    # the benchmark disagree with the shipped command whenever semantic/source
    # seeds changed the production anchors.
    from ..platform.compiler import GraphProgram
    from ..platform.runtime import create_graph_runtime

    graph = load_any(graph_path)
    runtime = create_graph_runtime(
        graph_path,
        graph=graph,
        enable_evidence=False,
        source_mode=source_mode,
        # Session/project memories are mutable user state. Keep the retrieval
        # benchmark deterministic while retaining production lexical/semantic
        # source planning.
        memory_scopes=(),
    )
    results: list[EvalResult] = []
    for task in tasks:
        compiled = runtime.compile(
            GraphProgram(
                query=task.query,
                query_class=task.query_class,
                packet=None,
                max_nodes=max_nodes,
            )
        )
        graph = compiled.graph
        retrieved = compiled.retrieval
        task = replace(task, query_class=compiled.route.query_class)
        answerability = retrieved.metadata.get("answerability", {})
        if not isinstance(answerability, dict):
            answerability = {}
        confidence = answerability.get("confidence")
        answerability_confidence = float(confidence) if isinstance(confidence, (int, float)) else None
        priority = packet_priority(
            retrieved.starts,
            retrieved.nodes,
            retrieved.edges,
            task.query_class,
            graph=graph,
        )
        packet = compiled.packet
        node_keys_by_id = {nid: _node_keys(graph, (nid,)) for nid in graph.nodes}
        returned_edges = {(edge.source, edge.target, edge.type) for edge in retrieved.edges}

        # Rank-aware metrics measure how far down the *packet the agent reads*
        # the answer sits, so rank by the packet's node emission order -- not a
        # PageRank re-ranking of the subgraph, which the agent never sees and
        # which buries a queried symbol's callers under the symbol itself.
        ranked_nodes = subsystem_node_order(graph, retrieved.nodes, priority=priority)

        # Resolve expectations against the *whole graph*, not only the packet.
        # A zero score can then be separated into two very different failures:
        # retrieval missed valid ground truth, or the declared ground truth did
        # not identify any node in the graph at all. The latter is an eval-data
        # defect and must not masquerade as a retrieval regression.
        expected_ids: set[str] = set()
        expected_groups: list[set[str]] = []
        expected_unresolved: list[str] = []
        for item in task.expected_nodes:
            matching_ids = _resolve_node_expectation_ids(graph, node_keys_by_id, item)
            expected_groups.append(matching_ids)
            if matching_ids:
                expected_ids.update(matching_ids)
            else:
                expected_unresolved.append(item)

        mrr_val = reciprocal_rank(ranked_nodes, expected_ids)
        ndcg_5 = ndcg_at_k(ranked_nodes, expected_ids, 5)
        ndcg_10 = ndcg_at_k(ranked_nodes, expected_ids, 10)

        node_recall = (
            None
            if not task.expected_nodes
            else sum(bool(group & retrieved.nodes) for group in expected_groups) / len(task.expected_nodes)
        )
        edge_recall = _edge_recall(task.expected_edges, returned_edges)
        scored = node_recall is not None or edge_recall is not None
        results.append(
            EvalResult(
                query=task.query,
                query_class=task.query_class,
                node_recall=node_recall,
                edge_recall=edge_recall,
                scored=scored,
                note=_eval_note(
                    scored=scored,
                    expected_unresolved=expected_unresolved,
                    expected_answerable=task.expected_answerable,
                ),
                returned_nodes=len(retrieved.nodes),
                returned_edges=len(retrieved.edges),
                token_estimate=estimate_tokens(packet),
                mrr=round(mrr_val, 4),
                ndcg_at_5=round(ndcg_5, 4),
                ndcg_at_10=round(ndcg_10, 4),
                answerability_status=str(answerability.get("status", "")),
                answerability_confidence=answerability_confidence,
                expected_resolved_count=len(task.expected_nodes) - len(expected_unresolved),
                expected_unresolved_count=len(expected_unresolved),
                expected_unresolved=tuple(expected_unresolved),
                expected_answerable=task.expected_answerable,
            )
        )
    return results


def reciprocal_rank(ranked_list: list[str], expected_nodes: set[str]) -> float:
    for idx, node_id in enumerate(ranked_list, start=1):
        if node_id in expected_nodes:
            return 1.0 / idx
    return 0.0


def ndcg_at_k(ranked_list: list[str], expected_nodes: set[str], k: int) -> float:
    import math

    k = min(len(ranked_list), k)
    if k <= 0 or not expected_nodes:
        return 0.0
    dcg = sum(
        1.0 / math.log2(idx + 1) for idx, node_id in enumerate(ranked_list[:k], start=1) if node_id in expected_nodes
    )
    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, min(k, len(expected_nodes)) + 1))
    return dcg / idcg if idcg > 0.0 else 0.0


def rank_nodes_by_subgraph_pagerank(graph: Graph, retrieved_nodes: set[str], retrieved_edges: list[Edge]) -> list[str]:
    active_nodes = {nid: graph.nodes[nid] for nid in retrieved_nodes if nid in graph.nodes}
    if not active_nodes:
        return []
    subgraph = Graph(
        nodes=active_nodes,
        edges=retrieved_edges,
    )
    pr = subgraph.pagerank(damping=0.85, max_iter=20, use_cache=False)
    # Total order, not just descending score. `retrieved_nodes` is a set, so
    # its iteration order varies with PYTHONHASHSEED across processes, and a
    # sort keyed on PageRank alone left ties (and near-ties the eval treats as
    # ties) to be broken by that non-deterministic order. The result: MRR/NDCG
    # oscillated on byte-identical input while node_recall stayed stable, which
    # made every rank-based gate unmeasurable below the noise band. The node_id
    # tiebreak makes the ranking a pure function of the graph.
    return sorted(retrieved_nodes, key=lambda nid: (-pr.get(nid, 0.0), nid))


def results_to_json(results: list[EvalResult]) -> str:
    return json.dumps([result.__dict__ for result in results], indent=2, ensure_ascii=False)


def calibration_pairs(results: list[EvalResult], *, complete_recall: float = 1.0) -> list[tuple[float, bool]]:
    """Pair answerability confidence with labeled retrieval completeness.

    The outcome is true only when every recall dimension declared by the eval
    task meets ``complete_recall``. Results without declared expectations or a
    confidence value are excluded. Runtime non-observation is deliberately not
    used as a negative label: a trace covers only paths that happened to run.
    """
    if not 0.0 <= complete_recall <= 1.0:
        raise ValueError("complete_recall must be in [0, 1]")
    pairs: list[tuple[float, bool]] = []
    for result in results:
        confidence = result.answerability_confidence
        if confidence is None:
            continue
        # Impossible/negative queries cannot name a valid expected node by
        # definition. They need an explicit label instead of a fabricated
        # nonexistent node expectation. This keeps true negatives in the
        # calibration set without pretending they are retrieval misses.
        if result.expected_answerable is False:
            pairs.append((confidence, False))
            continue
        # An expectation that resolves nowhere is invalid ground truth, not a
        # negative retrieval outcome. Including it would make calibration look
        # better or worse based on fixture typos and coarse path prefixes.
        if result.expected_unresolved_count:
            continue
        recalls = tuple(recall for recall in (result.node_recall, result.edge_recall) if recall is not None)
        if not recalls:
            continue
        pairs.append((confidence, all(recall >= complete_recall for recall in recalls)))
    return pairs


def results_with_calibration_to_json(results: list[EvalResult], *, bins: int = 10, complete_recall: float = 1.0) -> str:
    """Render eval results plus a calibration receipt over labeled tasks."""
    pairs = calibration_pairs(results, complete_recall=complete_recall)
    report = asdict(calibration_report(pairs, bins=bins))
    report["excluded_unresolved_expectation_tasks"] = sum(result.expected_unresolved_count > 0 for result in results)
    report["label_policy"] = {
        "source": "declared eval expectations plus explicit impossible-query labels",
        "complete_recall": complete_recall,
        "rule": (
            "expected_answerable=false is negative; otherwise all scored "
            "node/edge recall values must meet the threshold"
        ),
    }
    return json.dumps(
        {"results": [asdict(result) for result in results], "calibration": report},
        indent=2,
        ensure_ascii=False,
    )


def _edge_recall(expected: tuple[tuple[str, ...], ...], returned: set[tuple[str, str, str]]) -> float | None:
    if not expected:
        return None
    returned_pairs = {(source, target) for source, target, _type in returned}
    hits = 0
    for edge in expected:
        if len(edge) >= 3:
            if (edge[0], edge[1], edge[2]) in returned:
                hits += 1
        elif len(edge) == 2 and (edge[0], edge[1]) in returned_pairs:
            hits += 1
    return hits / len(expected)


def _node_keys(graph: Graph, node_ids: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for nid in node_ids:
        if not isinstance(nid, str):
            continue
        node = graph.nodes.get(nid)
        if node is None:
            continue
        keys.update((nid, node.label, node.path, _strip_known_suffix(node.label)))
        if node.path:
            keys.add(_strip_known_suffix(Path(node.path).name))
    return {key for key in keys if key}


def _node_expectation_matches(expected: str, candidate_keys: set[str]) -> bool:
    norm = _norm_node_key(expected)
    if norm in {_norm_node_key(item) for item in candidate_keys if item}:
        return True
    expected_path = expected.replace("\\", "/")
    return any(key.replace("\\", "/").endswith("/" + expected_path) for key in candidate_keys if key)


def _resolve_node_expectation_ids(
    graph: Graph,
    node_keys_by_id: dict[str, set[str]],
    expected: str,
) -> set[str]:
    """Resolve one qrel without letting generic concepts shadow code symbols.

    Exact node IDs are authoritative, including when a suite deliberately
    targets a concept node. For label/path expectations, prefer code-like
    matches when any exist. Scanner-created generic concepts often repeat a
    source symbol's label; treating both as separate relevant results inflates
    IDCG and lets a concept packet satisfy recall even when the actual source
    symbol is absent.
    """
    if expected in graph.nodes:
        return {expected}
    matches = {
        node_id
        for node_id, candidate_keys in node_keys_by_id.items()
        if _node_expectation_matches(expected, candidate_keys)
    }
    code_matches = {
        node_id for node_id in matches if (node := graph.nodes.get(node_id)) is not None and is_code_like(node)
    }
    return code_matches or matches


def _eval_note(
    *,
    scored: bool,
    expected_unresolved: list[str],
    expected_answerable: bool | None,
) -> str:
    if expected_unresolved:
        count = len(expected_unresolved)
        return (
            f"{count} expected node expectation(s) match no node in the graph; "
            "recall remains scored against all declared expectations, but this "
            "task is excluded from calibration"
        )
    if not scored:
        if expected_answerable is not None:
            return "no retrieval expectations parsed; task is labeled for answerability calibration only"
        return "no expectations parsed: give each task an `expected` (node labels/paths) and/or `expected_edges` list"
    return ""


def _norm_node_key(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\(\)$", "", value)
    value = value.replace("\\", "/")
    value = value.rsplit("/", 1)[-1]
    value = _strip_known_suffix(value)
    return value.lower()


def _strip_known_suffix(value: str) -> str:
    return re.sub(
        r"\.(py|pyi|js|jsx|ts|tsx|rs|go|java|c|h|hpp|cpp|cs|md|rst|txt|json|yaml|yml|toml)$",
        "",
        value,
        flags=re.IGNORECASE,
    )
