from __future__ import annotations

import copy
import unittest
from pathlib import Path

from graphgraph.research.registry import load_research_registry, validate_research_registry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "eval" / "context-system-research.json"


class ResearchRegistryTest(unittest.TestCase):
    def test_registry_is_referentially_complete_and_grounded(self) -> None:
        registry = load_research_registry(REGISTRY)

        self.assertEqual(validate_research_registry(registry, root=ROOT), [])
        claim_ids = {row["claim_id"] for row in registry["claims"]}
        candidate_ids = {row["candidate_id"] for row in registry["candidates"]}
        self.assertTrue({f"GPA-H{number}" for number in range(1, 9)} <= claim_ids)
        self.assertTrue({"GPA-GREEDY-LIMIT-001", "GPA-METRIC-LIMIT-001"} <= claim_ids)
        self.assertTrue({"I0", "C1", "C2", "C3", "C4", "C5", "C5-ONE-STEP"} <= candidate_ids)

    def test_registry_rejects_unknown_experiment_and_evidence_free_promotion(self) -> None:
        registry = load_research_registry(REGISTRY)
        broken = copy.deepcopy(registry)
        broken["claims"][0]["status"] = "promoted"
        broken["claims"][0]["experiment_ids"] = ["EXP-MISSING"]
        broken["claims"][0]["evidence"] = []

        errors = validate_research_registry(broken, root=ROOT)

        self.assertTrue(any("unknown experiment EXP-MISSING" in error for error in errors))
        self.assertTrue(any("terminal evidence status" in error for error in errors))

    def test_hypotheses_remain_unpromoted_until_experiments_finish(self) -> None:
        registry = load_research_registry(REGISTRY)
        hypotheses = [row for row in registry["claims"] if row["claim_id"].startswith("GPA-H")]

        self.assertTrue(hypotheses)
        self.assertTrue(all(row["status"] == "specified" for row in hypotheses))
        linked = {experiment["experiment_id"]: experiment["status"] for experiment in registry["experiments"]}
        self.assertTrue(all(linked[claim["experiment_ids"][0]] == "pending" for claim in hypotheses))


    def test_every_candidate_beyond_an_idea_has_an_experiment(self) -> None:
        # The ledger enforced "no claim without an experiment" but not the same
        # for candidates, so C1-HYBRID-RESERVE-003 reached the production CLI
        # while recorded as `specified` with nothing able to decide it.
        registry = load_research_registry(REGISTRY)
        tested = {
            candidate_id
            for experiment in registry["experiments"]
            for candidate_id in experiment.get("candidate_ids", ())
        }
        untested = sorted(
            row["candidate_id"]
            for row in registry["candidates"]
            if row["status"] != "idea" and row["candidate_id"] not in tested
        )
        self.assertEqual(untested, [])

    def test_implemented_candidates_are_not_promoted_without_a_passing_experiment(self) -> None:
        registry = load_research_registry(REGISTRY)
        status_by_experiment = {
            row["experiment_id"]: row["status"] for row in registry["experiments"]
        }
        for candidate in registry["candidates"]:
            if candidate["status"] != "promoted":
                continue
            deciding = [
                status_by_experiment[experiment["experiment_id"]]
                for experiment in registry["experiments"]
                if candidate["candidate_id"] in experiment.get("candidate_ids", ())
            ]
            self.assertIn(
                "passing",
                deciding,
                f"{candidate['candidate_id']} is promoted with no passing experiment",
            )

    def test_the_shipped_reserve_candidate_records_its_ungated_state(self) -> None:
        registry = load_research_registry(REGISTRY)
        shipped = next(
            row
            for row in registry["candidates"]
            if row["candidate_id"] == "C1-HYBRID-RESERVE-003"
        )
        # It is in the production package and reachable from the CLI, so the
        # ledger must say `implemented`. It must never say `promoted` unless
        # its deciding experiment actually passed -- the invariant, not the
        # snapshot: the experiment has since run and failed.
        self.assertEqual(shipped["status"], "implemented")
        self.assertIn("hybrid_reserve_v1", shipped["implementation"])
        deciding = next(
            row
            for row in registry["experiments"]
            if row["experiment_id"] == "EXP-GPA-HYBRID-RESERVE"
        )
        self.assertNotEqual(shipped["status"], "promoted")
        if deciding["status"] != "passing":
            self.assertNotEqual(
                shipped["status"],
                "promoted",
                "the reserve cannot be promoted while its experiment is not passing",
            )
        self.assertIn(deciding["status"], {"pending", "failing", "inconclusive", "passing"})


if __name__ == "__main__":
    unittest.main()
