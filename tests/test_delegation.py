import copy

import pytest

from roth.common import RothError
from roth.delegation import (
    build_plan,
    ingest_scores,
    apply_scores,
    calibration_evidence,
)
from roth.benchmark import (
    build_benchmark,
    import_answers,
    freeze_predictions,
    constrain_ranking,
)


def fake_scores(plan):
    return [
        {
            "task_id": t["task_id"],
            "acceptability": "acceptable",
            "score": float(i % 99),
            "evidence": ["Synthetic evidence"],
            "explanation": "Synthetic evaluation",
        }
        for i, t in enumerate(plan["tasks"])
    ]


def prepare(state, tmp_path):
    build_plan(state, "base", tmp_path / "base", "test-model", k=5, native=False)
    ingest_scores(
        state, "base", fake_scores(state["score_plans"]["base"]), source="synthetic"
    )


def answers_for(benchmark, split):
    return [
        {
            "question_id": q["id"],
            "choice": "Somewhat prefer A",
            "a_acceptable": "Acceptable",
            "b_acceptable": "Acceptable",
            "explanation": "Example tradeoff",
        }
        for q in benchmark["questions"]
        if q["split"] == split
    ]


def test_bidirectional_budget_cache_expansion(tmp_path, state):
    result = build_plan(
        state, "small", tmp_path / "small", "test-model", k=1, native=False
    )
    plan = state["score_plans"]["small"]
    assert result["directed_evaluations"] == 2 * len(plan["edges"])
    directions = {(t["participant_id"], t["candidate_id"]) for t in plan["tasks"]}
    assert all((b, a) in directions for a, b in directions)
    rows = fake_scores(plan)
    ingest_scores(state, "small", rows[:2], source="synthetic")
    with pytest.raises(RothError, match="incomplete"):
        apply_scores(state, "small")
    ingest_scores(state, "small", rows[2:], source="synthetic")
    expanded = build_plan(
        state,
        "larger",
        tmp_path / "larger",
        "test-model",
        k=2,
        expand="small",
        native=False,
    )
    assert expanded["cached"] == len(plan["tasks"])
    assert set(map(tuple, plan["edges"])) <= set(
        map(tuple, state["score_plans"]["larger"]["edges"])
    )
    with pytest.raises(RothError, match="budget"):
        build_plan(
            state,
            "budget",
            tmp_path / "budget",
            "test-model",
            k=5,
            budget=1,
            native=False,
        )


def test_score_validation_and_human_preservation(tmp_path, state):
    prepare(state, tmp_path)
    plan = state["score_plans"]["base"]
    bad = {**fake_scores(plan)[0], "score": float("nan")}
    with pytest.raises(RothError, match="finite"):
        ingest_scores(state, "base", [bad])
    row = copy.deepcopy(state["example_preferences"][0])
    row["source"] = "human"
    state["preferences"][row["participant_id"]] = row
    apply_scores(state, "base")
    assert state["preferences"][row["participant_id"]] == row


def test_heldout_isolation_and_prediction_freeze(tmp_path, state):
    prepare(state, tmp_path)
    build_benchmark(state, "check", tmp_path / "check", "base", pairs=4, native=False)
    b = state["benchmarks"]["check"]
    calibration = answers_for(b, "calibration")
    import_answers(state, "check", calibration, source="synthetic")
    feedback = calibration_evidence(state, "check")
    assert sum(map(len, feedback.values())) == len(calibration)
    build_plan(
        state,
        "revised",
        tmp_path / "revised",
        "test-model",
        k=5,
        calibration="check",
        native=False,
    )
    assert (
        state["score_plans"]["base"]["tasks"][0]["task_id"]
        != state["score_plans"]["revised"]["tasks"][0]["task_id"]
    )
    ingest_scores(
        state,
        "revised",
        fake_scores(state["score_plans"]["revised"]),
        source="synthetic",
    )
    freeze_predictions(state, "check", "revised", "revised")
    heldout = answers_for(b, "evaluation")
    report = import_answers(state, "check", heldout, source="synthetic")
    assert set(report["models"]) == {"baseline", "revised"}
    assert calibration_evidence(state, "check") == feedback
    with pytest.raises(RothError, match="already revealed"):
        freeze_predictions(state, "check", "revised", "leaked")


