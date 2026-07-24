from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from graphgraph.cli.parser import build_parser

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TARGETS = {
    ".agents/mcp_config.json",
    ".agents/plugins/marketplace.json",
    ".agents/skills/graphgraph/SKILL.md",
    ".agents/skills/graphgraph/examples/mcp_server_settings.json",
    ".agents/skills/graphgraph/scripts/validate_live.py",
    "plugins/graphgraph/.codex-plugin/plugin.json",
    "plugins/graphgraph/.mcp.json",
    "plugins/graphgraph/skills/graphgraph/SKILL.md",
    "plugins/graphgraph/skills/graphgraph/examples/mcp_server_settings.json",
    "plugins/graphgraph/skills/graphgraph/scripts/validate_live.py",
}


class DistributionArtifactTest(unittest.TestCase):
    def test_every_tracked_artifact_names_a_canonical_source_and_is_current(self) -> None:
        from graphgraph.distribution import distribution_artifact_status

        status = distribution_artifact_status(ROOT)

        self.assertEqual({item.path.as_posix() for item in status}, EXPECTED_TARGETS)
        self.assertTrue(all(item.source for item in status))
        self.assertTrue(all(item.current for item in status), status)

    def test_sync_is_byte_stable_and_check_detects_drift(self) -> None:
        from graphgraph.distribution import (
            distribution_artifact_status,
            sync_distribution_artifacts,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync_distribution_artifacts(root)
            first = {
                item.path.as_posix(): (root / item.path).read_bytes()
                for item in distribution_artifact_status(root)
            }
            sync_distribution_artifacts(root)
            second = {
                item.path.as_posix(): (root / item.path).read_bytes()
                for item in distribution_artifact_status(root)
            }
            self.assertEqual(first, second)

            target = root / "plugins" / "graphgraph" / ".mcp.json"
            target.write_text("stale\n", encoding="utf-8")
            drift = [item for item in distribution_artifact_status(root) if not item.current]
            self.assertEqual([item.path.as_posix() for item in drift], ["plugins/graphgraph/.mcp.json"])
            sync_distribution_artifacts(root)
            self.assertTrue(all(item.current for item in distribution_artifact_status(root)))

    def test_artifacts_cli_supports_check_and_sync(self) -> None:
        parser = build_parser()
        check = parser.parse_args(["artifacts", "--check"])
        sync = parser.parse_args(["artifacts", "--root", "somewhere"])

        self.assertTrue(check.check)
        self.assertFalse(sync.check)
        self.assertEqual(sync.root, "somewhere")

    def test_packaged_assets_include_every_file_backed_canonical_source(self) -> None:
        from graphgraph.distribution import FILE_BACKED_SOURCES

        assets = ROOT / "src" / "graphgraph" / "assets"
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "assets"
            shutil.copytree(assets, copied)
            self.assertEqual(
                {path.name for path in copied.iterdir() if path.is_file()},
                set(FILE_BACKED_SOURCES),
            )


if __name__ == "__main__":
    unittest.main()
