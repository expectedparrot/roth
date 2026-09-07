"""Offline native EDSL artifact/Results round trips; no provider or Humanize calls."""

import pytest

edsl = pytest.importorskip("edsl")

from roth.edsl_bridge import load_object, field_results, score_results
from roth.fielding import build_field, ingest_field
from roth.delegation import build_plan, ingest_scores
from roth.benchmark import build_benchmark, import_field_answers
from test_fielding import submission
from test_delegation import fake_scores


def results_object(survey, agent, scenario, answer):
    from edsl.results.result import Result

    model = edsl.Model("test")
    result = Result(
        agent=agent,
        scenario=scenario,
        model=model,
        iteration=0,
        answer=answer,
        survey=survey,
    )
    return edsl.Results(survey=survey, data=[result])


def test_human_native_rank_and_result_identity(tmp_path, state):
    root = tmp_path / "human"
    build_field(state, "human", root, native=True, only=["s001"])
    packages = state["fields"]["human"]["packages"]
    package = next(iter(packages.values()))
    folder = root / package["id"]
    survey = load_object("Survey", folder / "survey.ep")
    agents = load_object("AgentList", folder / "agent_list.ep")
    jobs = load_object("Jobs", folder / "jobs.ep")
    assert len(jobs.models) == 0
    assert "preferences" not in agents[0].traits
    answer = submission(package)["answers"]
    for question in package["questions"]:
        if question["kind"] == "rank":
            answer[question["question_name"]] = [
                question["question_options"].index(x)
                for x in answer[question["question_name"]]
            ]
    for question in survey.questions:
        question._validate_answer({"answer": answer[question.question_name]})
    results = results_object(survey, agents[0], edsl.Scenario({}), answer)
    results.save(str(tmp_path / "human-results.ep"))
    rows = field_results(tmp_path / "human-results.ep", packages)
    ingest_field(state, "human", rows)
    assert len(state["preferences"]["s001"]["ranking"]) == 4


def test_score_jobs_and_results(tmp_path, state):
    build_plan(state, "plan", tmp_path / "plan", "test", k=1, native=True)
    plan = state["score_plans"]["plan"]
    jobs = load_object("Jobs", tmp_path / "plan/edsl/jobs.ep")
    assert len(jobs.scenarios) == len(plan["tasks"])
    answer = {k: v for k, v in fake_scores(plan)[0].items() if k != "task_id"}
    results = results_object(
        jobs.survey, edsl.Agent(), jobs.scenarios[0], {"evaluation": answer}
    )
    results.save(str(tmp_path / "scores.ep"))
    rows = score_results(tmp_path / "scores.ep", plan)
    status = ingest_scores(state, "plan", rows, source="synthetic")
    assert status["completed"] == 1
    assert status["missing"]


def test_benchmark_native_roundtrip(tmp_path, state):
    build_plan(state, "plan", tmp_path / "plan", "test", k=5, native=False)
    ingest_scores(
        state, "plan", fake_scores(state["score_plans"]["plan"]), source="synthetic"
    )
    build_benchmark(state, "check", tmp_path / "check", "plan", pairs=2, native=True)
    packages = state["fields"]["check"]["packages"]
    package = next(p for p in packages.values() if p["split"] == "evaluation")
    folder = tmp_path / "check" / package["id"]
    jobs = load_object("Jobs", folder / "jobs.ep")
    answers = {
        q["question_name"]: q.get("question_options", ["Example reason"])[0]
        for q in package["questions"]
    }
    results = results_object(jobs.survey, jobs.agents[0], edsl.Scenario({}), answers)
    results.save(str(tmp_path / "benchmark-results.ep"))
    report = import_field_answers(
        state,
        "check",
        field_results(tmp_path / "benchmark-results.ep", packages),
        source="synthetic",
    )
    assert (
        report["participants"][package["participant_id"]]["overall"]["denominator"] == 1
    )
