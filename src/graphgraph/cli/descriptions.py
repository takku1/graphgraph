"""Ontology, frontend, and traversal-description CLI commands."""

from __future__ import annotations

import argparse
import json

from ..graph.ontology import DEFAULT_RELATIONS
from ..graph.traversal import POLICIES, traversal_policy
from ..scanner.frontends import available_frontends


def cmd_ontology(args: argparse.Namespace) -> None:
    for name, spec in DEFAULT_RELATIONS.items():
        if args.family and spec.family != args.family:
            continue
        weak = " weak" if spec.weak else ""
        print(
            f"{name}: family={spec.family} strength={spec.strength:g} "
            f"direction={spec.direction}{weak} - {spec.description}"
        )


def cmd_frontends(_args: argparse.Namespace) -> None:
    data = [capability.__dict__ for capability in available_frontends()]
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_traversal(args: argparse.Namespace) -> None:
    if args.query_class:
        print(
            json.dumps(
                traversal_policy(args.query_class).__dict__,
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    print(
        json.dumps(
            {name: policy.__dict__ for name, policy in POLICIES.items()},
            indent=2,
            ensure_ascii=False,
        )
    )


__all__ = ["cmd_frontends", "cmd_ontology", "cmd_traversal"]
