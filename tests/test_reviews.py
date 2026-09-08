"""Review assignment contracts and independent small-instance optimization checks."""

import builtins
from itertools import combinations
import json
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

from roth.agent import next_guidance
from roth.cli import main
from roth.common import RothError, write_json
from roth.review_example import review_example
from roth.review_report import verify_review_result
from roth.reviews import (
    evaluate_reviews,
    exclusion_reasons,
    review_edges,
    review_feasibility,
    review_scores,
    solve_reviews,
    validate_review_inputs,
)


def small(scoring="borda"):
    m = {
        "reviewers": [{"id": i, "name": i} for i in "abcd"],
        "submissions": [
            {"id": p, "title": p, "authors": [i]} for p, i in zip("wxyz", "abcd")
        ],
        "config": {
            "min_reviews": 1,
            "max_reviews": 1,
            "reviews_per_submission": 1,
            "scoring": scoring,
        },
    }
    rows = []
    for r in m["reviewers"]:
        options = [p["id"] for p in m["submissions"] if r["id"] not in p["authors"]]
        row = {"reviewer_id": r["id"], "complete": True, "source": "synthetic"}
        if scoring == "borda":
            row["ranking"] = options
        else:
            row["scores"] = {p: 100 - j * 20 for j, p in enumerate(options)}
        rows.append(row)
    return m, rows if scoring != "none" else []


def oracle(m, rows):
    """Enumerate edge subsets without calling Roth's verifier or scoring code."""
    people = m["reviewers"]
    papers = m["submissions"]
    rr = {r["reviewer_id"]: r for r in rows}
    pairs = [
        (r["id"], p["id"])
        for r in people
        for p in papers
        if r["id"] not in p["authors"]
        and [r["id"], p["id"]] not in m.get("excluded_pairs", [])
        and p["id"] not in rr.get(r["id"], {}).get("unacceptable", [])
    ]
    best = None
    demand = sum(p.get("reviews_required", 1) for p in papers)
    for allocation in combinations(pairs, demand):
        if any(
            sum(a == r["id"] for a, b in allocation) < r.get("min_reviews", 1)
            or sum(a == r["id"] for a, b in allocation) > r.get("max_reviews", 1)
            for r in people
        ):
            continue
        if any(
            sum(b == p["id"] for a, b in allocation) != p.get("reviews_required", 1)
            for p in papers
        ):
            continue
        total = 0
        for a, b in allocation:
            if m["config"]["scoring"] == "borda":
                universe = sum(
                    a not in p["authors"]
                    and [a, p["id"]] not in m.get("excluded_pairs", [])
                    for p in papers
                )
                order = rr[a]["ranking"]
                if b in order:
                    total += (
                        (universe - order.index(b) - 1) / max(1, universe - 1)
                        if universe > 1
                        else 1
                    )
            else:
                total += rr[a].get("scores", {}).get(b, 0) / 100
        best = total if best is None else max(best, total)
    return best


@pytest.mark.parametrize("scoring", ["borda", "scores"])
def test_exhaustive_small_markets(scoring):
    pytest.importorskip("scipy.optimize")
    rng = random.Random(17)
    for _ in range(24):
        m, rows = small(scoring)
        for r in m["reviewers"]:
            r["min_reviews"] = rng.randint(0, 1)
            r["max_reviews"] = rng.randint(1, 2)
        for p in m["submissions"]:
            p["reviews_required"] = rng.randint(0, 2)
        for row in rows:
            options = row["ranking"] if scoring == "borda" else list(row["scores"])
            rng.shuffle(options)
            row["unacceptable"] = options[-1:] if rng.random() < 0.3 else []
            options = [p for p in options if p not in row["unacceptable"]]
            count = rng.randint(0, len(options))
            if scoring == "borda":
                row["ranking"] = options[:count]
            else:
                row["scores"] = {p: rng.randint(0, 100) for p in options[:count]}
        best = oracle(m, rows)
        if best is None:
            with pytest.raises(RothError) as error:
                solve_reviews(m, rows)
            assert error.value.code == "INFEASIBLE"
        else:
            result = solve_reviews(m, rows)
            assert result["solution_status"] == "optimal"
            assert result["total_score"] == pytest.approx(best)
            assert verify_review_result(m, rows, result)["valid"]


