"""Reference embedding endpoint for GraphGraph's optional semantic backend.

GraphGraph's semantic index defaults to a dependency-free hashed bag-of-words,
which cannot match paraphrases (measured 0/4 recall). Point
``GRAPHGRAPH_EMBED_URL`` at a real embedding endpoint and it uses real vectors
instead. This is such an endpoint, kept out of the package so the tool stays
dependency-free; it is the piece a black-box evaluator needs to measure GATE 23
(semantic recall) against a real model.

Usage:

    pip install sentence-transformers    # one-time, ~90 MB model on first run
    python scripts/reference_embedding_server.py --port 8477
    # in another shell:
    GRAPHGRAPH_EMBED_URL=http://127.0.0.1:8477 graphgraph query "<paraphrase>"

The server speaks the shape ``HttpEmbeddingBackend`` expects: POST
``{"input": [text, ...]}`` -> ``{"embeddings": [[float, ...], ...]}``.

It refuses to start without a real model rather than silently serving a stub,
so a green run cannot come from a fake backend -- the same
prize-the-honest-signal discipline the tool applies elsewhere.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


def _load_model(name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise SystemExit(
            "sentence-transformers is not installed. Run:\n"
            "    pip install sentence-transformers\n"
            "This server intentionally refuses to serve stub vectors."
        ) from exc
    print(f"loading model {name!r} (first run downloads it) ...")
    model = SentenceTransformer(name)
    print(f"model loaded; embedding dimension = {model.get_sentence_embedding_dimension()}")
    return model


def build_handler(model):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quieter logs
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                texts = list(body.get("input", []))
                vectors = model.encode(texts, normalize_embeddings=True).tolist()
                payload = json.dumps({"embeddings": vectors}).encode("utf-8")
                self.send_response(200)
            except Exception as exc:  # pragma: no cover - defensive
                payload = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8477)
    parser.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="Any sentence-transformers model id (default: all-MiniLM-L6-v2, 384-dim).",
    )
    args = parser.parse_args()

    model = _load_model(args.model)
    server = HTTPServer((args.host, args.port), build_handler(model))
    url = f"http://{args.host}:{args.port}"
    print(f"serving embeddings at {url}")
    print(f"set:  GRAPHGRAPH_EMBED_URL={url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.server_close()


if __name__ == "__main__":
    main()
