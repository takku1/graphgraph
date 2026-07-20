from __future__ import annotations

import csv
import json
import math
import sqlite3
import struct
from pathlib import Path

from format_benchmark import make_graph

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "out"
BITPACK_DIR = OUT / "bitpack"
RESULTS_CSV = BITPACK_DIR / "bitpack_results.csv"
RESULTS_MD = BITPACK_DIR / "bitpack_results.md"


def label_bytes(graph: dict) -> int:
    return sum(len(node["name"].encode("utf-8")) + 8 for node in graph["nodes"])


def json_min_bytes(graph: dict) -> int:
    return len(json.dumps(graph, separators=(",", ":")).encode("utf-8"))


def sqlite_bytes(graph: dict, path: Path) -> int:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(
        """
        create table nodes(id integer primary key, name text not null, type text not null);
        create table edges(source integer not null, target integer not null, relation integer not null, weight integer not null);
        create index edge_source_idx on edges(source);
        create index edge_target_idx on edges(target);
        """
    )
    for node in graph["nodes"]:
        cur.execute("insert into nodes values (?, ?, ?)", (int(node["id"]), node["name"], node["type"]))
    for edge in graph["edges"]:
        cur.execute(
            "insert into edges values (?, ?, ?, ?)",
            (int(edge["source"]), int(edge["target"]), 1, int(edge["dependency"] * 10000)),
        )
    con.commit()
    con.close()
    return path.stat().st_size


def write_binary_edge_table(graph: dict, path: Path) -> int:
    # GGB1: magic, node_count u32, edge_count u32, then fixed records:
    # source u32, target u32, relation u16, weight_basis_points u16.
    with path.open("wb") as f:
        f.write(b"GGB1")
        f.write(struct.pack("<II", len(graph["nodes"]), len(graph["edges"])))
        for edge in graph["edges"]:
            f.write(
                struct.pack(
                    "<IIHH",
                    int(edge["source"]),
                    int(edge["target"]),
                    1,
                    int(edge["dependency"] * 10000),
                )
            )
    return path.stat().st_size


def csr_binary_bytes(graph: dict) -> int:
    node_count = len(graph["nodes"])
    edge_count = len(graph["edges"])
    ptr = (node_count + 1) * 4
    col = edge_count * 4
    rel = edge_count * 2
    weight = edge_count * 2
    header = 12
    return header + ptr + col + rel + weight


def dense_bitmap_bytes(graph: dict, with_relation_weight: bool = False) -> int:
    node_count = len(graph["nodes"])
    bitset = math.ceil((node_count * node_count) / 8)
    if not with_relation_weight:
        return bitset
    # Dense bitmap can mark edge existence compactly, but relation/weight still
    # need side arrays for each present edge.
    return bitset + (len(graph["edges"]) * 4)


def run() -> list[dict]:
    BITPACK_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for size in [3, 12, 50, 200, 1200, 10000]:
        graph = make_graph(size)
        edge_count = len(graph["edges"])
        labels = label_bytes(graph)
        candidates = [
            ("json_minified", json_min_bytes(graph), True, "human-ish text"),
            ("sqlite_indexed", sqlite_bytes(graph, BITPACK_DIR / f"graph_{size}.sqlite"), True, "machine db"),
            ("binary_edge_table_topology", write_binary_edge_table(graph, BITPACK_DIR / f"graph_{size}.ggb"), False, "machine binary"),
            ("binary_edge_table_plus_labels", write_binary_edge_table(graph, BITPACK_DIR / f"graph_{size}_labels.ggb") + labels, True, "machine binary + dictionary"),
            ("csr_binary_topology", csr_binary_bytes(graph), False, "machine csr"),
            ("csr_binary_plus_labels", csr_binary_bytes(graph) + labels, True, "machine csr + dictionary"),
            ("dense_bitmap_topology", dense_bitmap_bytes(graph), False, "machine bitmap"),
            ("dense_bitmap_plus_edge_attrs", dense_bitmap_bytes(graph, with_relation_weight=True) + labels, True, "bitmap + attrs + dictionary"),
        ]
        min_bytes = min(c[1] for c in candidates)
        for name, byte_count, has_labels, note in candidates:
            rows.append(
                {
                    "nodes": size,
                    "edges": edge_count,
                    "format": name,
                    "bytes": byte_count,
                    "bytes_per_edge": round(byte_count / max(1, edge_count), 3),
                    "relative_to_best": round(byte_count / min_bytes, 4),
                    "has_llm_labels": has_labels,
                    "note": note,
                }
            )
    return rows


def write(rows: list[dict]) -> None:
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    lines = [
        "# Binary / Bitmap Storage Benchmark",
        "",
        "This measures machine storage, not direct LLM prompt tokens. Binary and bitmap forms must be decoded into a text/token packet before a normal LLM API can use them.",
        "",
        "| Nodes | Edges | Format | Bytes | Bytes/edge | vs best | Has labels | Note |",
        "| ---: | ---: | --- | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['nodes']} | {row['edges']} | {row['format']} | {row['bytes']} | "
            f"{row['bytes_per_edge']} | {row['relative_to_best']} | {row['has_llm_labels']} | {row['note']} |"
        )
    lines.extend([
        "",
        "Read:",
        "",
        "- `dense_bitmap_topology` is only good for edge-existence tests. It loses relation type, weight, and labels unless side channels are added.",
        "- `csr_binary_topology` is the likely machine-query floor for sparse weighted project graphs.",
        "- `csr_binary_plus_labels` is closer to a complete local graph store.",
        "- None of these are direct LLM-native unless the inference runtime accepts custom binary/embedding/KV memory.",
    ])
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    rows = run()
    write(rows)
    print(RESULTS_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

