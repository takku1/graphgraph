from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ..io import find_graph_path, load_any, save_validated_graph
from ..platform import (
    CpgEvidenceProvider,
    EvidenceStore,
    GraphProgram,
    GraphRuntime,
    MemoryStore,
    ProjectRegistry,
    QuerySourcePlanner,
    SemanticIndex,
    StructuralEvidenceProvider,
    TemporalStore,
    build_change_packet,
    build_continuation_receipt,
    build_hierarchy,
    build_repair_context,
    evaluate_cases,
    graph_as_of,
    infer_edges,
    ingest_runtime_trace,
    load_benchmark_config,
    migrate_platform_state,
    run_benchmark,
)
from ..platform.evaluation import load_cases
from ..platform.interop import export_graph
from ..platform.service import install_git_hooks, serve_graph, watch_paths
from ..platform.temporal import new_episode
from ..services.native import update_paths_validated_graph


def add_platform_parser(sub: argparse._SubParsersAction) -> None:
    platform = sub.add_parser("platform", help="Compile advanced evidence, memory, time, federation, and repair workflows into GraphGraph IR.")
    actions = platform.add_subparsers(dest="platform_action", required=True)

    compile_cmd = actions.add_parser("compile", help="Compile an LLM-native context packet and validation receipt.")
    compile_cmd.add_argument("query")
    compile_cmd.add_argument("--graph")
    compile_cmd.add_argument("--query-class", default="auto")
    compile_cmd.add_argument("--packet", default="gg")
    compile_cmd.add_argument("--pass", action="append", dest="passes", choices=["evidence", "inference", "hierarchy"], default=[])
    compile_cmd.add_argument("--scope", action="append", default=[])
    compile_cmd.add_argument("--max-nodes", type=int)
    compile_cmd.add_argument("--evidence-store")
    compile_cmd.add_argument("--refresh-evidence", action="store_true")

    change = actions.add_parser("change", help="Compile two graph snapshots into a structural change packet.")
    change.add_argument("--before", required=True)
    change.add_argument("--after", required=True)
    change.add_argument("--impact-hops", type=int, default=2)

    continuation = actions.add_parser("continuation", help="Create a machine-readable agent continuation receipt.")
    continuation.add_argument("--objective", required=True)
    continuation.add_argument("--completed", action="append", default=[])
    continuation.add_argument("--remaining", action="append", default=[])
    continuation.add_argument("--changed", action="append", default=[])
    continuation.add_argument("--validation", action="append", default=[])
    continuation.add_argument("--next-query", default="")
    continuation.add_argument("--output")

    capabilities = actions.add_parser("capabilities", help="Describe compiler passes and evidence providers.")
    capabilities.set_defaults(platform_action="capabilities")

    registry = actions.add_parser("register", help="Register a repository graph for federation.")
    registry.add_argument("name")
    registry.add_argument("--root", default=".")
    registry.add_argument("--graph")
    registry.add_argument("--registry", default=".graphgraph/projects.json")
    registry.add_argument("--tag", action="append", default=[])

    federation = actions.add_parser("federate", help="Build a namespaced multi-repository graph.")
    federation.add_argument("--registry", default=".graphgraph/projects.json")
    federation.add_argument("--project", action="append", default=[])
    federation.add_argument("--output", default=".graphgraph/federated.gg")

    semantic = actions.add_parser("semantic", help="Build/query the local semantic fallback index.")
    semantic.add_argument("query", nargs="?")
    semantic.add_argument("--graph")
    semantic.add_argument("--index", default=".graphgraph/semantic.json")
    semantic.add_argument("--rebuild", action="store_true")
    semantic.add_argument("--limit", type=int, default=10)

    memory = actions.add_parser("memory", help="Add or search scoped agent/project memory.")
    memory.add_argument("operation", choices=["add", "query", "list"])
    memory.add_argument("text", nargs="?")
    memory.add_argument("--store", default=".graphgraph/memory.json")
    memory.add_argument("--scope", action="append", default=[])
    memory.add_argument("--kind", default="fact")
    memory.add_argument("--source", default="")
    memory.add_argument("--related", action="append", default=[])
    memory.add_argument("--limit", type=int, default=10)

    episode = actions.add_parser("episode", help="Append or inspect temporal graph episodes.")
    episode.add_argument("operation", choices=["add", "list"])
    episode.add_argument("--id")
    episode.add_argument("--kind", default="event")
    episode.add_argument("--summary", default="")
    episode.add_argument("--actor", default="")
    episode.add_argument("--related", action="append", default=[])
    episode.add_argument("--supersedes", default="")
    episode.add_argument("--store", default=".graphgraph/episodes.jsonl")
    episode.add_argument("--as-of", default="")

    as_of = actions.add_parser("as-of", help="Materialize a graph snapshot at an ISO timestamp.")
    as_of.add_argument("timestamp")
    as_of.add_argument("--graph")
    as_of.add_argument("--output", required=True)

    transform = actions.add_parser("transform", help="Persist evidence, inference, or hierarchy graph passes.")
    transform.add_argument("passes", nargs="+", choices=["evidence", "inference", "hierarchy"])
    transform.add_argument("--graph")
    transform.add_argument("--output", required=True)
    transform.add_argument("--evidence-store")
    transform.add_argument("--refresh-evidence", action="store_true")

    trace = actions.add_parser("trace", help="Compile runtime call events into typed graph evidence.")
    trace.add_argument("--trace", required=True)
    trace.add_argument("--trace-id", default="runtime")
    trace.add_argument("--graph")
    trace.add_argument("--output", required=True)

    repair = actions.add_parser("repair", help="Compile an issue or stack trace into bounded repair context.")
    repair.add_argument("issue")
    repair.add_argument("--graph")
    repair.add_argument("--max-nodes", type=int, default=30)
    repair.add_argument("--hops", type=int, default=2)

    portable = actions.add_parser("export", help="Export portable JSON, JSONL, GraphML, or Cypher.")
    portable.add_argument("--graph")
    portable.add_argument("--output", required=True)
    portable.add_argument("--format", choices=["auto", "json", "jsonl", "graphml", "cypher"], default="auto")

    evaluate = actions.add_parser("eval", help="Run cross-project retrieval acceptance cases.")
    evaluate.add_argument("--cases", required=True)
    evaluate.add_argument("--registry")
    evaluate.add_argument("--graph")
    evaluate.add_argument("--project", default="default")

    benchmark = actions.add_parser("benchmark", help="Run enforced multi-repository latency, token, recall, and correctness gates.")
    benchmark.add_argument("--config", required=True)
    benchmark.add_argument("--output")
    benchmark.add_argument("--no-enforce", action="store_true")

    acceptance = actions.add_parser(
        "acceptance",
        help="Run the sealed black-box GraphGraph acceptance board.",
    )
    acceptance.add_argument("--repo", default=".", help="target repository root")
    acceptance.add_argument("--graph", help="graph path (default: <repo>/.graphgraph/graph.gg)")
    acceptance.add_argument("--case", action="append", default=[], help="run only this canonical case ID")
    acceptance.add_argument("--json", dest="as_json", action="store_true", help="emit JSON instead of Markdown")
    acceptance.add_argument("--output", help="also write the report to this path")

    quality = actions.add_parser(
        "quality",
        help="Check token/recall/precision metrics against the hermetic baseline.",
    )
    quality.add_argument("--baseline", help="quality baseline JSON (default: packaged baseline)")
    quality.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    quality.add_argument("--no-enforce", action="store_true", help="report regressions without exiting nonzero")

    serve = actions.add_parser("serve", help="Run the shared local HTTP API and operational console.")
    serve.add_argument("--graph")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true")
    serve.add_argument("--token")
    serve.add_argument("--allow-origin", action="append", default=[])
    serve.add_argument("--max-body-bytes", type=int, default=1_000_000)
    serve.add_argument("--rate-limit", type=int, default=120)

    migrate = actions.add_parser("migrate", help="Migrate local platform state files to the current schema.")
    migrate.add_argument("--directory", default=".graphgraph")

    watch = actions.add_parser("watch", help="Continuously splice changed files into the native graph.")
    watch.add_argument("--directory", default=".")
    watch.add_argument("--graph", default=".graphgraph/graph.gg")
    watch.add_argument("--interval", type=float, default=1.0)

    hooks = actions.add_parser("hooks", help="Install managed Git hooks that refresh GraphGraph after commits and merges.")
    hooks.add_argument("--directory", default=".")
    hooks.add_argument("--executable", default="graphgraph")
    platform.set_defaults(func=cmd_platform)


