from __future__ import annotations

import hmac
import ipaddress
import json
import threading
import time
import urllib.parse
import webbrowser
from collections import defaultdict, deque
from dataclasses import asdict
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from ..io import load_any
from ..scanner.files import collect_files
from .compiler import GraphProgram, GraphRuntime
from .contracts import StructuralEvidenceProvider
from .cpg import CpgEvidenceProvider
from .evidence_store import EvidenceStore
from .memory import MemoryStore
from .persistence import PLATFORM_STATE_VERSION, append_jsonl_many, migrate_platform_state
from .source_planner import QuerySourcePlanner
from .temporal import Episode, TemporalStore

_PACKETS = {
    "lowlevel",
    "sql",
    "hybrid",
    "semantic_arrow",
    "gg",
    "gg_hybrid",
    "gg_lex",
    "gg_lex_hybrid",
    "svo",
    "doc_summary",
}
_PASSES = {"evidence", "inference", "hierarchy"}


class _GraphFileCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._graph = None
        self.hits = 0
        self.misses = 0

    def get(self):
        stat = self.path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if self._graph is not None and self._stamp == stamp:
                self.hits += 1
                return self._graph
            self._graph = load_any(self.path)
            self._stamp = stamp
            self.misses += 1
            return self._graph

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


class _RateLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self._lock = threading.Lock()
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str) -> bool:
        cutoff = time.monotonic() - 60.0
        with self._lock:
            requests = self._requests[client]
            while requests and requests[0] < cutoff:
                requests.popleft()
            if len(requests) >= self.limit:
                return False
            requests.append(time.monotonic())
            return True