def test_self_team_and_explicit_conflicts():
    m, rows = review_example()
    reasons = exclusion_reasons(m)
    assert reasons["s01", "p01"] == ["self_review"]
    assert "teammate_review" in reasons["s01", "p02"]
    assert reasons["s01", "p04"] == ["organizer_conflict"]
    edges, reasons = review_edges(m, rows)
    assert (rows[1]["reviewer_id"], rows[1]["unacceptable"][0]) not in edges
    m["config"]["exclude_teammates"] = False
    assert ("s01", "p02") not in exclusion_reasons(m)
    assert ("s01", "p01") in exclusion_reasons(m)
    m["eligible_pairs"] = [["s01", "p01"], ["s01", "p02"]]
    reasons = exclusion_reasons(m)
    assert "self_review" in reasons["s01", "p01"]  # allow-list cannot re-enable it
    assert "ineligible" in reasons["s01", "p03"]


@pytest.mark.parametrize(
    "change",
    [
        lambda m, p: m["config"].update(min_reviews=True),
        lambda m, p: m["reviewers"][0].update(max_reviews=-1),
        lambda m, p: m["reviewers"][0].update(min_reviews=3, max_reviews=2),
        lambda m, p: m["submissions"][0].update(authors=["missing"]),
        lambda m, p: m["submissions"][0].update(authors=[]),
        lambda m, p: m["submissions"][0].update(reviews_required=1.5),
        lambda m, p: m["config"].update(typo=1),
        lambda m, p: p.pop(),
        lambda m, p: p[0].update(complete=False),
        lambda m, p: p[0].update(ranking=["w"]),
        lambda m, p: p[0].update(ranking=["x", "x"]),
        lambda m, p: p[0].update(unacceptable=["x"]),
        lambda m, p: p[0].update(scores={"x": 10}),
    ],
)
def test_invalid_contracts(change):
    m, p = small()
    change(m, p)
    with pytest.raises(RothError):
        validate_review_inputs(m, p)


@pytest.mark.parametrize("value", [True, -1, 101, float("nan"), float("inf"), "50"])
def test_invalid_scores(value):
    m, p = small("scores")
    p[0]["scores"]["x"] = value
    with pytest.raises(RothError):
        validate_review_inputs(m, p)


def test_partial_zero_score_distinct_from_excluded_and_missing():
    m, p = small()
    p[0]["ranking"] = ["x"]
    p[0]["unacceptable"] = ["z"]
    m, p = validate_review_inputs(m, p)
    assert (
        review_scores(m, p)["a"]["x"] == 1
    )  # fixed universe of three, not submitted list size
    edges, reasons = review_edges(m, p)
    assert ("a", "y") in edges and ("a", "z") not in edges
    assert review_scores(m, p)["a"].get("y", 0) == 0
    with pytest.raises(RothError, match="Missing reviewer"):
        validate_review_inputs(m, p[1:])
    m["config"]["scoring"] = "none"
    assert validate_review_inputs(m, [])[1] == []
    with pytest.raises(RothError, match="discard"):
        validate_review_inputs(m, p)


def test_shared_bottleneck_not_just_total_counts():
    pytest.importorskip("scipy.optimize")
    m, _ = small("none")
    m["config"]["min_reviews"] = 0
    m["submissions"] = [
        {"id": p, "title": p, "authors": ["d" if p in "wx" else "a"]} for p in "wxyz"
    ]
    m["eligible_pairs"] = [
        ["a", "w"],
        ["a", "x"],
        ["b", "y"],
        ["b", "z"],
        ["c", "y"],
        ["c", "z"],
        ["d", "y"],
        ["d", "z"],
    ]
    m, p = validate_review_inputs(m, [])
    assert review_feasibility(m, p)["necessary_checks_pass"]
    with pytest.raises(RothError, match="bottleneck") as error:
        solve_reviews(m, p)
    assert error.value.code == "INFEASIBLE"


def test_verifier_rejects_duplicate_conflict_and_wrong_coverage():
    m, p = small()
    good = [["a", "x"], ["b", "w"], ["c", "z"], ["d", "y"]]
    assert evaluate_reviews(m, p, good)["valid"]
    for bad in [
        good[:-1],
        good + [good[0]],
        [["a", "w"]] + good[1:],
        [["a", "x"], ["a", "z"], ["c", "z"], ["d", "y"]],
    ]:
        with pytest.raises(RothError) as error:
            evaluate_reviews(m, p, bad)
        assert error.value.code == "INVALID_SOLUTION"


def test_empty_allocation_and_optional_solver(monkeypatch):
    m = {
        "reviewers": [{"id": "a", "name": "A"}],
        "submissions": [{"id": "x", "title": "X", "authors": ["a"]}],
        "config": {
            "min_reviews": 0,
            "max_reviews": 0,
            "reviews_per_submission": 0,
            "scoring": "none",
        },
    }
    assert solve_reviews(m, [])["assignments"] == []
    real_import = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "scipy":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    m, p = small()
    with pytest.raises(RothError) as error:
        solve_reviews(m, p)
    assert error.value.code == "MISSING_DEPENDENCY"


