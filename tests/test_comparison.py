"""Counterfactuals preserve preferences and compare outcomes on a common scale."""

from copy import deepcopy
import csv
import json

import pytest

from roth.cli import main
from roth.common import RothError, digest, read_json, write_json
from roth.comparison import (
    change_label,
    compare_reports,
    load_baseline,
    prepare_scenarios,
)
from roth.market import validate_market
from roth.report import export_report
from roth.storage import empty_state
from roth.workflow import freeze, ingest_preferences, run_matching


def stable_report(tmp_path):
    market = validate_market(
        {
            "synthetic": True,
            "participants": [
                {"id": p, "name": p.upper(), "side": side}
                for side, ids in (("left", "abc"), ("right", "xy"))
                for p in ids
            ],
        }
    )
    state = empty_state()
    state["market"] = market
    rows = [
        {
            "participant_id": p,
            "ranking": ranking,
            "complete": True,
            "source": "synthetic",
        }
        for p, ranking in {
            "a": ["x", "y"],
            "b": ["x", "y"],
            "c": ["x", "y"],
            "x": ["a", "b", "c"],
            "y": ["b", "c", "a"],
        }.items()
    ]
    ingest_preferences(state, rows)
    freeze(state, "original")
    run_matching(state, "original", "original")
    export_report(state, "original", tmp_path / "report")
    return tmp_path / "report", state


def test_stable_capacity_changes_baseline_immutable_and_ordinals(tmp_path):
    report, state = stable_report(tmp_path)
    saved = digest(state)
    files = {p.name: p.read_bytes() for p in report.iterdir() if p.is_file()}
    output = tmp_path / "compare"
    compare_reports(
        report,
        [
            {"name": "extra-seat", "capacities": {"x": 2}},
            {"name": "closed", "capacities": {"x": 0}},
            {"name": "same"},
        ],
        output,
    )
    data = read_json(output / "comparison.json")
    assert data["baseline_verification"]["snapshot_hash_verified"]
    expanded, closed, same = data["scenarios"]
    rows = {r["participant_id"]: r for r in expanded["comparison"]["participants"]}
    assert rows["b"]["before"]["assigned"] == ["y"]
    assert rows["b"]["after"]["assigned"] == ["x"]
    assert rows["b"]["preference_change"] == "better_ranks"
    assert rows["c"]["before"]["assigned"] == []
    assert rows["c"]["after"]["assigned"] == ["y"]
    assert rows["x"]["after"]["assigned"] == ["a", "b"]
    assert rows["x"]["after"]["vacancies"] == 0
    assert closed["comparison"]["counts"]["worse_ranks"] >= 1
    assert same["reused_baseline"] and same["comparison"]["changed_participants"] == 0
    assert digest(state) == saved
    assert all(
        (report / name).read_bytes() == content for name, content in files.items()
    )
    assert read_json(output / "extra-seat/preferences.json") == read_json(
        report / "preferences.json"
    )
    assert all(
        r["scenario"] for r in csv.DictReader((output / "participants.csv").open())
    )
    assert "<script" not in (output / "index.html").read_text()
    with pytest.raises(RothError, match="already exists"):
        compare_reports(report, [{"name": "new"}], output)


def test_ordinal_comparison_does_not_invent_set_utility():
    assert change_label("stable", {"ranks": [1, 4]}, {"ranks": [2, 3]}) == "mixed"
    assert change_label("stable", {"ranks": []}, {"ranks": [7]}) == "better_ranks"
    assert change_label("stable", {"ranks": [1, 3]}, {"ranks": [1]}) == "worse_ranks"
    assert change_label("stable", {"ranks": []}, {"ranks": []}) == "equal"


def test_reduced_cohort_and_right_proposer(tmp_path):
    report, state = stable_report(tmp_path)
    freeze(state, "reduced", exclude=["c"])
    run_matching(state, "reduced", "reduced", side="right")
    export_report(state, "reduced", tmp_path / "reduced")
    compare_reports(
        tmp_path / "reduced",
        [{"name": "left", "proposing_side": "left"}],
        tmp_path / "comparison",
    )
    data = read_json(tmp_path / "comparison/comparison.json")
    assert data["baseline_scope"]["cohort_scope"] == "reduced"
    assert "c" not in {
        r["participant_id"] for r in data["scenarios"][0]["comparison"]["participants"]
    }
    with pytest.raises(RothError, match="active participant"):
        prepare_scenarios(
            load_baseline(tmp_path / "reduced"),
            [{"name": "absent", "capacities": {"c": 2}}],
        )


