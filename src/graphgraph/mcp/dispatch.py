"""JSON-RPC dispatch kept separate from GraphGraph MCP tool handlers."""

from __future__ import annotations

from typing import Any


def dispatch(request: dict[str, Any]) -> dict[str, Any] | None:
    # Resolve handlers at call time so existing tests and integrations that
    # patch ``graphgraph.mcp.server.handle_*`` retain their behavior.
    from . import server

    method = request.get("method")
    request_id = request.get("id")
    try:
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            result = server.handle_initialize(request.get("params") or {})
        elif method == "tools/list":
            result = server.handle_tools_list(request.get("params") or {})
        elif method == "tools/call":
            result = server.handle_tools_call(request.get("params") or {})
        else:
            raise ValueError(f"unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": str(exc)},
        }