def create_server(
    graph_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    allowed_origins: tuple[str, ...] = (),
    max_body_bytes: int = 1_000_000,
    rate_limit_per_minute: int = 120,
) -> ThreadingHTTPServer:
    resolved = graph_path.resolve()
    if not _is_loopback_host(host) and not token:
        raise ValueError("non-loopback HTTP binding requires an API token")
    graph_cache = _GraphFileCache(resolved)
    limiter = _RateLimiter(rate_limit_per_minute)
    migration = migrate_platform_state(resolved.parent)
    max_body_bytes = max(1024, max_body_bytes)

    class Handler(BaseHTTPRequestHandler):
        server_version = "GraphGraph/0.2"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if parsed.path == "/":
                    self._send(HTTPStatus.OK, _UI, "text/html; charset=utf-8")
                    return
                if not self._allow_api():
                    return
                graph = graph_cache.get()
                if parsed.path == "/api/status":
                    self._json({
                        "graph": str(resolved),
                        "nodes": len(graph.nodes),
                        "edges": len(graph.edges),
                        "metadata": graph.metadata,
                        "graph_cache": graph_cache.stats(),
                        "state_version": PLATFORM_STATE_VERSION,
                        "migration": migration,
                    })
                    return
                if parsed.path == "/api/query":
                    self._json(self._compile(graph, {
                        "query": _one(query, "q"),
                        "packet": _one(query, "packet", "gg"),
                        "passes": [
                            value
                            for raw in query.get("passes", [])
                            for value in raw.split(",")
                            if value
                        ],
                    }))
                    return
                if parsed.path == "/api/node":
                    node_id = _one(query, "id")
                    node = graph.nodes.get(node_id)
                    if node is None:
                        self._json({"error": "node not found"}, HTTPStatus.NOT_FOUND)
                    else:
                        self._json({
                            "node": node.__dict__,
                            "incoming": [edge.__dict__ for edge in graph.incoming().get(node_id, [])],
                            "outgoing": [edge.__dict__ for edge in graph.outgoing().get(node_id, [])],
                        })
                    return
                if parsed.path == "/api/graph":
                    limit = min(1000, max(1, int(_one(query, "limit", "300"))))
                    ranked = graph.pagerank()
                    node_ids = sorted(
                        (node_id for node_id, node in graph.nodes.items() if node.active),
                        key=lambda node_id: (-ranked.get(node_id, 0.0), node_id),
                    )[:limit]
                    selected = set(node_ids)
                    self._json({
                        "nodes": [{
                            "id": graph.nodes[node_id].id,
                            "label": graph.nodes[node_id].label,
                            "kind": graph.nodes[node_id].kind,
                            "path": graph.nodes[node_id].path,
                            "rank": ranked.get(node_id, 0.0),
                        } for node_id in node_ids],
                        "edges": [
                            {"source": edge.source, "target": edge.target, "type": edge.type}
                            for edge in graph.edges
                            if edge.active and edge.source in selected and edge.target in selected
                        ],
                        "truncated": len(node_ids) < sum(node.active for node in graph.nodes.values()),
                    })
                    return
                self._json({"error": "route not found"}, HTTPStatus.NOT_FOUND)
            except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception:
                self._json({"error": "internal server error"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            try:
                if not self._allow_api():
                    return
                data = self._read_json()
                if parsed.path == "/api/query":
                    self._json(self._compile(graph_cache.get(), data))
                    return
                if parsed.path == "/api/memory":
                    content = _bounded_text(data.get("content"), "content", 20_000)
                    scope = _bounded_text(data.get("scope", "project"), "scope", 100)
                    record = MemoryStore(resolved.parent / "memory.json").remember(
                        content,
                        scope=scope,
                        kind=_bounded_text(data.get("kind", "fact"), "kind", 100),
                        source=_bounded_text(data.get("source", "http"), "source", 1000),
                        related_nodes=_string_tuple(data.get("related_nodes"), 100, 200),
                    )
                    self._json({"ok": True, "record": asdict(record)}, HTTPStatus.CREATED)
                    return
                if parsed.path == "/api/episode":
                    timestamp = _bounded_text(
                        data.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                        "timestamp",
                        100,
                    )
                    episode = Episode(
                        _bounded_text(data.get("id"), "id", 200),
                        timestamp,
                        _bounded_text(data.get("kind", "event"), "kind", 100),
                        _bounded_text(data.get("summary"), "summary", 20_000),
                        _bounded_text(data.get("actor", "http"), "actor", 1000),
                        _string_tuple(data.get("related_nodes"), 100, 200),
                        _bounded_text(data.get("supersedes", ""), "supersedes", 200, allow_empty=True),
                        _string_tuple(data.get("facts"), 100, 1000),
                    )
                    TemporalStore(resolved.parent / "episodes.jsonl").append(episode)
                    self._json({"ok": True, "episode": asdict(episode)}, HTTPStatus.CREATED)
                    return
                if parsed.path == "/api/trace":
                    events = data.get("events", [data])
                    if not isinstance(events, list) or len(events) > 10_000:
                        raise ValueError("events must be an array of at most 10000 items")
                    trace_path = resolved.parent / "runtime-trace.jsonl"
                    normalized_events = []
                    for event in events:
                        if not isinstance(event, dict):
                            raise ValueError("each trace event must be an object")
                        normalized_events.append({
                            "caller": _bounded_text(event.get("caller"), "caller", 1000),
                            "callee": _bounded_text(event.get("callee"), "callee", 1000),
                            "count": max(0.0, float(event.get("count", 1.0))),
                            "timestamp": _bounded_text(event.get("timestamp", ""), "timestamp", 100, allow_empty=True),
                            "location": _bounded_text(event.get("location", ""), "location", 2000, allow_empty=True),
                            "evidence": _bounded_text(event.get("evidence", ""), "evidence", 5000, allow_empty=True),
                        })
                    append_jsonl_many(trace_path, normalized_events)
                    self._json({"ok": True, "events": len(events)}, HTTPStatus.CREATED)
                    return
                if parsed.path == "/api/migrate":
                    self._json(migrate_platform_state(resolved.parent))
                    return
                self._json({"error": "route not found"}, HTTPStatus.NOT_FOUND)
            except (ValueError, FileNotFoundError, json.JSONDecodeError, TimeoutError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception:
                self._json({"error": "internal server error"}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_OPTIONS(self) -> None:  # noqa: N802
            origin = self.headers.get("Origin", "")
            if origin and origin in allowed_origins:
                self.send_response(HTTPStatus.NO_CONTENT.value)
                self._security_headers()
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-GraphGraph-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.end_headers()
                return
            self._json({"error": "origin not allowed"}, HTTPStatus.FORBIDDEN)

        def log_message(self, format: str, *args) -> None:
            return

        def _json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(data, indent=2, ensure_ascii=False), "application/json; charset=utf-8")

        def _allow_api(self) -> bool:
            if not limiter.allow(self.client_address[0]):
                self._json({"error": "rate limit exceeded"}, HTTPStatus.TOO_MANY_REQUESTS)
                return False
            if token:
                supplied = self.headers.get("X-GraphGraph-Token", "")
                authorization = self.headers.get("Authorization", "")
                if authorization.startswith("Bearer "):
                    supplied = authorization[7:]
                if not hmac.compare_digest(supplied, token):
                    self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return False
            return True

        def _read_json(self) -> dict[str, object]:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                raise ValueError("Content-Length is required")
            length = int(raw_length)
            if length < 0 or length > max_body_bytes:
                raise ValueError(f"request body exceeds {max_body_bytes} bytes")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def _compile(self, graph, data: dict[str, object]) -> dict[str, object]:
            text = _bounded_text(data.get("query"), "query", 20_000)
            packet = _bounded_text(data.get("packet", "gg"), "packet", 100)
            if packet not in _PACKETS:
                raise ValueError(f"unknown packet: {packet}")
            raw_passes = data.get("passes", [])
            if not isinstance(raw_passes, list):
                raise ValueError("passes must be an array")
            passes = tuple(str(value) for value in raw_passes)
            unknown = set(passes) - _PASSES
            if unknown:
                raise ValueError(f"unknown compiler passes: {', '.join(sorted(unknown))}")
            max_nodes = data.get("max_nodes")
            if max_nodes is not None:
                max_nodes = min(1000, max(1, int(max_nodes)))
            result = GraphRuntime(
                graph,
                (StructuralEvidenceProvider(), CpgEvidenceProvider()),
                evidence_store=EvidenceStore(resolved.parent / "evidence.db"),
                source_planner=QuerySourcePlanner(resolved.parent, graph_path=resolved),
                source_mode=_bounded_text(
                    data.get("source_mode", "auto"),
                    "source_mode",
                    20,
                ),
            ).compile(GraphProgram(text, packet=packet, passes=passes, max_nodes=max_nodes))
            return json.loads(result.envelope())

        def _send(self, status: HTTPStatus, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self._security_headers()
            origin = self.headers.get("Origin", "")
            if origin and origin in allowed_origins:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(encoded)

        def _security_headers(self) -> None:
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
            )

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def serve_graph(
    graph_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    token: str | None = None,
    allowed_origins: tuple[str, ...] = (),
    max_body_bytes: int = 1_000_000,
    rate_limit_per_minute: int = 120,
) -> None:
    server = create_server(
        graph_path,
        host=host,
        port=port,
        token=token,
        allowed_origins=allowed_origins,
        max_body_bytes=max_body_bytes,
        rate_limit_per_minute=rate_limit_per_minute,
    )
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    server.serve_forever()


def watch_paths(
    root: Path,
    callback: Callable[[list[str], list[str]], None],
    *,
    interval: float = 1.0,
    stop: threading.Event | None = None,
    include: tuple[str, ...] = (".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".md", ".rst"),
) -> None:
    """Portable polling watcher for continuous graph refresh workflows."""
    stop = stop or threading.Event()
    state = _snapshot(root, include)
    while not stop.wait(max(0.1, interval)):
        current = _snapshot(root, include)
        changed = sorted(path for path, stamp in current.items() if state.get(path) != stamp)
        deleted = sorted(state.keys() - current.keys())
        if changed or deleted:
            callback(changed, deleted)
        state = current


def _snapshot(root: Path, include: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    result = {}
    collected = collect_files(root, max_nodes=1_000_000)
    for path in collected.files:
        if path.suffix.casefold() not in include:
            continue
        stat = path.stat()
        result[path.relative_to(root).as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return result


def install_git_hooks(root: Path, *, executable: str = "graphgraph") -> list[Path]:
    """Install managed post-commit/post-merge refresh hooks without replacing existing hooks."""
    git_dir = root.resolve() / ".git"
    if not git_dir.is_dir():
        raise ValueError(f"not a Git repository: {root}")
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    marker_start = "# >>> graphgraph managed >>>"
    marker_end = "# <<< graphgraph managed <<<"
    block = (
        f"{marker_start}\n"
        f"{executable} context \"refresh graph after git change\" --sync git --json > .graphgraph/hook-receipt.json\n"
        f"{marker_end}\n"
    )
    for name in ("post-commit", "post-merge"):
        path = hooks_dir / name
        existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else "#!/bin/sh\n"
        if marker_start in existing:
            before, rest = existing.split(marker_start, 1)
            _old, after = rest.split(marker_end, 1)
            content = before + block + after.lstrip("\r\n")
        else:
            content = existing.rstrip() + "\n\n" + block
        path.write_text(content, encoding="utf-8", newline="\n")
        try:
            path.chmod(path.stat().st_mode | 0o111)
        except OSError:
            pass
        installed.append(path)
    return installed


def _one(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def _is_loopback_host(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _bounded_text(
    value: object,
    name: str,
    limit: int,
    *,
    allow_empty: bool = False,
) -> str:
    text = str(value or "").strip()
    if not text and not allow_empty:
        raise ValueError(f"{name} is required")
    if len(text) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return text


def _string_tuple(value: object, max_items: int, max_length: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > max_items:
        raise ValueError(f"expected an array of at most {max_items} strings")
    return tuple(_bounded_text(item, "array item", max_length) for item in value)


_UI = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GraphGraph Console</title><style>
:root{color-scheme:light;--ink:#172026;--muted:#66737c;--line:#d7dde1;--paper:#f7f8f8;--accent:#087f5b;--code:#101719;--warn:#b45309}
*{box-sizing:border-box}html,body{width:100%;max-width:100vw;overflow-x:hidden}body{margin:0;font:14px/1.45 system-ui,sans-serif;color:var(--ink);background:var(--paper)}
header{width:100%;height:52px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:20px;padding:0 22px;background:white;min-width:0;overflow:hidden}
h1{font-size:16px;margin:0;white-space:nowrap;flex:none}.status{color:var(--muted);font-size:12px;margin-left:auto;min-width:0;max-width:calc(100vw - 210px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}main{width:100%;min-width:0;display:grid;grid-template-columns:minmax(280px,380px) minmax(0,1fr);height:calc(100vh - 52px)}
.controls{width:100%;min-width:0;padding:20px;border-right:1px solid var(--line);background:white;overflow:auto}.workspace{display:grid;grid-template-rows:42px 1fr;min-width:0;min-height:0}
label{display:block;font-size:12px;font-weight:650;margin:0 0 6px}textarea,select,input{width:100%;min-width:0;max-width:100%;border:1px solid #aeb8be;border-radius:4px;background:white;padding:9px;font:inherit}
textarea{height:132px;resize:vertical}.row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;margin-top:14px}.row>div{min-width:0}
button{border:0;border-radius:4px;padding:9px 13px;background:var(--accent);color:white;font-weight:650;cursor:pointer;margin-top:14px}
.tabs{display:flex;align-items:end;gap:2px;padding:0 14px;border-bottom:1px solid var(--line);background:white}.tab{margin:0;background:transparent;color:var(--muted);border-radius:0;padding:12px 14px 9px;border-bottom:3px solid transparent}.tab.active{color:var(--ink);border-color:var(--accent)}
.pane{display:none;min-height:0}.pane.active{display:block}.context-pane{padding:18px;height:100%;overflow:auto}pre{margin:0;background:var(--code);color:#dce8e3;padding:18px;min-height:300px;overflow:auto;border-radius:4px;white-space:pre-wrap}
.graph-pane{height:100%;position:relative;background:#fff}.graph-pane canvas{display:block;width:100%;height:100%}.legend{position:absolute;left:14px;bottom:12px;color:var(--muted);background:rgba(255,255,255,.92);padding:6px 8px;border:1px solid var(--line);border-radius:4px;font-size:11px}
.details{margin-top:18px;border-top:1px solid var(--line);padding-top:14px;color:var(--muted);overflow-wrap:anywhere}.details strong{color:var(--ink)}
@media(max-width:760px){header{padding:0 14px;gap:12px}.status{max-width:calc(100vw - 190px)}main{grid-template-columns:minmax(0,1fr);height:auto}.controls{border-right:0;border-bottom:1px solid var(--line)}.row{grid-template-columns:minmax(0,1fr)}.workspace{height:70vh}}
@media(max-width:500px){.status{display:none}}
</style></head><body><header><h1>GraphGraph Console</h1><span class="status" id="status">Loading graph status...</span></header><main><section class="controls">
<label for="query">Context query</label><textarea id="query">What is the architecture and primary execution path?</textarea>
<div class="row"><div><label for="packet">Packet</label><select id="packet"><option>gg</option><option>semantic_arrow</option><option>sql</option><option>doc_summary</option></select></div>
<div><label for="passes">Compiler passes</label><select id="passes"><option value="">native</option><option value="evidence">evidence</option><option value="inference">inference</option><option value="hierarchy">hierarchy</option><option value="evidence,inference,hierarchy">all passes</option></select></div></div>
<button id="run">Compile context</button><div class="details" id="details"><strong>Node inspection</strong><br>Select a node in the topology.</div></section>
<section class="workspace"><nav class="tabs"><button class="tab active" data-pane="context">Context packet</button><button class="tab" data-pane="graph">Topology</button></nav>
<div class="pane context-pane active" id="context"><pre id="output">Ready.</pre></div><div class="pane graph-pane" id="graph"><canvas id="canvas"></canvas><div class="legend">Top 300 PageRank nodes. Drag to pan; wheel to zoom; select for evidence.</div></div></section></main>
<script>
const out=document.querySelector('#output'),canvas=document.querySelector('#canvas'),ctx=canvas.getContext('2d'),details=document.querySelector('#details');let topology={nodes:[],edges:[]},view={x:0,y:0,z:1},drag=null;
fetch('/api/status').then(r=>r.json()).then(s=>document.querySelector('#status').textContent=`${s.nodes} nodes / ${s.edges} edges | ${s.graph}`);
fetch('/api/graph?limit=300').then(r=>r.json()).then(g=>{topology=g;layout();draw()});
document.querySelector('#run').onclick=async()=>{out.textContent='Compiling...';show('context');const query=document.querySelector('#query').value,packet=document.querySelector('#packet').value,passes=document.querySelector('#passes').value.split(',').filter(Boolean);const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,packet,passes})});out.textContent=JSON.stringify(await r.json(),null,2)};
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>show(t.dataset.pane));function show(id){document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.pane===id));document.querySelectorAll('.pane').forEach(p=>p.classList.toggle('active',p.id===id));if(id==='graph'){resize();draw()}}
function layout(){const n=topology.nodes.length,cols=Math.max(1,Math.ceil(Math.sqrt(n)));topology.nodes.forEach((node,i)=>{node.i=i;node.x=(i%cols)*82;node.y=Math.floor(i/cols)*58;node.r=4+Math.min(7,Math.sqrt(node.rank||0)*80)});center()}
function center(){resize();if(!topology.nodes.length)return;const box=canvas.getBoundingClientRect(),maxX=Math.max(...topology.nodes.map(n=>n.x))+40,maxY=Math.max(...topology.nodes.map(n=>n.y))+40;view.z=Math.min(1.4,Math.max(.18,Math.min(box.width/maxX,box.height/maxY)));view.x=(box.width-maxX*view.z)/2;view.y=(box.height-maxY*view.z)/2}
function resize(){const d=devicePixelRatio||1,r=canvas.getBoundingClientRect();canvas.width=Math.max(1,r.width*d);canvas.height=Math.max(1,r.height*d);ctx.setTransform(d,0,0,d,0,0)}
function draw(){const r=canvas.getBoundingClientRect();ctx.clearRect(0,0,r.width,r.height);ctx.save();ctx.translate(view.x,view.y);ctx.scale(view.z,view.z);const map=new Map(topology.nodes.map(n=>[n.id,n]));ctx.strokeStyle='rgba(102,115,124,.2)';ctx.lineWidth=1/view.z;topology.edges.forEach(e=>{const a=map.get(e.source),b=map.get(e.target);if(a&&b){ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke()}});topology.nodes.forEach(n=>{ctx.beginPath();ctx.arc(n.x,n.y,n.r,0,Math.PI*2);ctx.fillStyle=color(n.kind);ctx.fill();if(view.z>1.25||(n.i<30&&view.z>.75)){ctx.fillStyle='#172026';ctx.font='10px system-ui';ctx.fillText(n.label.slice(0,12),n.x+n.r+3,n.y+4)}});ctx.restore()}
function color(k){if(/test/.test(k))return'#b45309';if(/doc|section/.test(k))return'#2563a6';if(/class|type|struct/.test(k))return'#7c3f8c';if(/function|method/.test(k))return'#087f5b';return'#66737c'}
canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,vx:view.x,vy:view.y};canvas.setPointerCapture(e.pointerId)};canvas.onpointermove=e=>{if(drag){view.x=drag.vx+e.clientX-drag.x;view.y=drag.vy+e.clientY-drag.y;draw()}};canvas.onpointerup=e=>{const moved=drag&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>4;drag=null;if(!moved)pick(e)};
canvas.onwheel=e=>{e.preventDefault();const f=e.deltaY<0?1.12:.89;view.z=Math.max(.1,Math.min(4,view.z*f));draw()};async function pick(e){const r=canvas.getBoundingClientRect(),x=(e.clientX-r.left-view.x)/view.z,y=(e.clientY-r.top-view.y)/view.z;let hit=null,best=18/view.z;topology.nodes.forEach(n=>{const d=Math.hypot(n.x-x,n.y-y);if(d<best){best=d;hit=n}});if(hit){const data=await fetch('/api/node?id='+encodeURIComponent(hit.id)).then(r=>r.json());details.innerHTML=`<strong>${esc(hit.label)}</strong><br>${esc(hit.kind)}<br>${esc(hit.path||'No source path')}<br>${data.incoming.length} incoming / ${data.outgoing.length} outgoing`}}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}window.onresize=()=>{resize();draw()};if(new URLSearchParams(location.search).get('view')==='graph'){show('graph')}
</script></body></html>"""