def test_solver_limits_and_invalid_incumbents(monkeypatch):
    opt = pytest.importorskip("scipy.optimize")
    m, p = small()
    actual_milp = opt.milp
    seen = []

    def limited(*args, **kwargs):
        result = actual_milp(*args, **kwargs)
        result.status = 1
        seen.append(result)
        return result

    monkeypatch.setattr(opt, "milp", limited)
    result = solve_reviews(m, p)
    assert result["solution_status"] == "feasible_limit"
    assert not result["solver"]["optimal"]
    for fake, code in [
        (SimpleNamespace(status=1, message="limit", x=None), "SOLVER_LIMIT"),
        (SimpleNamespace(status=4, message="error"), "SOLVER_ERROR"),
        (
            SimpleNamespace(status=1, message="fractional", x=[0.5] * 12),
            "INVALID_SOLUTION",
        ),
    ]:
        monkeypatch.setattr(opt, "milp", lambda *a, **kw: fake)
        with pytest.raises(RothError) as error:
            solve_reviews(m, p)
        assert error.value.code == code


def test_cli_agent_report_cycle_and_tamper_detection(tmp_path, capsys):
    pytest.importorskip("scipy.optimize")

    def call(*argv):
        code = main(list(map(str, argv)))
        output = json.loads(capsys.readouterr().out)
        assert code == 0, output
        return output["data"]

    root = tmp_path / "class review"
    assert next_guidance(root, scenario="reviews")["phase"] == "define_market"
    call("reviews", "example", root)
    assert not (root / ".roth").exists()
    validated = call(
        "reviews",
        "validate",
        root / "market.json",
        "--preferences",
        root / "preferences.json",
    )
    assert validated["checks"]["necessary_checks_pass"]
    guide = call("--project", root, "agent", "next")
    assert guide["scenario"] == "reviews" and guide["phase"] == "solve"
    result = call(*guide["actions"][0]["argv"][1:])
    assert len(result["assignments"]) == 36
    assert set(result["statistics"]["reviewer_loads"].values()) == {3}
    assert set(result["statistics"]["submission_coverage"].values()) == {3}
    report = Path(result["report"])
    html = report.read_text()
    assert html.count('class="assigned"') == 36 and "<script" not in html
    assert (report.parent / "submitted-preferences.json").exists()
    assert call(*guide["rerun"][1:])["complete"]
    assert not (root / ".roth").exists()
    before = report.read_bytes()
    raw = json.loads((root / "preferences.json").read_text())
    raw[0]["ranking"].reverse()
    (root / "preferences.json").write_text(json.dumps(raw))
    next_step = next_guidance(root)
    assert next_step["next_output"].endswith("report-2")
    assert report.read_bytes() == before
    (root / "preferences.json").write_bytes(
        (report.parent / "submitted-preferences.json").read_bytes()
    )
    saved = json.loads((report.parent / "result.json").read_text())
    saved["solution_status"] = "feasible_limit"
    saved["solver"]["optimal"] = False
    (report.parent / "result.json").write_text(json.dumps(saved))
    limited = next_guidance(root)
    assert (
        limited["phase"] == "review_results"
        and not limited["complete"]
        and limited["questions"]
    )
    saved["statistics"]["assignments"] += 1
    (report.parent / "result.json").write_text(json.dumps(saved))
    assert next_guidance(root)["phase"] == "inspect_result"
    code = main(
        [
            "reviews",
            "solve",
            str(root / "market.json"),
            "--preferences",
            str(root / "preferences.json"),
            "--output",
            str(report.parent),
        ]
    )
    assert code == 2 and json.loads(capsys.readouterr().out)["errors"]


def test_agent_collection_inputs_and_infeasibility(tmp_path, monkeypatch):
    m, p = small()
    write_json(tmp_path / "market.json", m)
    assert next_guidance(tmp_path)["phase"] == "collect_preferences"
    assert (
        next_guidance(tmp_path, collection="delegated")["phase"]
        == "unsupported_collection"
    )
    assert (
        next_guidance(tmp_path, scenario="many-to-one")["phase"]
        == "resolve_scenario_conflict"
    )
    write_json(tmp_path / "preferences.json", p)
    monkeypatch.setattr(
        "roth.agent_reviews.importlib.util.find_spec", lambda name: None
    )
    guide = next_guidance(tmp_path)
    assert guide["phase"] == "install_solver"
    assert guide["actions"][0]["network"]
    m["config"]["max_reviews"] = 0
    m["config"]["min_reviews"] = 0
    (tmp_path / "market.json").write_text(json.dumps(m))
    assert next_guidance(tmp_path)["phase"] == "resolve_feasibility"
