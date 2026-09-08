"""Capacity matching checked against an independent enumeration oracle."""

import itertools
import json
from pathlib import Path
import random

import pytest

from roth import deferred_acceptance, verify_matching
from roth.agent import next_guidance
from roth.cli import main
from roth.common import RothError
from roth.example import mentorship_example
from roth.market import load_side, validate_market
from roth.storage import Store
from roth.workflow import freeze, ingest_preferences, run_matching


def stable_outcomes(left, right, quotas):
    """Enumerate assignments of unit-capacity left participants, independently."""
    outcomes = []
    for choices in itertools.product(*[[None] + order for order in left.values()]):
        assigned = dict(zip(left, choices))
        groups = {b: [a for a in left if assigned[a] == b] for b in right}
        if any(
            len(group) > quotas[b] or any(a not in right[b] for a in group)
            for b, group in groups.items()
        ):
            continue
        blocked = False
        for a, order in left.items():
            for b in order:
                if a not in right[b] or assigned[a] == b:
                    continue
                wants = assigned[a] is None or order.index(b) < order.index(assigned[a])
                admits = quotas[b] > 0 and (
                    len(groups[b]) < quotas[b]
                    or any(right[b].index(a) < right[b].index(c) for c in groups[b])
                )
                blocked |= wants and admits
        if not blocked:
            outcomes.append(
                sorted([a, b] for a, b in assigned.items() if b is not None)
            )
    return outcomes


def test_random_capacity_markets_against_exhaustive_oracle():
    rng = random.Random(711)
    for _ in range(100):
        left = {f"e{i}": [] for i in range(rng.randint(1, 5))}
        right = {f"m{i}": [] for i in range(rng.randint(1, 3))}
        quotas = {p: rng.randint(0, 3) for p in right}
        for own, other in ((left, right), (right, left)):
            for p in own:
                own[p] = rng.sample(list(other), rng.randrange(len(other) + 1))
        stable = stable_outcomes(left, right, quotas)
        assert stable
        for side in ("left", "right"):
            result = deferred_acceptance(left, right, side, quotas)
            assert result["matches"] in stable
            assert len(result["trace"]) <= sum(
                len(order) for order in (left if side == "left" else right).values()
            )
            # The same market works with capacities placed on the left.
            flipped = deferred_acceptance(
                right, left, "right" if side == "left" else "left", quotas
            )
            assert sorted([b, a] for a, b in flipped["matches"]) == result["matches"]
            if side == "left":
                actual = dict(result["matches"])
                for alternative in stable:
                    other = dict(alternative)
                    for a, order in left.items():
                        rank = order.index(actual[a]) if a in actual else len(order)
                        other_rank = order.index(other[a]) if a in other else len(order)
                        assert rank <= other_rank


def test_replacement_vacancies_and_proposing_side_difference():
    left = {"a": ["x", "y"], "b": ["y", "x"], "c": ["x"]}
    right = {"x": ["c", "b", "a"], "y": ["a", "b"]}
    quotas = {"x": 2}
    assert deferred_acceptance(left, right, capacities=quotas)["matches"] == [
        ["a", "x"],
        ["b", "y"],
        ["c", "x"],
    ]
    assert deferred_acceptance(left, right, "right", quotas)["matches"] == [
        ["a", "y"],
        ["b", "x"],
        ["c", "x"],
    ]
    result = deferred_acceptance(
        {"a": ["x"], "b": ["x"], "c": ["x"]},
        {"x": ["c", "b", "a"]},
        capacities={"x": 2},
    )
    assert result["matches"] == [["b", "x"], ["c", "x"]]
    assert result["trace"][-1]["displaced"] == "a"
    assert result["vacancies"] == {"a": 1, "b": 0, "c": 0, "x": 0}
    assert verify_matching(left, right, [["c", "x"]], quotas)["blocking_pairs"]
    assert not verify_matching(left, right, [["c", "x"], ["c", "x"]], quotas)[
        "feasible"
    ]
    assert not verify_matching(
        left, right, [["a", "x"], ["b", "x"], ["c", "x"]], quotas
    )["feasible"]
    assert verify_matching({"a": ["x"]}, {"x": ["a"]}, [], {"x": 0})["stable"]
    assert (
        deferred_acceptance({"a": ["x"]}, {"x": ["a"]}, capacities={"x": 0})[
            "unmatched"
        ]["x"]
        == "zero_capacity"
    )


@pytest.mark.parametrize("capacity", [-1, 1.5, True, "3", None])
def test_invalid_capacity_contract(capacity):
    market, _ = mentorship_example(2, 1)
    market["participants"][-1]["capacity"] = capacity
    with pytest.raises(RothError, match="Capacity"):
        validate_market(market)
    with pytest.raises(RothError, match="Capacity"):
        deferred_acceptance({"a": ["x"]}, {"x": ["a"]}, capacities={"x": capacity})


def test_reject_many_to_many_and_unknown_capacity_ids():
    with pytest.raises(RothError, match="Many-to-many"):
        deferred_acceptance({"a": ["x"]}, {"x": ["a"]}, capacities={"a": 2, "x": 2})
    with pytest.raises(RothError, match="Unknown capacity"):
        deferred_acceptance({"a": []}, {}, capacities={"missing": 2})


