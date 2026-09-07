import copy

import pytest

from roth.common import RothError
from roth.fielding import build_field, ingest_field, OUTSIDE, UNKNOWN, ACCEPT, REJECT


def submission(package, unknown=None):
    answers = {}
    for q in package["questions"]:
        if q["kind"] == "rank":
            answers[q["question_name"]] = list(q["question_options"])
        elif q["question_name"].startswith("known_"):
            answers[q["question_name"]] = (
                UNKNOWN if q["mapping"]["candidate"] == unknown else "Assessed"
            )
        elif q["question_name"].startswith("accept_"):
            answers[q["question_name"]] = ACCEPT
        else:
            answers[q["question_name"]] = q.get("question_options", ["Instructions"])[0]
    return {
        "package_id": package["id"],
        "participant_id": package["participant_id"],
        "submission_id": "first",
        "answers": answers,
    }


def test_rank_outside_unknown_identity_and_replay(tmp_path, state):
    build_field(state, "human", tmp_path / "survey", native=False, only=["s001"])
    package = next(iter(state["fields"]["human"]["packages"].values()))
    row = submission(package, "i001")
    rank = row["answers"]["ranking"]
    rank.insert(1, rank.pop(rank.index(OUTSIDE)))
    bad = {**row, "participant_id": "s002"}
    with pytest.raises(RothError, match="Wrong respondent"):
        ingest_field(state, "human", [bad])
    ingest_field(state, "human", [row])
    pref = state["preferences"]["s001"]
    assert "i001" not in pref["ranking"] + pref["unacceptable"]
    assert "i001" in pref["evaluated"]
    assert pref["unacceptable"]
    assert ingest_field(state, "human", [row])["imported"] == 0
    changed = copy.deepcopy(row)
    changed["answers"]["ranking"].reverse()
    with pytest.raises(RothError, match="conflicting content"):
        ingest_field(state, "human", [changed])


def test_screen_batches_then_cross_batch_rank(tmp_path, state):
    build_field(
        state,
        "screen",
        tmp_path / "screen",
        kind="screening",
        batch_size=2,
        native=False,
        only=["s001"],
    )
    assert len(state["fields"]["screen"]["packages"]) == 2
    rows = [submission(p) for p in state["fields"]["screen"]["packages"].values()]
    rows[0]["answers"]["accept_0"] = REJECT
    ingest_field(state, "screen", rows)
    assert not state["preferences"]
    build_field(state, "rank", tmp_path / "rank", native=False, only=["s001"])
    p = next(iter(state["fields"]["rank"]["packages"].values()))
    assert len(p["candidates"]) == 3
    ingest_field(state, "rank", [submission(p)])
    assert len(state["preferences"]["s001"]["ranking"]) == 3
    assert len(state["preferences"]["s001"]["unacceptable"]) == 1


def test_budget_and_partial_response(tmp_path, state):
    with pytest.raises(RothError, match="over budget"):
        build_field(state, "large", tmp_path / "large", max_options=1, native=False)
    assert not (tmp_path / "large").exists()
    build_field(state, "human", tmp_path / "human", native=False, only=["s001"])
    p = next(iter(state["fields"]["human"]["packages"].values()))
    row = submission(p)
    row["answers"].pop("ranking")
    with pytest.raises(RothError, match="Missing answer"):
        ingest_field(state, "human", [row])
    assert not state["preferences"]


def test_static_preview_escapes_html(tmp_path, state):
    state["market"]["participants"][0]["name"] = '<script>alert("x")</script>'
    build_field(state, "safe", tmp_path / "safe", native=False, only=["s001"])
    content = (tmp_path / "safe/preview.html").read_text()
    assert "<script>" not in content
    assert "&lt;script&gt;" in content


def test_instruction_responses_can_arrive_incrementally(tmp_path, state):
    build_field(
        state,
        "instructions",
        tmp_path / "instructions",
        kind="instructions",
        native=False,
        only=["s001", "s002"],
    )
    packages = list(state["fields"]["instructions"]["packages"].values())
    for index, p in enumerate(packages):
        row = submission(p)
        row["answers"]["preferences"] = f"Updated instructions for participant {index}"
        ingest_field(state, "instructions", [row])
    assert len(state["fields"]["instructions"]["responses"]) == 2


def test_latest_screening_revision_wins_across_rounds(tmp_path, state):
    for name in ("z_first", "a_second"):
        build_field(
            state, name, tmp_path / name, kind="screening", native=False, only=["s001"]
        )
        package = next(iter(state["fields"][name]["packages"].values()))
        row = submission(package)
        if name == "a_second":
            row["answers"]["accept_0"] = REJECT
        ingest_field(state, name, [row])
    from roth.fielding import screen_decisions

    assert screen_decisions(state, "s001")["i001"] == REJECT
