"""Check the MILP against exhaustive discrete assignments, not its own encoding."""

from itertools import product
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("scipy.optimize")

from roth.cli import main
from roth.common import RothError
from roth.teams import borda, evaluate_assignment, solve_teams, validate_team_inputs


def small_market(weight=0.5):
    market = {
        "students": [{"id": i, "name": i.upper()} for i in "abcde"],
        "projects": [{"id": p, "name": p.upper()} for p in "xyz"],
        "config": {
            "target_size": 3,
            "allow_smaller": True,
            "allow_larger": True,
            "min_size": 2,
            "max_size": 4,
            "social_weight": weight,
        },
    }
    preferences = [
        {
            "student_id": i,
            "projects": order,
            "teammates": peers,
            "complete": True,
            "source": "synthetic",
            "incompatible_teammates": ["e"] if i == "a" else [],
            "unacceptable_projects": ["z"] if i == "b" else [],
        }
        for i, order, peers in [
            ("a", ["x", "y"], ["b", "c"]),
            ("b", ["y", "x"], ["a"]),
            ("c", ["z", "y", "x"], ["d", "e"]),
            ("d", ["x", "z"], ["c"]),
            ("e", [], ["a", "d"]),
        ]
    ]
    return market, preferences


def exhaustive(market, prefs):
    ids = [s["id"] for s in market["students"]]
    projects = [p["id"] for p in market["projects"]]
    config = market["config"]
    best = None
    for allocation in product(projects, repeat=len(ids)):
        mapping = dict(zip(ids, allocation))
        sizes = [allocation.count(p) for p in projects if p in allocation]
        if any(s < config["min_size"] or s > config["max_size"] for s in sizes):
            continue
        if any(
            mapping[r["student_id"]] in r["unacceptable_projects"]
            or any(
                mapping[j] == mapping[r["student_id"]]
                for j in r["incompatible_teammates"]
            )
            for r in prefs
        ):
            continue
        score = 0
        for r in prefs:
            i = r["student_id"]
            project_points = sum(
                (len(projects) - index - 1)
                for index, p in enumerate(r["projects"])
                if p == mapping[i]
            )
            teammate_points = sum(
                (len(ids) - index - 2)
                for index, j in enumerate(r["teammates"])
                if mapping[j] == mapping[i]
            )
            score += (
                (1 - config["social_weight"]) * project_points / (len(projects) - 1)
            )
            score += (
                config["social_weight"]
                * teammate_points
                / ((len(ids) - 2) * (config["target_size"] - 1))
            )
        key = (sum(abs(s - config["target_size"]) for s in sizes), -score)
        if best is None or key < best:
            best = key
    return best


@pytest.mark.parametrize("weight", [0, 0.35, 1])
def test_joint_optimum_matches_exhaustive_enumeration(weight):
    market, preferences = small_market(weight)
    expected = exhaustive(market, preferences)
    result = solve_teams(market, preferences)
    assert result["solution_status"] == "optimal"
    assert result["size_deviation"] == expected[0] == 1
    assert result["total_score"] == pytest.approx(-expected[1])
    assert sorted(len(t["students"]) for t in result["teams"]) == [2, 3]
    assert result["assignments"]["a"] != result["assignments"]["e"]
    assert result["assignments"]["b"] != "z"
    assert result["statistics"]["unranked_project_assignments"] >= 1


def test_borda_uses_full_universe_and_preserves_zero_ranked_choice():
    assert borda(["x"], 3) == {"x": 2}
    assert borda(["x", "y", "z"], 3) == {"x": 2, "y": 1, "z": 0}
    assert borda(["x"], 1) == {"x": 1}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m, r: r.pop(),
        lambda m, r: r[0].update(complete=False),
        lambda m, r: r[0].update(teammates=["a"]),
        lambda m, r: r[0].update(projects=["x", "x"]),
        lambda m, r: r[0].update(projects=["unknown"]),
        lambda m, r: r[0].update(unacceptable_projects=["x"]),
        lambda m, r: m["config"].update(allow_smaller=False),
        lambda m, r: m["config"].update(social_weight=float("nan")),
        lambda m, r: m["config"].update(target_size=True),
        lambda m, r: m["config"].update(project_capacity=2),
    ],
)
def test_invalid_or_missing_preferences_and_configuration(mutation):
    market, rows = small_market()
    mutation(market, rows)
    with pytest.raises(RothError):
        validate_team_inputs(market, rows)


