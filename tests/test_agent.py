"""Exercise intake and execute actual suggested workflows end to end."""

import json
from pathlib import Path

import pytest

from roth.agent import next_guidance
from roth.cli import create_example, main, parser
from roth.common import RothError, write_json
from roth.example import internship_example
from roth.storage import Store
from roth.team_example import classroom_example
from roth.workflow import ingest_preferences


def call(capsys, argv):
    code = main(list(map(str, argv)))
    data = json.loads(capsys.readouterr().out)
    return code, data


def assert_commands(data):
    for command in data.get("actions", []) + data.get("examples", []):
        if command["argv"][0] == "roth":
            parser().parse_args(command["argv"][1:])
        assert all(
            isinstance(command[key], bool)
            for key in ("mutates", "network", "requires_authorization")
        )
    if "rerun" in data:
        parser().parse_args(data["rerun"][1:])


def team_files(root):
    market, rows = classroom_example()
    write_json(root / "market.json", market)
    write_json(root / "preferences.json", rows)
    return market, rows


def test_fresh_intake_does_not_create_files(tmp_path, capsys):
    root = tmp_path / "not-created"
    code, envelope = call(capsys, ["--project", root, "agent", "next"])
    assert code == 0 and envelope["data"]["phase"] == "identify_scenario"
    assert not root.exists() and not envelope["next_steps"]
    assert len(envelope["data"]["questions"]) == 2
    assert_commands(envelope["data"])
    code, envelope = call(capsys, ["--project", root, "next"])
    assert code == 0 and envelope["data"]["phase"] == "identify_scenario"


@pytest.mark.parametrize("scenario", ["teams", "one-to-one", "many-to-one"])
def test_scenario_specific_intake(tmp_path, scenario):
    data = next_guidance(tmp_path, scenario=scenario)
    assert data["phase"] == "define_market"
    assert data["questions"] and not data["actions"]
    assert_commands(data)


@pytest.mark.parametrize("scenario", ["roommates", "other"])
def test_unsupported_scenarios_never_reinterpreted(tmp_path, scenario):
    data = next_guidance(tmp_path, scenario=scenario)
    assert data["phase"] == "unsupported_scenario" and not data["supported"]
    assert not data["actions"]


def test_capacity_detection_and_scenario_conflict(tmp_path):
    market, rows = internship_example(3, 2)
    market["participants"][-1]["capacity"] = 2
    write_json(tmp_path / "market.json", market)
    assert next_guidance(tmp_path)["scenario"] == "many-to-one"
    assert (
        next_guidance(tmp_path, scenario="one-to-one")["phase"]
        == "resolve_scenario_conflict"
    )


def test_raw_one_to_one_files_drive_initialize_to_review(tmp_path, capsys):
    root = tmp_path / "market with spaces"
    market, rows = internship_example(5, 4)
    write_json(root / "market.json", market)
    write_json(root / "preferences.json", rows)
    phases = []
    for _ in range(8):
        data = next_guidance(root)
        phases.append(data["phase"])
        assert_commands(data)
        if data["complete"]:
            assert Path(data["report"]).is_file()
            break
        assert len(data["actions"]) == 1
        action = data["actions"][0]
        assert not action["network"] and not action["requires_authorization"]
        code, output = call(capsys, action["argv"][1:])
        assert code == 0, output
    assert phases == [
        "initialize",
        "import_preferences",
        "freeze_preferences",
        "match",
        "export_report",
        "review_results",
    ]
    before = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in (root / ".roth").rglob("*")
        if p.is_file()
    }
    assert next_guidance(root)["complete"]
    after = {
        p: (p.stat().st_mtime_ns, p.read_bytes())
        for p in (root / ".roth").rglob("*")
        if p.is_file()
    }
    assert before == after


def test_collection_choice_and_human_route_override_delegation_permission(
    tmp_path, capsys
):
    market, _ = internship_example(5, 4)
    write_json(tmp_path / "market.json", market)
    assert (
        call(capsys, ["--project", tmp_path, "init", tmp_path / "market.json"])[0] == 0
    )
    assert next_guidance(tmp_path)["phase"] == "choose_collection"
    assert (
        next_guidance(tmp_path, collection="rankings")["phase"] == "collect_preferences"
    )
    data = next_guidance(tmp_path, collection="human")
    assert data["phase"] == "build_human_surveys"
    command = data["actions"][0]
    assert command["argv"][command["argv"].index("--kind") + 1] == "ranking"
    assert command["mutates"] and not command["network"]
    assert_commands(data)
    assert next_guidance(tmp_path, collection="delegated")["phase"] == "plan_delegation"


def test_large_human_market_routes_to_screening(tmp_path, capsys):
    market, _ = internship_example(18, 16)
    write_json(tmp_path / "market.json", market)
    assert (
        call(capsys, ["--project", tmp_path, "init", tmp_path / "market.json"])[0] == 0
    )
    data = next_guidance(tmp_path, collection="human")
    argv = data["actions"][0]["argv"]
    assert argv[argv.index("--kind") + 1] == "screening"


def test_explicit_collection_does_not_import_default_synthetic_fixtures(tmp_path):
    root = tmp_path / "example"
    create_example(root, 5, 4)
    assert next_guidance(root, collection="human")["phase"] == "build_human_surveys"
    assert next_guidance(root, collection="delegated")["phase"] == "plan_delegation"
    assert next_guidance(root)["phase"] == "import_preferences"


