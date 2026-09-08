"""Human collection semantics, durable identity/revisions, and native round trips."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from roth.agent import next_guidance
from roth.cli import main, parser
from roth.collection import (
    RANK,
    NEUTRAL,
    EXCLUDE,
    assessment,
    build_collection,
    build_rankings,
    collection_status,
    export_preferences,
    import_responses,
    load_collection,
    register_collection,
)
from roth.common import RothError, read_json, write_json
from roth.review_example import review_example
from roth.team_example import classroom_example


def answers(col, fixture, stage="assessment", sid="first"):
    rows = {r.get("student_id", r.get("reviewer_id")): r for r in fixture}
    responses = []
    context = assessment(col)[2]
    for key, p in col["packages"].items():
        if p["stage"] != stage or (
            stage == "ranking" and p["assessment_hash"] != context
        ):
            continue
        row = rows[p["participant_id"]]
        domain = p["domain"]
        result = {}
        if stage == "ranking":
            q = p["questions"][0]
            order = row[domain if col["mode"] == "teams" else "ranking"]
            result["ranking"] = sorted(
                q["question_options"],
                key=lambda label: order.index(q["mapping"][label]),
            )
        else:
            rank = row.get(domain if col["mode"] == "teams" else "ranking", [])
            excluded = row.get(
                "unacceptable_projects"
                if domain == "projects"
                else "incompatible_teammates"
                if domain == "teammates"
                else "unacceptable",
                [],
            )
            for q in p["questions"]:
                candidate = q.get("mapping", {}).get("candidate")
                result[q["question_name"]] = (
                    q["question_options"][0]
                    if candidate is None
                    else EXCLUDE
                    if candidate in excluded
                    else str(int(row["scores"][candidate]))
                    if candidate in row.get("scores", {})
                    else RANK
                    if candidate in rank
                    else NEUTRAL
                )
        responses.append(
            {
                "package_id": key,
                "participant_id": p["participant_id"],
                "submission_id": sid,
                "answers": result,
            }
        )
    return responses


@pytest.mark.parametrize("mode", ["teams", "reviews", "scores"])
def test_complete_batched_collection_exports_solver_inputs(tmp_path, mode):
    market, fixture = classroom_example() if mode == "teams" else review_example()
    if mode == "scores":
        market["config"]["scoring"] = "scores"
        for row in fixture:
            row["scores"] = {
                p: 100 - 10 * i for i, p in enumerate(row.pop("ranking")[:7])
            }
    actual_mode = "reviews" if mode == "scores" else mode
    # Nonalphabetical roster order must survive stored-state canonicalization.
    market["students" if mode == "teams" else "reviewers"].reverse()
    root = tmp_path / "collection"
    status = build_collection(actual_mode, market, root, batch_size=2, native=False)
    assert not status["complete"] and status["completed_participants"] == 0
    _, _, col = load_collection(root)
    rows = answers(col, fixture)
    first = import_responses(root, rows[:2], source="synthetic")
    assert not first["complete"]
    with pytest.raises(RothError, match="incomplete"):
        export_preferences(root, tmp_path / "early.json")
    status = import_responses(root, rows[2:], source="synthetic")
    if mode != "scores":
        status = build_rankings(root)
        assert status["ranking_needed"]
        _, _, col = load_collection(root)
        status = import_responses(
            root, answers(col, fixture, "ranking"), source="synthetic"
        )
    assert status["complete"]
    out = tmp_path / "preferences.json"
    exported = export_preferences(root, out)
    result = read_json(out)
    assert {r.get("student_id", r.get("reviewer_id")) for r in result} == {
        r.get("student_id", r.get("reviewer_id")) for r in fixture
    }
    assert exported["preferences_hash"] == collection_status(root)["preferences_hash"]
    assert all(r["source"] == "synthetic" for r in result)
    assert read_json(exported["provenance"])["decisions"]
    expected = {r.get("student_id", r.get("reviewer_id")): r for r in fixture}
    for row in result:
        original = expected[row.get("student_id", row.get("reviewer_id"))]
        for key in (
            "projects",
            "teammates",
            "ranking",
            "scores",
            "unacceptable_projects",
            "incompatible_teammates",
            "unacceptable",
        ):
            if key in original:
                assert (
                    row[key] == original[key]
                    or key.startswith(("unacceptable", "incompatible"))
                    and set(row[key]) == set(original[key])
                )
    pytest.importorskip("scipy.optimize")
    if mode == "teams":
        from roth.teams import solve_teams

        assert solve_teams(market, result)["solution_status"] == "optimal"
    else:
        from roth.reviews import solve_reviews

        assert solve_reviews(market, result)["statistics"]["assignments"] == 36
    with pytest.raises(RothError, match="exists"):
        export_preferences(root, out)


def test_atomic_identity_replay_and_stale_rankings(tmp_path):
    m, p = classroom_example()
    root = tmp_path / "col"
    build_collection("teams", m, root, native=False)
    _, _, col = load_collection(root)
    rows = answers(col, p)
    bad = deepcopy(rows)
    bad[-1]["participant_id"] = "wrong"
    with pytest.raises(RothError, match="respondent"):
        import_responses(root, bad, source="synthetic")
    assert not load_collection(root)[2]["responses"]
    import_responses(root, rows, source="synthetic")
    assert import_responses(root, rows, source="synthetic")["imported"] == 0
    build_rankings(root)
    _, _, col = load_collection(root)
    ranking = answers(col, p, "ranking")
    import_responses(root, ranking, source="synthetic")
    assert collection_status(root)["complete"]
    revised = deepcopy(rows[0])
    revised["submission_id"] = "revision"
    key = next(iter(revised["answers"]))
    revised["answers"][key] = NEUTRAL
    with pytest.raises(RothError, match="--replace"):
        import_responses(root, [revised], source="synthetic")
    import_responses(root, [revised], replace=True, source="synthetic")
    assert not collection_status(root)["complete"]
    # Old submission replays do not overwrite the current revision.
    import_responses(root, [rows[0]], source="synthetic")
    assert (
        load_collection(root)[2]["responses"][revised["package_id"]]["submission_id"]
        == "revision"
    )
    stale = deepcopy(ranking[0])
    stale["submission_id"] = "late"
    with pytest.raises(RothError, match="stale"):
        import_responses(root, [stale], replace=True, source="synthetic")
    changed = deepcopy(revised)
    changed["answers"][key] = EXCLUDE
    with pytest.raises(RothError, match="conflicting content"):
        import_responses(root, [changed], replace=True, source="synthetic")
    build_rankings(root)
    assert len(load_collection(root)[2]["rounds"]) == 3


def test_budget_no_truncation_missing_answers_and_human_source(tmp_path):
    m, p = review_example()
    root = tmp_path / "col"
    build_collection("reviews", m, root, max_options=2, native=False)
    _, _, col = load_collection(root)
    rows = answers(col, p)
    missing = deepcopy(rows[0])
    missing["answers"].pop(next(iter(missing["answers"])))
    with pytest.raises(RothError, match="answer"):
        import_responses(root, [missing])
    import_responses(root, rows)  # importing organizer-declared human responses
    with pytest.raises(RothError, match="budget"):
        build_rankings(root)
    build_rankings(root, max_options=20)
    revision = deepcopy(rows[0])
    revision["submission_id"] = "new"
    with pytest.raises(RothError, match="human response"):
        import_responses(root, [revision], replace=True, source="synthetic")
    m.pop("synthetic")
    real = tmp_path / "real"
    build_collection("reviews", m, real, native=False)
    with pytest.raises(RothError, match="synthetic market"):
        import_responses(real, [], source="synthetic")


def test_singletons_neutral_and_empty_sections(tmp_path):
    m = {
        "students": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "projects": [{"id": "p", "name": "P"}],
        "synthetic": True,
        "config": {"target_size": 2},
    }
    fixture = [
        {
            "student_id": i,
            "projects": ["p"],
            "teammates": [],
            "unacceptable_projects": [],
            "incompatible_teammates": [],
        }
        for i in "ab"
    ]
    build_collection("teams", m, tmp_path / "col", native=False)
    _, _, col = load_collection(tmp_path / "col")
    assert import_responses(
        tmp_path / "col", answers(col, fixture), source="synthetic"
    )["complete"]
    export_preferences(tmp_path / "col", tmp_path / "p.json")
    assert all(
        r["teammates"] == [] and r["incompatible_teammates"] == []
        for r in read_json(tmp_path / "p.json")
    )


def test_agent_collection_bypasses_synthetic_files_and_resumes(tmp_path, capsys):
    pytest.importorskip("edsl")
    m, p = review_example()
    root = tmp_path / "study"
    write_json(root / "market.json", m)
    write_json(root / "preferences.json", p)
    g = next_guidance(root, collection="human")
    assert g["phase"] == "build_surveys"
    command = g["actions"][0]["argv"][1:] + ["--json-only"]
    assert main(command) == 0
    capsys.readouterr()
    g = next_guidance(root, collection="human")
    assert g["phase"] == "collect_assessments"
    field = root / "field"
    _, _, col = load_collection(field)
    import_responses(field, answers(col, p), source="synthetic")
    g = next_guidance(root, collection="human")
    assert g["phase"] == "build_rankings"
    assert main(g["actions"][0]["argv"][1:]) == 0
    capsys.readouterr()
    _, _, col = load_collection(field)
    import_responses(field, answers(col, p, "ranking"), source="synthetic")
    g = next_guidance(root, collection="human")
    assert g["phase"] == "export_preferences" and g["next_preferences"].endswith(
        "preferences-2.json"
    )
    assert main(g["actions"][0]["argv"][1:]) == 0
    capsys.readouterr()
    g = next_guidance(root, collection="human")
    assert g["phase"] == "solve"
    assert str(root / "preferences-2.json") in g["actions"][0]["argv"]
    assert read_json(root / "preferences.json") == p
    for command in g["actions"]:
        parser().parse_args(command["argv"][1:])
    before = {p: p.read_bytes() for p in (field / ".roth").rglob("*") if p.is_file()}
    next_guidance(root, collection="human")
    assert before == {p: p.read_bytes() for p in before}
    m["config"]["max_reviews"] = 4
    (root / "market.json").write_text(json.dumps(m))
    assert (
        next_guidance(root, collection="human")["phase"]
        == "resolve_collection_revision"
    )


def test_native_roundtrip_contacts_and_registration(tmp_path):
    edsl = pytest.importorskip("edsl")
    from roth.edsl_bridge import load_object, field_results
    from test_edsl_bridge import results_object

    m = {
        "students": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "projects": [{"id": "p", "name": "P"}],
        "synthetic": True,
        "config": {"target_size": 2},
    }
    fixture = [
        {
            "student_id": i,
            "projects": ["p"],
            "teammates": [],
            "unacceptable_projects": [],
            "incompatible_teammates": [],
        }
        for i in "ab"
    ]
    root = tmp_path / "native"
    build_collection("teams", m, root, contacts={"a": {"email": "a@example.invalid"}})
    _, _, col = load_collection(root)
    responses = answers(col, fixture)
    package = col["packages"][responses[0]["package_id"]]
    folder = Path(package["folder"])
    jobs = load_object("Jobs", folder / "jobs.ep")
    assert (
        len(jobs.models) == 0 and jobs.agents[0].traits["email"] == "a@example.invalid"
    )
    assert "a@example.invalid" not in (root / "assessment/preview.html").read_text()
    for q in jobs.survey.questions:
        q._validate_answer({"answer": responses[0]["answers"][q.question_name]})
    results = results_object(
        jobs.survey, jobs.agents[0], edsl.Scenario({}), responses[0]["answers"]
    )
    results.save(str(tmp_path / "responses.ep"))
    native = field_results(tmp_path / "responses.ep", col["packages"])
    import_responses(root, native, source="synthetic")
    reg = register_collection(
        root, package["id"], "12345678-1234-1234-1234-123456789012"
    )
    assert reg["external_actions"]["invite"][0] == "ep"
    with pytest.raises(RothError, match="different survey"):
        register_collection(root, package["id"], "22345678-1234-1234-1234-123456789012")
    handoffs = read_json(root / "assessment/handoff.json")
    for handoff in handoffs:
        argv = handoff["register"]
        argv[argv.index("--uuid") + 1] = "12345678-1234-1234-1234-123456789012"
        parser().parse_args(argv[1:])
        assert handoff["native_built"]