def test_solver_reports_infeasibility_without_relaxing_constraints():
    market, rows = small_market()
    for row in rows:
        row["teammates"] = []
        row["incompatible_teammates"] = [r["student_id"] for r in rows if r is not row]
    with pytest.raises(RothError, match="No feasible") as error:
        solve_teams(market, rows)
    assert error.value.code == "INFEASIBLE"


def test_impossible_size_arithmetic():
    market, rows = small_market()
    market["config"] = {"target_size": 3}
    with pytest.raises(RothError) as error:
        solve_teams(market, rows)
    assert error.value.code == "INFEASIBLE"


def test_independent_checker_rejects_invalid_assignments():
    market, rows = small_market()
    with pytest.raises(RothError, match="size bounds"):
        evaluate_assignment(market, rows, dict.fromkeys("abcde", "x"))
    with pytest.raises(RothError, match="incompatible"):
        evaluate_assignment(market, rows, dict(zip("abcde", "xyyyx")))


def test_solver_limit_without_incumbent_is_structured(monkeypatch):
    import scipy.optimize

    monkeypatch.setattr(
        scipy.optimize,
        "milp",
        lambda *a, **kw: SimpleNamespace(status=1, x=None, message="time limit"),
    )
    with pytest.raises(RothError) as error:
        solve_teams(*small_market())
    assert error.value.code == "SOLVER_LIMIT"


@pytest.mark.parametrize("phase", ["team_size", "preferences"])
def test_solver_limit_with_incumbent_does_not_claim_optimality(monkeypatch, phase):
    import scipy.optimize

    real = scipy.optimize.milp
    calls = []

    def limited(*args, **kwargs):
        calls.append(1)
        result = real(*args, **kwargs)
        if phase == "team_size" or len(calls) == 2:
            result.status, result.message = 1, "time limit"
        return result

    monkeypatch.setattr(scipy.optimize, "milp", limited)
    result = solve_teams(*small_market())
    assert result["valid"] and result["solution_status"] == "feasible_limit"
    assert not result["solver"]["phases"][phase]["optimal"]


def test_preference_timeout_without_new_incumbent_preserves_feasible_size_solution(
    monkeypatch,
):
    import scipy.optimize

    real = scipy.optimize.milp
    calls = []

    def limited(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return real(*args, **kwargs)
        return SimpleNamespace(status=1, x=None, fun=None, message="time limit")

    monkeypatch.setattr(scipy.optimize, "milp", limited)
    result = solve_teams(*small_market())
    assert result["valid"] and result["solution_status"] == "feasible_limit"
    assert result["solver"]["phases"]["team_size"]["optimal"]


def test_cli_example_freezes_inputs_and_renders_actual_matrix(tmp_path, capsys):
    def call(*args):
        code = main(list(map(str, args)))
        return code, json.loads(capsys.readouterr().out)

    root = tmp_path / "classroom"
    assert call("teams", "example", root)[0] == 0
    market, prefs = root / "market.json", root / "preferences.json"
    assert not (root / "report").exists()
    assert call("teams", "validate", market, "--preferences", prefs)[0] == 0
    code, output = call(
        "teams", "solve", market, "--preferences", prefs, "--output", root / "report"
    )
    assert code == 0, output
    result = output["data"]
    assert result["solution_status"] == "optimal"
    assert result["statistics"]["students"] == 12 and result["statistics"]["teams"] == 4
    page = Path(result["report"]).read_text()
    assert "<script" not in page
    assert page.count("data-student=") == 12 * 5 + 12 * 11
    assert page.count("<small>ASSIGNED</small>") == 12
    assert page.count("<small>TEAM</small>") == 24
    assert json.loads(
        (root / "report/submitted-preferences.json").read_text()
    ) == json.loads(prefs.read_text())
    assert (
        call(
            "teams",
            "solve",
            market,
            "--preferences",
            prefs,
            "--output",
            root / "report",
        )[0]
        == 2
    )


def test_report_escapes_names(tmp_path):
    from roth.team_report import export_team_report

    market, rows = small_market()
    market["students"][0]["name"] = '<script>alert("bad")</script>'
    result = solve_teams(market, rows)
    report = export_team_report(market, rows, result, tmp_path / "report")
    text = Path(report["report"]).read_text()
    assert "<script>" not in text and "&lt;script&gt;" in text