def test_reject_both_and_pairwise_cycle(tmp_path, state):
    prepare(state, tmp_path)
    build_benchmark(state, "check", tmp_path / "check", "base", pairs=4, native=False)
    b = state["benchmarks"]["check"]
    q = b["questions"][0]
    import_answers(
        state,
        "check",
        [
            {
                "question_id": q["id"],
                "choice": "Somewhat prefer A",
                "a_acceptable": "Unacceptable",
                "b_acceptable": "Unacceptable",
                "explanation": "Neither suitable",
            }
        ],
    )
    ranking, rejected = constrain_ranking(
        state, q["participant_id"], [q["a"], q["b"]], set()
    )
    assert ranking == [] and rejected == {q["a"], q["b"]}
    b["questions"] = [
        {
            "id": f"q{i}",
            "participant_id": "s001",
            "a": a,
            "b": c,
            "split": "calibration",
            "selection": "diagnostic",
        }
        for i, (a, c) in enumerate(
            [("i001", "i002"), ("i002", "i003"), ("i003", "i001")]
        )
    ]
    b["answers"] = {
        q["id"]: {
            "choice": "Somewhat prefer A",
            "a_acceptable": "Acceptable",
            "b_acceptable": "Acceptable",
        }
        for q in b["questions"]
    }
    with pytest.raises(RothError, match="cycle"):
        constrain_ranking(state, "s001", ["i001", "i002", "i003"], set())


def test_model_parameters_change_cache_and_validate_results(tmp_path, state):
    build_plan(
        state,
        "cold",
        tmp_path / "cold",
        "test",
        k=1,
        native=False,
        parameters={"temperature": 0},
    )
    build_plan(
        state,
        "warm",
        tmp_path / "warm",
        "test",
        k=1,
        native=False,
        parameters={"temperature": 1},
    )
    assert {t["task_id"] for t in state["score_plans"]["cold"]["tasks"]}.isdisjoint(
        t["task_id"] for t in state["score_plans"]["warm"]["tasks"]
    )
    row = fake_scores(state["score_plans"]["cold"])[0]
    row["model"] = {"model": "test", "parameters": {"temperature": 1}}
    with pytest.raises(RothError, match="parameter"):
        ingest_scores(state, "cold", [row])


def test_organizer_hybrid_policy_scores_only_delegated_side(tmp_path, state):
    state["market"]["config"]["side_policies"] = {"left": "direct"}
    for p in state["market"]["participants"]:
        if p["side"] == "left":
            p["preferences"] = ""
    build_plan(state, "hybrid", tmp_path / "hybrid", "test", k=2, native=False)
    plan = state["score_plans"]["hybrid"]
    assert all(t["participant_id"].startswith("i") for t in plan["tasks"])
    ingest_scores(state, "hybrid", fake_scores(plan), source="synthetic")
    result = apply_scores(state, "hybrid")
    assert set(result["skipped_human_or_direct"]) == {f"s{i:03d}" for i in range(1, 6)}
    assert all(p.startswith("i") for p in state["preferences"])


def test_gate_applies_to_current_scores_and_retirement(tmp_path, state):
    state["market"]["config"].update(
        benchmark_policy="gate", benchmark_min_answers=1, benchmark_min_accuracy=0
    )
    build_plan(state, "plan", tmp_path / "plan", "test", k=5, native=False)
    ingest_scores(state, "plan", fake_scores(state["score_plans"]["plan"]))
    apply_scores(state, "plan")
    from roth.workflow import freeze

    with pytest.raises(RothError, match="passing benchmark"):
        freeze(state, "blocked")
    build_benchmark(state, "check", tmp_path / "check", "plan", pairs=2, native=False)
    import_answers(
        state, "check", answers_for(state["benchmarks"]["check"], "evaluation")
    )
    with pytest.raises(RothError, match="Pairwise evidence changed"):
        freeze(state, "stale")
    apply_scores(state, "plan", replace=True)
    freeze(state, "passed")
    state["benchmarks"]["check"]["retired"] = True
    with pytest.raises(RothError, match="passing benchmark"):
        freeze(state, "retired")