def test_direct_policy_requires_organizer_delegation_decision(tmp_path, capsys):
    market, _ = internship_example(3, 2)
    market["config"]["delegation"] = "direct"
    write_json(tmp_path / "market.json", market)
    assert (
        call(capsys, ["--project", tmp_path, "init", tmp_path / "market.json"])[0] == 0
    )
    data = next_guidance(tmp_path, collection="delegated")
    assert data["phase"] == "configure_delegation"
    assert data["actions"][0]["argv"][-1] == "--help"
    assert not data["actions"][0]["mutates"]


def test_confirmation_and_coverage_block_freeze(tmp_path):
    root = tmp_path / "confirm"
    create_example(root, 3, 2)
    store = Store(root)
    with store.lock():
        state = store.load()
        state["market"]["config"]["delegation"] = "confirm"
        rows = state["example_preferences"]
        for row in rows:
            row["source"] = "delegated"
        ingest_preferences(state, rows)
        store.commit(state, "test.confirm")
    data = next_guidance(root)
    assert data["phase"] == "confirm_preferences"
    assert (
        data["actions"][0]["argv"][data["actions"][0]["argv"].index("--kind") + 1]
        == "confirmation"
    )
    assert (
        "--market" not in data["rerun"]
    )  # stale example fixture must not shadow policy revisions
    with store.lock():
        state = store.load()
        for row in state["preferences"].values():
            row["confirmed"] = True
        state["market"]["config"]["unknown_policy"] = "require_complete"
        state["preferences"]["s001"]["ranking"].pop()
        store.commit(state, "test.coverage")
    data = next_guidance(root)
    assert data["phase"] == "resolve_before_freeze"
    assert "Unevaluated" in data["issues"][0]
    assert not data["actions"]


def test_explicit_preference_revision_detected_after_completion(tmp_path):
    root = tmp_path / "done"
    create_example(root, run=True)
    rows = json.loads((root / "preferences.json").read_text())
    rows[0]["ranking"].reverse()
    alternate = tmp_path / "new-rankings.json"
    write_json(alternate, rows)
    assert next_guidance(root)["complete"]
    data = next_guidance(root, preferences_path=alternate)
    assert data["phase"] == "review_preference_import" and not data["complete"]
    assert not data["actions"]
    assert next_guidance(root, preferences_path=root / "preferences.json")["complete"]


def test_corrupt_history_is_not_replaced_with_fresh_intake(tmp_path):
    root = tmp_path / "bad"
    create_example(root)
    event = next((root / ".roth/events").glob("*.json"))
    data = json.loads(event.read_text())
    data["hash"] = "corrupted"
    event.write_text(json.dumps(data))
    with pytest.raises(RothError) as error:
        next_guidance(root)
    assert error.value.code == "INTEGRITY_ERROR"


def test_team_collection_and_validation_guidance(tmp_path):
    market, rows = classroom_example()
    write_json(tmp_path / "market.json", market)
    data = next_guidance(tmp_path)
    assert data["scenario"] == "teams" and data["phase"] == "collect_preferences"
    assert "--collection human" in data["collection"]
    assert (
        next_guidance(tmp_path, collection="delegated")["phase"]
        == "unsupported_collection"
    )
    write_json(tmp_path / "preferences.json", rows[:-1])
    assert next_guidance(tmp_path)["phase"] == "repair_preferences"


def test_optional_solver_guidance_marks_installation_correctly(tmp_path, monkeypatch):
    team_files(tmp_path)
    monkeypatch.setattr("roth.agent.importlib.util.find_spec", lambda name: None)
    data = next_guidance(tmp_path)
    assert data["phase"] == "install_solver"
    command = data["actions"][0]
    assert (
        command["mutates"] and command["network"] and command["requires_authorization"]
    )


def test_team_workflow_and_changed_input_rerun(tmp_path, capsys):
    pytest.importorskip("scipy")
    root = tmp_path / "classroom"
    market, rows = team_files(root)
    data = next_guidance(root)
    assert data["phase"] == "solve"
    assert_commands(data)
    assert call(capsys, data["actions"][0]["argv"][1:])[0] == 0
    code, response = call(capsys, data["rerun"][1:])
    assert code == 0 and response["data"]["phase"] == "review_results"
    assert response["data"]["complete"] and not response["next_steps"]
    market["config"]["social_weight"] = 0.25
    (root / "market.json").write_text(json.dumps(market))
    data = next_guidance(root)
    assert data["phase"] == "solve"
    assert data["next_output"] == str(root / "report-2")
    assert data["rerun"][data["rerun"].index("--output") + 1] == str(root / "report-2")
    assert call(capsys, data["actions"][0]["argv"][1:])[0] == 0
    code, response = call(capsys, data["rerun"][1:])
    assert code == 0 and response["data"]["complete"]
    saved = root / "report-2/result.json"
    result = json.loads(saved.read_text())
    result["solution_status"] = "feasible_limit"
    saved.write_text(json.dumps(result))
    data = next_guidance(root, output=root / "report-2")
    assert (
        data["phase"] == "review_results" and data["questions"] and not data["complete"]
    )
    result["total_score"] += 5
    saved.write_text(json.dumps(result))
    assert next_guidance(root, output=root / "report-2")["phase"] == "inspect_result"