@pytest.mark.parametrize(
    "spec",
    [
        {"name": "../escape"},
        {"name": "baseline"},
        {"name": "Baseline"},
        {"name": "bad", "capacities": {"x": True}},
        {"name": "bad", "capacities": {"x": 2, "a": 2}},
        {"name": "bad", "preferences": []},
        {"name": "bad", "capacities": {"unknown": 1}},
        {"name": "bad", "proposing_side": "neither"},
    ],
)
def test_invalid_changes_do_not_create_output(tmp_path, spec):
    report, _ = stable_report(tmp_path)
    with pytest.raises(RothError):
        compare_reports(report, [{"name": "valid"}, spec], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_tampered_snapshot_rejected(tmp_path):
    report, _ = stable_report(tmp_path)
    snapshot = read_json(report / "snapshot.json")
    snapshot["coverage"] = "fabricated"
    (report / "snapshot.json").write_text(json.dumps(snapshot))
    with pytest.raises(RothError, match="snapshot"):
        load_baseline(report)


def team_report(tmp_path):
    pytest.importorskip("scipy")
    from roth.teams import solve_teams
    from roth.team_report import export_team_report

    market = {
        "synthetic": True,
        "students": [{"id": i, "name": "<script>" if i == "a" else i} for i in "abcd"],
        "projects": [{"id": p, "name": p} for p in "xyz"],
        "config": {"target_size": 2, "social_weight": 0.25},
    }
    prefs = [
        {
            "student_id": i,
            "projects": ["x", "y", "z"],
            "teammates": [j for j in "abcd" if j != i],
            "complete": True,
            "source": "synthetic",
        }
        for i in "abcd"
    ]
    result = solve_teams(market, prefs)
    export_team_report(market, prefs, result, tmp_path / "report")
    return tmp_path / "report"


def test_closed_project_preserves_borda_and_explicit_exclusions(tmp_path):
    from roth.teams import evaluate_assignment

    report = team_report(tmp_path)
    baseline = load_baseline(report)
    frozen = deepcopy(baseline)
    compare_reports(
        report,
        [
            {"name": "close-x", "close_projects": ["x"]},
            {"name": "infeasible", "close_projects": ["x", "y"]},
            {"name": "after-failure"},
        ],
        tmp_path / "out",
    )
    data = read_json(tmp_path / "out/comparison.json")
    feasible, impossible, same = data["scenarios"]
    assert feasible["status"] == "optimal"
    for row in feasible["comparison"]["participants"]:
        assert row["after"]["assigned"][0] != "x"
        assert row["after"]["ranks"][0] in (2, 3)
        expected = 0.5 if row["after"]["assigned"] == ["y"] else 0
        assert row["after"]["project_score"] == expected
    assert impossible["status"] == "infeasible" and "comparison" not in impossible
    assert same["comparison"]["changed_participants"] == 0
    variant = read_json(tmp_path / "out/close-x/market.json")
    assert variant["projects"] == baseline["market"]["projects"]
    assert (
        read_json(tmp_path / "out/close-x/preferences.json") == baseline["preferences"]
    )
    with pytest.raises(RothError, match="closed project"):
        evaluate_assignment(
            variant, baseline["preferences"], baseline["result"]["assignments"]
        )
    assert baseline == frozen
    html = (tmp_path / "out/index.html").read_text()
    assert "&lt;script&gt;" in html and "<script>" not in html


def test_target_weight_changes_use_baseline_scale(tmp_path):
    report = team_report(tmp_path)
    compare_reports(
        report,
        [
            {
                "name": "four",
                "config": {
                    "target_size": 4,
                    "min_size": 4,
                    "max_size": 4,
                    "social_weight": 0.5,
                },
            }
        ],
        tmp_path / "out",
    )
    data = read_json(tmp_path / "out/comparison.json")["scenarios"][0]
    assert data["status"] == "optimal"
    # All four share x. Each has social points 2+1+0, divided by BASELINE 2*(2-1).
    for row in data["comparison"]["participants"]:
        assert row["after"]["social_score"] == 1.5
        assert row["after"]["score"] == pytest.approx(0.75 + 0.25 * 1.5)
        assert len(row["after"]["teammates"]) == 3
    assert data["objective_score"] == pytest.approx(
        3.0
    )  # New target divisor is 2*(4-1).


def review_report(tmp_path, scoring="borda"):
    pytest.importorskip("scipy")
    from roth.reviews import solve_reviews
    from roth.review_report import export_review_report

    market = {
        "mode": "reviews",
        "synthetic": True,
        "reviewers": [{"id": i, "name": i} for i in "abc"],
        "submissions": [
            {"id": p, "title": p, "authors": [i]} for p, i in zip("xyz", "abc")
        ],
        "config": {
            "min_reviews": 1,
            "max_reviews": 1,
            "reviews_per_submission": 1,
            "scoring": scoring,
        },
    }
    prefs = (
        [
            {
                "reviewer_id": i,
                "complete": True,
                "source": "synthetic",
                **(
                    {"ranking": options}
                    if scoring == "borda"
                    else {"scores": {p: 80 - 30 * k for k, p in enumerate(options)}}
                ),
            }
            for i, options in zip("abc", (["y", "z"], ["z", "x"], ["x", "y"]))
        ]
        if scoring != "none"
        else []
    )
    result = solve_reviews(market, prefs)
    export_review_report(market, prefs, result, tmp_path / "report")
    return tmp_path / "report"


@pytest.mark.parametrize("scoring", ["borda", "scores", "none"])
def test_review_workload_not_mistaken_for_gain(tmp_path, scoring):
    report = review_report(tmp_path, scoring)
    spec = {
        "name": "two",
        "reviewer_bounds": {r: {"max_reviews": 2} for r in "abc"},
        "reviews_required": {p: 2 for p in "xyz"},
    }
    compare_reports(
        report,
        [spec, {"name": "too-many", "reviews_required": {"x": 4}}],
        tmp_path / "out",
    )
    feasible, impossible = read_json(tmp_path / "out/comparison.json")["scenarios"]
    assert feasible["status"] == "optimal"
    for row in feasible["comparison"]["participants"]:
        assert row["before"]["load"] == 1 and row["after"]["load"] == 2
        assert row["preference_change"] == (
            "unscored" if scoring == "none" else "workload_changed"
        )
        assert {"a": "x", "b": "y", "c": "z"}[row["participant_id"]] not in row[
            "after"
        ]["assigned"]
    assert impossible["status"] == "infeasible"


def test_solver_limit_without_incumbent_is_not_infeasible(tmp_path, monkeypatch):
    import roth.teams as teams

    report = team_report(tmp_path)

    def limit(*args, **kwargs):
        raise RothError("No incumbent before time limit", "SOLVER_LIMIT")

    monkeypatch.setattr(teams, "solve_teams", limit)
    compare_reports(
        report,
        [{"name": "limit", "config": {"social_weight": 0}}, {"name": "same"}],
        tmp_path / "out",
    )
    limited, same = read_json(tmp_path / "out/comparison.json")["scenarios"]
    assert limited["status"] == "solver_limit" and "comparison" not in limited
    assert same["reused_baseline"]


def test_cli_json_and_guidance(tmp_path, capsys):
    from roth.agent import next_guidance

    report = team_report(tmp_path)
    write_json(
        tmp_path / "scenarios.json",
        [{"name": "larger", "config": {"allow_larger": True, "max_size": 4}}],
    )
    assert (
        main(
            [
                "compare",
                str(report),
                "--scenarios",
                str(tmp_path / "scenarios.json"),
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 0
    )
    response = json.loads(capsys.readouterr().out)
    assert response["status"] == "ok" and response["data"]["mode"] == "teams"
    guidance = next_guidance(
        tmp_path,
        market_path=report / "market.json",
        preferences_path=report / "preferences.json",
        output=report,
    )
    assert guidance["phase"] == "review_results"
    assert guidance["what_if"]["baseline"] == str(report)
    assert (
        main(
            [
                "compare",
                str(report),
                "--scenarios",
                str(tmp_path / "scenarios.json"),
                "--output",
                str(tmp_path / "out"),
            ]
        )
        == 2
    )
    assert json.loads(capsys.readouterr().out)["status"] == "error"