def cmd_platform(args: argparse.Namespace) -> None:
    action = args.platform_action
    if action == "compile":
        graph_path = _graph_path(args)
        graph = load_any(graph_path)
        runtime = GraphRuntime(
            graph,
            (StructuralEvidenceProvider(), CpgEvidenceProvider()),
            evidence_store=EvidenceStore(
                Path(args.evidence_store) if args.evidence_store else graph_path.parent / "evidence.db"
            ),
            refresh_evidence=args.refresh_evidence,
            source_planner=QuerySourcePlanner(graph_path.parent, graph_path=graph_path),
        )
        result = runtime.compile(GraphProgram(
            args.query,
            args.query_class,
            args.packet,
            tuple(args.passes),
            tuple(args.scope),
            args.max_nodes,
        ))
        print(result.envelope())
        return
    if action == "change":
        print(build_change_packet(load_any(Path(args.before)), load_any(Path(args.after)), impact_hops=args.impact_hops).to_json())
        return
    if action == "continuation":
        receipt = build_continuation_receipt(
            objective=args.objective,
            completed=tuple(args.completed),
            remaining=tuple(args.remaining),
            changed_paths=tuple(args.changed),
            validation=tuple(args.validation),
            next_query=args.next_query,
        )
        text = receipt.to_json()
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
        print(text)
        return
    if action == "capabilities":
        registry = GraphRuntime(_empty_graph(), (StructuralEvidenceProvider(), CpgEvidenceProvider())).providers
        print(json.dumps({
            "model": "LLM-native graph IR compiler",
            "hot_path": ["SYNC", "EXTRACT", "NORMALIZE_IR", "ANCHOR", "EXPAND", "SELECT", "PACK"],
            "passes": ["evidence", "inference", "hierarchy"],
            "providers": registry.capabilities(),
            "adapters": ["federation", "semantic", "temporal", "memory", "runtime_trace", "repair", "evaluation", "interop", "http", "watch"],
        }, indent=2))
        return
    if action == "register":
        graph_path = Path(args.graph) if args.graph else find_graph_path(Path(args.root))
        print(json.dumps(asdict(ProjectRegistry(Path(args.registry)).register(args.name, Path(args.root), graph_path, tags=tuple(args.tag))), indent=2))
        return
    if action == "federate":
        graph = ProjectRegistry(Path(args.registry)).build(names=tuple(args.project))
        validation = save_validated_graph(graph, Path(args.output))
        print(json.dumps({"output": args.output, "nodes": len(graph.nodes), "edges": len(graph.edges), "valid": validation.ok}, indent=2))
        return
    if action == "semantic":
        index_path = Path(args.index)
        if args.rebuild or not index_path.exists():
            index = SemanticIndex(index_path).build(_graph(args))
        else:
            index = SemanticIndex.load(index_path)
        print(json.dumps({"index": str(index_path), "vectors": len(index.vectors), "matches": index.query(args.query, limit=args.limit) if args.query else []}, indent=2))
        return
    if action == "memory":
        store = MemoryStore(Path(args.store))
        scopes = tuple(args.scope)
        if args.operation == "add":
            if not args.text:
                raise ValueError("memory add requires text")
            scope = scopes[0] if scopes else "project"
            data = asdict(store.remember(args.text, scope=scope, kind=args.kind, source=args.source, related_nodes=tuple(args.related)))
        elif args.operation == "query":
            if not args.text:
                raise ValueError("memory query requires text")
            data = [asdict(record) for record in store.search(args.text, scopes=scopes, limit=args.limit)]
        else:
            data = [asdict(record) for record in store.read(scopes=scopes)]
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if action == "episode":
        store = TemporalStore(Path(args.store))
        if args.operation == "add":
            if not args.id or not args.summary:
                raise ValueError("episode add requires --id and --summary")
            episode = new_episode(args.id, args.kind, args.summary, actor=args.actor, related_nodes=tuple(args.related), supersedes=args.supersedes)
            store.append(episode)
            data = asdict(episode)
        else:
            data = [asdict(episode) for episode in store.read(as_of=args.as_of)]
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if action == "as-of":
        graph = graph_as_of(_graph(args), args.timestamp)
        validation = save_validated_graph(graph, Path(args.output))
        print(json.dumps({"output": args.output, "nodes": len(graph.nodes), "edges": len(graph.edges), "valid": validation.ok}, indent=2))
        return
    if action == "transform":
        graph_path = _graph_path(args)
        graph = load_any(graph_path)
        receipts = []
        for item in args.passes:
            if item == "evidence":
                graph, provider_receipts = GraphRuntime(
                    graph,
                    (StructuralEvidenceProvider(), CpgEvidenceProvider()),
                    evidence_store=EvidenceStore(
                        Path(args.evidence_store)
                        if args.evidence_store
                        else graph_path.parent / "evidence.db"
                    ),
                    refresh_evidence=args.refresh_evidence,
                    source_planner=QuerySourcePlanner(graph_path.parent, graph_path=graph_path),
                ).apply_evidence()
                receipts.extend(asdict(receipt) for receipt in provider_receipts)
            elif item == "inference":
                graph, receipt = infer_edges(graph)
                receipts.append(receipt)
            else:
                graph = build_hierarchy(graph)
                receipts.append({"pass": "hierarchy", "communities": graph.metadata.get("communities", "0")})
        validation = save_validated_graph(graph, Path(args.output))
        print(json.dumps({"output": args.output, "valid": validation.ok, "receipts": receipts}, indent=2))
        return
    if action == "trace":
        graph, receipt = ingest_runtime_trace(_graph(args), Path(args.trace), trace_id=args.trace_id)
        validation = save_validated_graph(graph, Path(args.output))
        print(json.dumps({"output": args.output, "valid": validation.ok, **receipt}, indent=2))
        return
    if action == "repair":
        print(json.dumps(build_repair_context(_graph(args), args.issue, max_nodes=args.max_nodes, hops=args.hops), indent=2, ensure_ascii=False))
        return
    if action == "export":
        print(json.dumps(export_graph(_graph(args), Path(args.output), args.format), indent=2))
        return
    if action == "eval":
        cases = load_cases(Path(args.cases))
        if args.registry:
            registry = ProjectRegistry(Path(args.registry))
            graphs = {entry.name: load_any(Path(entry.graph)) for entry in registry.list()}
        else:
            graphs = {args.project: _graph(args)}
        print(json.dumps(evaluate_cases(graphs, cases), indent=2, ensure_ascii=False))
        return
    if action == "benchmark":
        report = run_benchmark(load_benchmark_config(Path(args.config)))
        text = json.dumps(report, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(text)
        if not args.no_enforce and not report["ok"]:
            raise SystemExit(1)
        return
    if action == "acceptance":
        from ..acceptance.service import execute_acceptance

        execution = execute_acceptance(
            repo=Path(args.repo),
            graph_path=Path(args.graph) if args.graph else None,
            case_ids=tuple(args.case),
            as_json=args.as_json,
            output=Path(args.output) if args.output else None,
        )
        print(execution.report)
        if execution.exit_code:
            raise SystemExit(execution.exit_code)
        return
    if action == "quality":
        from ..acceptance.quality import (
            BASELINE_PATH,
            compare,
            format_report,
            load_baseline,
            run_quality,
            to_json,
        )

        report = run_quality()
        baseline_path = Path(args.baseline) if args.baseline else BASELINE_PATH
        regressions = compare(report, load_baseline(baseline_path))
        if args.as_json:
            print(json.dumps({
                "baseline": str(baseline_path),
                "ok": not regressions,
                "metrics": to_json(report),
                "regressions": [asdict(item) for item in regressions],
            }, indent=2))
        else:
            print(format_report(report))
            print("\nno quality regression" if not regressions else "\nquality regressions:")
            for item in regressions:
                print(f"  {item.query}: {item.reason} {item.baseline} -> {item.current}")
        if regressions and not args.no_enforce:
            raise SystemExit(1)
        return
    if action == "serve":
        graph_path = Path(args.graph) if args.graph else find_graph_path()
        print(f"GraphGraph console: http://{args.host}:{args.port}")
        serve_graph(
            graph_path,
            host=args.host,
            port=args.port,
            open_browser=args.open,
            token=args.token,
            allowed_origins=tuple(args.allow_origin),
            max_body_bytes=args.max_body_bytes,
            rate_limit_per_minute=args.rate_limit,
        )
        return
    if action == "migrate":
        print(json.dumps(migrate_platform_state(Path(args.directory)), indent=2))
        return
    if action == "watch":
        root = Path(args.directory).resolve()
        graph_path = Path(args.graph)
        print(f"Watching {root}; graph={graph_path}")

        def refresh(changed: list[str], deleted: list[str]) -> None:
            status = update_paths_validated_graph(directory=root, output_path=graph_path, paths=changed, deleted_paths=deleted)
            print(json.dumps({"changed": changed, "deleted": deleted, "nodes": len(status.graph.nodes), "edges": len(status.graph.edges)}))

        watch_paths(root, refresh, interval=args.interval)
        return
    if action == "hooks":
        paths = install_git_hooks(Path(args.directory), executable=args.executable)
        print(json.dumps({"installed": [str(path) for path in paths]}, indent=2))
        return
    raise ValueError(f"unknown platform action: {action}")


def _graph(args: argparse.Namespace):
    return load_any(_graph_path(args))


def _graph_path(args: argparse.Namespace) -> Path:
    return Path(args.graph) if getattr(args, "graph", None) else find_graph_path()


def _empty_graph():
    from ..graph.core import Graph

    return Graph()
