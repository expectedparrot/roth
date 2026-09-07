import json
from pathlib import Path

from roth.cli import main
from roth.storage import Store


def call(capsys, *argv):
    code = main(list(map(str, argv)))
    output = json.loads(capsys.readouterr().out)
    return code, output


def test_offline_demo_and_validation(tmp_path, capsys):
    root = tmp_path / "internships"
    code, result = call(capsys, "demo", root)
    assert code == 0 and result["status"] == "ok"
    assert Path(result["data"]["report"]).exists()
    code, result = call(capsys, "--project", root, "validate")
    assert code == 0 and result["data"]["valid"]
    state = Store(root).load()
    assert len(state["market"]["participants"]) == 22
    assert state["runs"]["main"]["verification"]["stable"]
    individual = json.loads(
        next((root / "report/individual").glob("*.json")).read_text()
    )
    assert "preferences" not in str(individual) and "email" not in str(individual)


def test_error_envelopes_and_atomic_failed_import(tmp_path, capsys):
    root = tmp_path / "project"
    assert call(capsys, "example", "create", root)[0] == 0
    rows = json.loads((root / "preferences.json").read_text())
    rows[-1]["ranking"] = ["unknown"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(rows))
    code, result = call(capsys, "--project", root, "preferences", "import", bad)
    assert code == 2 and result["errors"]
    assert not Store(root).load()["preferences"]
    code, result = call(capsys, "nonsense")
    assert code == 2 and result["errors"][0]["code"] == "USAGE_ERROR"


def test_complete_synthetic_calibration_cli(tmp_path, capsys):
    root = tmp_path / "delegated"
    assert (
        call(capsys, "example", "create", root, "--students", 5, "--internships", 4)[0]
        == 0
    )

    def ok(*args):
        code, response = call(capsys, "--project", root, *args)
        assert code == 0, response
        return response["data"]

    ok(
        "score",
        "plan",
        "--name",
        "base",
        "--model",
        "test",
        "--k",
        5,
        "--output",
        root / "base",
        "--json-only",
    )
    ok("example", "scores", "--name", "base", "--output", root / "base-scores.json")
    ok(
        "score",
        "import",
        root / "base-scores.json",
        "--name",
        "base",
        "--source",
        "synthetic",
    )
    ok(
        "benchmark",
        "build",
        "--name",
        "check",
        "--scores",
        "base",
        "--pairs",
        4,
        "--output",
        root / "check",
        "--json-only",
    )
    ok(
        "example",
        "benchmark",
        "--name",
        "check",
        "--split",
        "calibration",
        "--output",
        root / "calibration.json",
    )
    ok(
        "benchmark",
        "import",
        root / "calibration.json",
        "--name",
        "check",
        "--source",
        "synthetic",
    )
    ok(
        "score",
        "plan",
        "--name",
        "revised",
        "--model",
        "test",
        "--k",
        5,
        "--calibration",
        "check",
        "--expand",
        "base",
        "--output",
        root / "revised",
        "--json-only",
    )
    ok(
        "example",
        "scores",
        "--name",
        "revised",
        "--output",
        root / "revised-scores.json",
    )
    ok(
        "score",
        "import",
        root / "revised-scores.json",
        "--name",
        "revised",
        "--source",
        "synthetic",
    )
    ok(
        "benchmark",
        "predict",
        "--name",
        "check",
        "--scores",
        "revised",
        "--label",
        "a_revised",
    )
    ok(
        "example",
        "benchmark",
        "--name",
        "check",
        "--split",
        "evaluation",
        "--output",
        root / "evaluation.json",
    )
    report = ok(
        "benchmark",
        "import",
        root / "evaluation.json",
        "--name",
        "check",
        "--source",
        "synthetic",
    )
    assert set(report["models"]) == {"baseline", "a_revised"}
    ok("score", "apply", "--name", "revised")
    ok("preferences", "freeze", "--name", "inferred")
    result = ok("match", "--snapshot", "inferred", "--name", "inferred")
    assert result["verification"]["stable"] and "check" in result["benchmarks"]
    assert result["scope"]["preference_sources"] == ["synthetic"]
    ok("report", "--run", "inferred", "--output", root / "report")
    ok("validate")


def test_next_marks_exported_demo_complete(tmp_path, capsys):
    root = tmp_path / "done"
    assert call(capsys, "demo", root)[0] == 0
    code, result = call(capsys, "--project", root, "next")
    assert code == 0 and result["data"]["complete"]
    assert result["next_steps"] == []
