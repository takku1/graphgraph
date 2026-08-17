from __future__ import annotations

import tempfile
from pathlib import Path

from graphgraph import remove_paths, scan_directory, update_paths
from graphgraph.io import save_graph
from graphgraph.scanner.frontends.persistent_facts import (
    PersistentPythonTypeIndex,
    join_python_project_type_facts,
    python_file_type_snapshot,
)


def test_python_snapshot_records_class_parent_edges() -> None:
    snapshot = python_file_type_snapshot(
        "class User(Base, Mixin):\n    pass\n",
        "models.py",
    )
    assert ["python", "User", "Base"] in snapshot["parents"]
    assert ["python", "User", "Mixin"] in snapshot["parents"]


def test_project_fact_join_keeps_parent_edges() -> None:
    snapshots = {
        "base.py": python_file_type_snapshot(
            "class Base:\n    def save(self):\n        return 1\n",
            "base.py",
        ),
        "models.py": python_file_type_snapshot(
            "class User(Base):\n    pass\n",
            "models.py",
        ),
    }
    facts = join_python_project_type_facts(snapshots)
    assert ("python", "User", "Base") in facts.parents


def test_typescript_snapshot_records_extends_and_fields() -> None:
    from graphgraph.scanner.frontends.persistent_facts import frontend_file_type_snapshot

    snapshot = frontend_file_type_snapshot(
        "export class User extends Base {\n  client: Client;\n}\n",
        "models.ts",
    )
    assert snapshot["language"] == "typescript"
    assert ["typescript", "User", "Base"] in snapshot["parents"]
    assert any(row[:2] == ["User", "client"] for row in snapshot["fields"])


