from graphgraph.scanner.resolution_report import heldout_precision_table


def test_heldout_volume_table_meets_precision_gate() -> None:
    report = heldout_precision_table()
    assert report["metric"] == "receiver_resolution_precision"
    assert report["value"] >= 0.98
    assert report["recall"] >= 0.98
    assert report["false_owners"] == 0
    assert {"ts", "cs", "py", "go"} <= set(report["by_language"])
    for language in ("ts", "cs", "py", "go"):
        row = report["by_language"][language]
        assert row["found"] == row["expected"], language
        assert row["false_owners"] == 0, language
        assert row["precision"] >= 0.98, language
    assert "volume" in report["by_language"]["polyglot_fixture"]
