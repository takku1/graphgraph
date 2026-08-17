"""Ontology, frontend, and traversal-description CLI commands."""

from __future__ import annotations

import argparse
import json

from ..graph.ontology import relation_records
from ..graph.traversal import policy_records
from ..scanner.frontends import available_frontends


def cmd_ontology(args: argparse.Namespace) -> None:
    for row in relation_records(args.family):
        weak = " weak" if row["weak"] else ""
        print(
            f"{row['name']}: family={row['family']} strength={row['strength']:g} "
            f"direction={row['direction']}{weak} - {row['description']}"
        )


def cmd_frontends(_args: argparse.Namespace) -> None:
    data = [capability.__dict__ for capability in available_frontends()]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_traversal(args: argparse.Namespace) -> None:
    print(
        json.dumps(
            policy_records(args.query_class),
            indent=2,
            ensure_ascii=False,
        )
    )


__all__ = ["cmd_frontends", "cmd_ontology", "cmd_traversal"]