def test_csv_capacity_import(tmp_path):
    path = tmp_path / "mentors.csv"
    path.write_text("id,name,capacity\nx,Mentor,3\ny,Mentor 2,\n")
    people = load_side(path, "right")
    market = validate_market({"participants": people})
    assert market["participants"][0]["capacity"] == 3
    assert market["participants"][1].get("capacity", 1) == 1
    path.write_text("id,name,capacity\nx,Mentor,1.5\n")
    with pytest.raises(RothError, match="CSV capacity"):
        load_side(path, "right")


def test_mentorship_agent_lifecycle_and_reports(tmp_path, capsys):
    def call(*argv):
        code = main(list(map(str, argv)))
        result = json.loads(capsys.readouterr().out)
        assert code == 0, result
        return result["data"]

    root = tmp_path / "mentorship study"
    call("example", "mentorship", root)
    assert not Store(root).load()["preferences"]
    phases = []
    for _ in range(7):
        data = call("--project", root, "agent", "next")
        assert data["scenario"] == "many-to-one"
        phases.append(data["phase"])
        if data["complete"]:
            break
        for action in data["actions"]:
            assert not action["network"]
            call(*action["argv"][1:])
    assert phases == [
        "import_preferences",
        "freeze_preferences",
        "match",
        "export_report",
        "review_results",
    ]
    assert call("--project", root, "validate")["valid"]
    state = Store(root).load()
    run = next(iter(state["runs"].values()))
    assert len(run["matches"]) == 30
    assert all(v == 0 for v in run["vacancies"].values())
    stats = run["statistics"]["by_side"]["right"]
    assert stats["match_rate"]["numerator"] == 10
    assert stats["slot_fill_rate"] == {"numerator": 30, "denominator": 30, "rate": 1}
    assert all(len(rs) == 3 for rs in stats["assigned_partner_rank_lists"].values())
    assert stats["assigned_partner_ranks"] == {}
    directory = Path(data["report"]).parent
    mentor = json.loads((directory / "individual/m001.json").read_text())
    assert len(mentor["partners"]) == 3 and "partner" not in mentor
    assert not {"contact", "preferences"}.intersection(mentor["partners"][0])
    employee = json.loads((directory / "individual/e001.json").read_text())
    assert employee["partner"] == employee["partners"][0]
    html = (directory / "index.html").read_text()
    assert html.count('class="matched"') == 30
    assert "Rankings and realized matches" in html and "Capacity and vacancies" in html
    assert "<script" not in html
    # Explicit completed inputs preserve the many-to-one route through recursion.
    assert (
        next_guidance(root, preferences_path=root / "preferences.json")["scenario"]
        == "many-to-one"
    )


def test_snapshot_capacity_survives_market_changes(tmp_path):
    market, rows = mentorship_example(4, 2, 3)
    store = Store(tmp_path)
    with store.lock(create=True):
        state = store.load()
        state["market"] = market
        ingest_preferences(state, rows)
        freeze(state, "original", exclude=["e004"])
        state["market"]["participants"][-1]["capacity"] = 0
        result = run_matching(state, "original", "saved")
    assert result["capacities"]["m002"] == 3
    assert "e004" not in result["capacities"]
    assert result["statistics"]["by_side"]["right"]["unfilled_slots"] == 3
    assert len(result["matches"]) == 3


def test_many_to_one_human_and_delegated_artifacts(tmp_path):
    from roth.delegation import build_plan
    from roth.fielding import build_field, ingest_field, OUTSIDE

    market, _ = mentorship_example(4, 1, 2)
    store = Store(tmp_path)
    with store.lock(create=True):
        state = store.load()
    state["market"] = market
    build_field(state, "human", tmp_path / "human", native=False, only=["m001"])
    package = next(iter(state["fields"]["human"]["packages"].values()))
    assert "up to 2 partners" in package["questions"][0]["question_text"]
    answers = {}
    for q in package["questions"]:
        answers[q["question_name"]] = (
            q["question_options"] if q["kind"] == "rank" else "Assessed"
        )
    assert OUTSIDE in answers["ranking"]
    ingest_field(
        state,
        "human",
        [
            {
                "package_id": package["id"],
                "participant_id": "m001",
                "submission_id": "first",
                "answers": answers,
            }
        ],
    )
    assert (
        len(state["preferences"]["m001"]["ranking"]) == 4
    )  # not truncated to capacity
    state["market"]["config"]["delegation"] = "delegated"
    build_plan(state, "score", tmp_path / "score", model="test", native=False)
    tasks = state["score_plans"]["score"]["tasks"]
    mentor_tasks = [t for t in tasks if t["participant_id"] == "m001"]
    assert len(mentor_tasks) == 4
    assert all(
        t["capacity"] == 2 and "independently" in t["prompt"] for t in mentor_tasks
    )
    from roth.benchmark import build_benchmark
    from roth.delegation import ingest_scores

    ingest_scores(
        state,
        "score",
        [
            {
                "task_id": t["task_id"],
                "acceptability": "acceptable",
                "score": i,
                "evidence": ["Synthetic fixture"],
                "explanation": "Synthetic fixture",
            }
            for i, t in enumerate(tasks)
        ],
        source="synthetic",
    )
    build_benchmark(state, "check", tmp_path / "check", "score", native=False)
    questions = [
        q
        for package in state["fields"]["check"]["packages"].values()
        for q in package["questions"]
    ]
    assert any("Your capacity is 2" in q["question_text"] for q in questions)
    assert any("additional slot empty" in q["question_text"] for q in questions)
