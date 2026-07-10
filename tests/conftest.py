from __future__ import annotations

from graphgraph import Edge, Graph, Node


def sample_graph() -> Graph:
    return Graph(
        nodes={
            "N1": Node("N1", "AuthService", "service", "server/auth.py"),
            "N2": Node("N2", "TokenStore", "data", "server/tokens.py"),
            "N3": Node("N3", "AuditLog", "data", "server/audit.py"),
        },
        edges=[
            Edge("N1", "N2", "reads", 0.9),
            Edge("N2", "N3", "writes", 0.8),
        ],
    )