def test_incremental_typescript_consumer_keeps_inherited_method_edge() -> None:
    base = "export class Base {\n  save(): number { return 1; }\n}\n"
    models = "import { Base } from './base';\nexport class User extends Base {}\n"
    consumer = (
        "import { User } from './models';\n"
        "export function persist(user: User): number {\n"
        "  return user.save();\n"
        "}\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "base.ts").write_text(base, encoding="utf-8")
        (root / "models.ts").write_text(models, encoding="utf-8")
        (root / "consumer.ts").write_text(consumer, encoding="utf-8")
        graph_path = root / ".graphgraph" / "graph.json"
        manifest_path = root / ".graphgraph" / "manifest.json"
        baseline = scan_directory(
            root,
            depth="symbols",
            frontend="auto",
            manifest_path=manifest_path,
        )
        save_graph(baseline, graph_path)
        inherited = {
            (edge.source, edge.target)
            for edge in baseline.edges
            if edge.type == "calls"
            and baseline.nodes[edge.source].label == "persist"
            and baseline.nodes[edge.target].label == "save"
        }
        assert inherited, "full scan must resolve User.save through Base"

        (root / "consumer.ts").write_text(consumer + "\n// touch\n", encoding="utf-8")
        incremental = update_paths(
            root,
            ["consumer.ts"],
            depth="symbols",
            frontend="auto",
            previous_graph_path=graph_path,
            manifest_path=manifest_path,
        )

    assert {
        (edge.source, edge.target)
        for edge in incremental.edges
        if edge.type == "calls"
        and incremental.nodes[edge.source].label == "persist"
        and incremental.nodes[edge.target].label == "save"
    } == inherited


def _assert_field_change_promotes_consumer(
    *,
    provider_name: str,
    consumer_name: str,
    old_provider: str,
    new_provider: str,
    consumer: str,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / provider_name).write_text(old_provider, encoding="utf-8")
        (root / consumer_name).write_text(consumer, encoding="utf-8")
        graph_path = root / ".graphgraph" / "graph.json"
        manifest_path = root / ".graphgraph" / "manifest.json"
        baseline = scan_directory(
            root,
            depth="symbols",
            frontend="auto",
            manifest_path=manifest_path,
        )
        save_graph(baseline, graph_path)
        (root / provider_name).write_text(new_provider, encoding="utf-8")
        incremental = update_paths(
            root,
            [provider_name],
            depth="symbols",
            frontend="auto",
            previous_graph_path=graph_path,
            manifest_path=manifest_path,
        )
    assert incremental.metadata["incremental_type_files_promoted"] == "1"


def test_rust_field_change_promotes_consumer() -> None:
    _assert_field_change_promotes_consumer(
        provider_name="provider.rs",
        consumer_name="consumer.rs",
        old_provider="pub struct Client { pub store: Store }\n",
        new_provider="pub struct Client { pub store: Other }\n",
        consumer="fn use_it(c: Client) { c.store.save(); }\n",
    )


def test_cpp_field_change_promotes_consumer() -> None:
    _assert_field_change_promotes_consumer(
        provider_name="provider.cpp",
        consumer_name="consumer.cpp",
        old_provider="class Client { public: Store store; };\n",
        new_provider="class Client { public: Other store; };\n",
        consumer="void use_it(Client c) { c.store.save(); }\n",
    )


def test_go_field_change_promotes_consumer() -> None:
    _assert_field_change_promotes_consumer(
        provider_name="provider.go",
        consumer_name="consumer.go",
        old_provider="package p\n\ntype Client struct {\n\tStore Store\n}\n",
        new_provider="package p\n\ntype Client struct {\n\tStore Other\n}\n",
        consumer="package p\n\nfunc Use(c Client) { c.Store.Save() }\n",
    )


def test_frontend_snapshot_records_member_obligations() -> None:
    from graphgraph.scanner.frontends.persistent_facts import frontend_file_type_snapshot

    rust = frontend_file_type_snapshot(
        "fn use_it(c: Client) { c.store.save(); }\n",
        "consumer.rs",
    )
    assert ["field", "", "store"] in rust["obligations"]
    go = frontend_file_type_snapshot(
        "package p\nfunc Use(c Client) { c.Store.Save() }\n",
        "consumer.go",
    )
    assert ["field", "", "Store"] in go["obligations"]


def test_incremental_consumer_keeps_inherited_method_edge() -> None:
    base = "class Base:\n    def save(self):\n        return 1\n"
    models = "class User(Base):\n    pass\n"
    consumer = (
        "from models import User\n\n"
        "def persist(user: User):\n"
        "    return user.save()\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "base.py").write_text(base, encoding="utf-8")
        (root / "models.py").write_text(models, encoding="utf-8")
        (root / "consumer.py").write_text(consumer, encoding="utf-8")
        graph_path = root / ".graphgraph" / "graph.json"
        manifest_path = root / ".graphgraph" / "manifest.json"
        baseline = scan_directory(
            root,
            depth="symbols",
            frontend="auto",
            manifest_path=manifest_path,
        )
        save_graph(baseline, graph_path)
        inherited = {
            (edge.source, edge.target)
            for edge in baseline.edges
            if edge.type == "calls"
            and baseline.nodes[edge.source].label == "persist"
            and baseline.nodes[edge.target].label == "save"
        }
        assert inherited

        (root / "consumer.py").write_text(consumer + "\n# touch\n", encoding="utf-8")
        incremental = update_paths(
            root,
            ["consumer.py"],
            depth="symbols",
            frontend="auto",
            previous_graph_path=graph_path,
            manifest_path=manifest_path,
        )

    assert {
        (edge.source, edge.target)
        for edge in incremental.edges
        if edge.type == "calls"
        and incremental.nodes[edge.source].label == "persist"
        and incremental.nodes[edge.target].label == "save"
    } == inherited


def test_project_fact_join_propagates_package_reexports_and_ambiguity() -> None:
    snapshots = {
        "pkg/one.py": python_file_type_snapshot(
            "def build() -> First:\n    return First()\n",
            "pkg/one.py",
        ),
        "pkg/two.py": python_file_type_snapshot(
            "def build() -> Second:\n    return Second()\n",
            "pkg/two.py",
        ),
        "pkg/__init__.py": python_file_type_snapshot(
            "from one import build\nfrom two import build\n",
            "pkg/__init__.py",
        ),
    }

    facts = join_python_project_type_facts(snapshots)

    assert facts.returns[("pkg", "build")].types == frozenset({"First", "Second"})
    assert facts.returns[("pkg", "build")].concrete is None


def test_affected_join_work_is_independent_of_unrelated_fact_volume() -> None:
    old = {
        "provider.py": python_file_type_snapshot(
            "def build() -> Old:\n    return Old()\n",
            "provider.py",
        ),
        "consumer.py": python_file_type_snapshot(
            "from provider import build\n\ndef use():\n    return build().run()\n",
            "consumer.py",
        ),
    }
    for index in range(250):
        rel = f"unrelated_{index}.py"
        old[rel] = python_file_type_snapshot(
            f"value_{index}: Type{index}\n",
            rel,
        )
    index = PersistentPythonTypeIndex.from_snapshots(old)
    old_changed = {"provider.py": old["provider.py"]}
    new_changed = {
        "provider.py": python_file_type_snapshot(
            "def build() -> New:\n    return New()\n",
            "provider.py",
        )
    }

    changed = index.update(
        old_changed,
        new_changed,
        {"provider.py"},
    )
    affected = index.affected_files(
        changed,
        excluded_files={"provider.py"},
    )

    assert affected.files == frozenset({"consumer.py"})
    assert affected.changed_facts == 1
    assert affected.affected_obligations == 1


def test_changed_fact_propagates_through_reexport_worklist() -> None:
    old_model = python_file_type_snapshot(
        "def build() -> Old:\n    return Old()\n",
        "pkg/model.py",
    )
    new_model = python_file_type_snapshot(
        "def build() -> New:\n    return New()\n",
        "pkg/model.py",
    )
    snapshots = {
        "pkg/model.py": old_model,
        "pkg/__init__.py": python_file_type_snapshot(
            "from model import build\n",
            "pkg/__init__.py",
        ),
        "consumer.py": python_file_type_snapshot(
            "from pkg import build\n\ndef use():\n    return build().run()\n",
            "consumer.py",
        ),
    }
    index = PersistentPythonTypeIndex.from_snapshots(snapshots)

    changed = index.update(
        {"pkg/model.py": old_model},
        {"pkg/model.py": new_model},
        {"pkg/model.py"},
    )
    affected = index.affected_files(
        changed,
        excluded_files={"pkg/model.py"},
    )

    assert changed == frozenset(
        {
            ("return", "model", "build"),
            ("return", "pkg", "build"),
        }
    )
    assert affected.files == frozenset({"pkg/__init__.py", "consumer.py"})


def test_incremental_return_fact_change_equals_full_rebuild() -> None:
    old_provider = (
        "class Old:\n"
        "    def ping(self):\n"
        "        return 1\n\n"
        "class New:\n"
        "    def ping(self):\n"
        "        return 2\n\n"
        "def make() -> Old:\n"
        "    return Old()\n"
    )
    new_provider = old_provider.replace(
        "def make() -> Old:\n    return Old()\n",
        "def make() -> New:\n    return New()\n",
    )
    consumer = "from provider import make\n\ndef use():\n    value = make()\n    return value.ping()\n"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "provider.py").write_text(old_provider, encoding="utf-8")
        (root / "consumer.py").write_text(consumer, encoding="utf-8")
        graph_path = root / ".graphgraph" / "graph.json"
        manifest_path = root / ".graphgraph" / "manifest.json"
        baseline = scan_directory(
            root,
            depth="symbols",
            frontend="auto",
            manifest_path=manifest_path,
        )
        save_graph(baseline, graph_path)

        (root / "provider.py").write_text(new_provider, encoding="utf-8")
        incremental = update_paths(
            root,
            ["provider.py"],
            depth="symbols",
            frontend="auto",
            previous_graph_path=graph_path,
            manifest_path=manifest_path,
        )
        rebuilt = scan_directory(
            root,
            depth="symbols",
            frontend="auto",
        )

    assert incremental.nodes == rebuilt.nodes
    assert sorted(incremental.edges, key=repr) == sorted(rebuilt.edges, key=repr)
    assert incremental.metadata["incremental_type_facts_changed"] == "1"
    assert incremental.metadata["incremental_type_obligations_affected"] == "1"
    assert incremental.metadata["incremental_type_files_promoted"] == "1"

    ping_targets = {
        incremental.nodes[edge.target].parent
        for edge in incremental.edges
        if edge.type == "calls"
        and incremental.nodes.get(edge.source) is not None
        and incremental.nodes[edge.source].label == "use"
        and incremental.nodes.get(edge.target) is not None
        and incremental.nodes[edge.target].label == "ping"
    }
    assert {incremental.nodes[parent].label for parent in ping_targets} == {"New"}


def test_incremental_field_fact_change_equals_full_rebuild() -> None:
    old_provider = (
        "class Old:\n"
        "    def ping(self):\n"
        "        return 1\n\n"
        "class New:\n"
        "    def ping(self):\n"
        "        return 2\n\n"
        "class Context:\n"
        "    value: Old\n"
    )
    new_provider = old_provider.replace("value: Old", "value: New")
    consumer = (
        "from provider import Context\n\n"
        "def use(context: Context):\n"
        "    value = context.value\n"
        "    return value.ping()\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "provider.py").write_text(old_provider, encoding="utf-8")
        (root / "consumer.py").write_text(consumer, encoding="utf-8")
        graph_path = root / ".graphgraph" / "graph.json"
        manifest_path = root / ".graphgraph" / "manifest.json"
        baseline = scan_directory(
            root,
            depth="symbols",
            frontend="auto",
            manifest_path=manifest_path,
        )
        save_graph(baseline, graph_path)

        (root / "provider.py").write_text(new_provider, encoding="utf-8")
        incremental = update_paths(
            root,
            ["provider.py"],
            depth="symbols",
            frontend="auto",
            previous_graph_path=graph_path,
            manifest_path=manifest_path,
        )
        rebuilt = scan_directory(root, depth="symbols", frontend="auto")

    assert incremental.nodes == rebuilt.nodes
    assert sorted(incremental.edges, key=repr) == sorted(rebuilt.edges, key=repr)
    assert incremental.metadata["incremental_type_facts_changed"] == "1"
    assert incremental.metadata["incremental_type_obligations_affected"] == "1"
    assert incremental.metadata["incremental_type_files_promoted"] == "1"


def test_removing_fact_provider_rejoins_unchanged_consumer() -> None:
    provider = (
        "class Service:\n"
        "    def ping(self):\n"
        "        return 1\n\n"
        "def make() -> Service:\n"
        "    return Service()\n"
    )
    consumer = (
        "from provider import make\n\n"
        "def use():\n"
        "    value = make()\n"
        "    return value.ping()\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "provider.py").write_text(provider, encoding="utf-8")
        (root / "consumer.py").write_text(consumer, encoding="utf-8")
        graph_path = root / ".graphgraph" / "graph.json"
        manifest_path = root / ".graphgraph" / "manifest.json"
        baseline = scan_directory(
            root,
            depth="symbols",
            frontend="auto",
            manifest_path=manifest_path,
        )
        save_graph(baseline, graph_path)

        (root / "provider.py").unlink()
        incremental = remove_paths(
            root,
            ["provider.py"],
            depth="symbols",
            frontend="auto",
            previous_graph_path=graph_path,
            manifest_path=manifest_path,
        )
        rebuilt = scan_directory(root, depth="symbols", frontend="auto")

    assert incremental.nodes == rebuilt.nodes
    assert sorted(incremental.edges, key=repr) == sorted(rebuilt.edges, key=repr)
    assert incremental.metadata["incremental_type_facts_changed"] == "1"
    assert incremental.metadata["incremental_type_files_promoted"] == "1"
