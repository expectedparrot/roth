import copy
import json

import pytest

from roth.common import RothError
from roth.market import validate_market, validate_preferences
from roth.storage import Store
from roth.workflow import ingest_preferences, freeze, run_matching


def test_nonresponse_unknown_and_reduced_cohort(state):
    rows = state["example_preferences"][:-1]
    ingest_preferences(state, rows)
    with pytest.raises(RothError, match="Missing completed"):
        freeze(state, "bad")
    excluded = state["example_preferences"][-1]["participant_id"]
    snapshot = freeze(state, "small", [excluded])
    assert snapshot["cohort_scope"] == "reduced"
    run_matching(state, "small", "run")
    assert excluded not in {p for e in state["runs"]["run"]["matches"] for p in e}


def test_unknown_not_rejected_and_frozen_revisions(state):
    rows = copy.deepcopy(state["example_preferences"])
    rows[0]["ranking"] = rows[0]["ranking"][:1]
    ingest_preferences(state, rows)
    original = freeze(state, "one")
    assert original["coverage"] == "restricted"
    assert original["unknown"][rows[0]["participant_id"]]
    saved = copy.deepcopy(original)
    ingest_preferences(state, state["example_preferences"], replace=True)
    assert state["snapshots"]["one"] == saved
    assert freeze(state, "two")["hash"] != saved["hash"]


def test_confirmation_and_human_override(state):
    state["market"]["config"]["delegation"] = "confirm"
    rows = copy.deepcopy(state["example_preferences"])
    for r in rows:
        r["source"] = "delegated"
    ingest_preferences(state, rows)
    with pytest.raises(RothError, match="confirmation"):
        freeze(state, "bad")
    for r in rows:
        r["source"] = "human"
        r["confirmed"] = True
    ingest_preferences(state, rows, replace=True)
    freeze(state, "good")
    row = {**rows[0], "source": "delegated"}
    with pytest.raises(RothError, match="Cannot replace human"):
        ingest_preferences(state, [row], replace=True)


def test_complete_policy_and_invalid_preferences(state):
    state["market"]["config"]["unknown_policy"] = "require_complete"
    rows = copy.deepcopy(state["example_preferences"])
    rows[0]["ranking"] = []
    ingest_preferences(state, rows)
    with pytest.raises(RothError, match="Unevaluated"):
        freeze(state, "bad")
    for bad in (
        {"ranking": ["unknown"]},
        {"ranking": ["i001", "i001"]},
        {"complete": False},
    ):
        with pytest.raises(RothError):
            validate_preferences(state["market"], [{**rows[0], **bad}])


def test_one_slot_and_contact_separation(state):
    bad = copy.deepcopy(state["market"])
    bad["participants"][0]["capacity"] = 2
    with pytest.raises(RothError, match="one-to-one"):
        validate_market(bad)
    bad = copy.deepcopy(state["market"])
    bad["participants"][0]["profile"]["email"] = "private@example.invalid"
    with pytest.raises(RothError, match="outside public profile"):
        validate_market(bad)


def test_history_detects_tampering(tmp_path, state):
    store = Store(tmp_path)
    with store.lock(create=True):
        store.load()
        store.commit(state, "init")
        loaded = store.load()
        assert loaded == state
        ingest_preferences(loaded, state["example_preferences"])
        store.commit(loaded, "import")
    files = sorted((store.root / "events").glob("*.json"))
    event = json.loads(files[0].read_text())
    event["action"] = "changed"
    files[0].write_text(json.dumps(event))
    with pytest.raises(RothError, match="Corrupt event"):
        store.load()
