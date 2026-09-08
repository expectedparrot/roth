"""Read-only intake and state-aware guidance for the agent using Roth.

The calling agent interprets the user's situation and answers the intake using
explicit scenario flags and input files. No LLM calls or keyword classification
are performed here. Suggested commands are separate from explanations/questions.
"""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

from .common import RothError, digest, read_json


SCENARIOS = [
    {
        "id": "reviews",
        "supported": True,
        "when": "Assign several submissions to each reviewer and several reviewers to each submission, with authorship/conflicts and workload rules.",
        "examples": ["classroom peer review", "internal proposal review"],
        "method": "Binary assignment optimization with exact review coverage and bounded workloads; Borda rankings or explicit scores.",
    },
    {
        "id": "one-to-one",
        "supported": True,
        "when": "Two distinct sides rank each other; each participant receives at most one partner.",
        "examples": [
            "students and individual internship openings",
            "mentees and mentors with one mentee each",
        ],
        "method": "Deferred acceptance; stability relative to the frozen preferences and candidate graph.",
    },
    {
        "id": "teams",
        "supported": True,
        "when": "Form teams from one student roster and assign each team a distinct project; students rank projects and teammates.",
        "examples": [
            "classroom project teams",
            "joint team formation and project assignment",
        ],
        "method": "Joint Borda MILP: minimize target-size deviation, then maximize weighted preference scores.",
    },
    {
        "id": "many-to-one",
        "supported": True,
        "when": "One side accepts multiple partners under fixed capacities, while the other side receives at most one.",
        "examples": ["employees and mentors", "students and faculty advisers"],
        "method": "Deferred acceptance with responsive individual rankings and capacities; either side may propose.",
    },
    {
        "id": "roommates",
        "supported": False,
        "when": "Pairs are formed within a single pool, with no distinct second side.",
    },
    {
        "id": "other",
        "supported": False,
        "when": "For example: teams without projects, repeated projects, or arbitrary coalition formation.",
    },
]


def action(argv, purpose, *, mutates=False, network=False):
    return {
        "argv": [str(a) for a in argv],
        "purpose": purpose,
        "mutates": mutates,
        "network": network,
        "requires_authorization": network,
    }


def question(key, text, choices=None):
    item = {"id": key, "question": text}
    if choices:
        item["choices"] = choices
    return item


def fresh_path(path):
    path = Path(path)
    candidate, count = path, 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}-{count}")
        count += 1
    return candidate


def _response(scenario, phase, instruction, *, questions=(), actions=(), **details):
    if phase == "review_results" and details.get("report"):
        details["what_if"] = {
            "instruction": "If the organizer wants policy comparisons, record named changes in a scenarios JSON array, then use roth compare against this saved report. Keep the baseline and preferences fixed. Explain assignment churn, individual gains/losses on the baseline score scale, workload changes, and infeasible scenarios. Do not adopt a scenario automatically.",
            "baseline": str(Path(details["report"]).parent),
            "command_template": "roth compare BASELINE_REPORT --scenarios SCENARIOS.json --output NEW_COMPARISON_REPORT",
            "documentation": "docs/comparisons.md",
        }
    return {
        "scenario": scenario,
        "phase": phase,
        "complete": False,
        "instruction": instruction,
        "questions": list(questions),
        "actions": list(actions),
        **details,
    }


def _shape(market):
    if not isinstance(market, dict):
        return None
    if market.get("mode") == "reviews" or (
        "reviewers" in market and "submissions" in market
    ):
        return "reviews"
    if "students" in market and "projects" in market:
        return "teams"
    if "participants" in market:
        people = market["participants"]
        if isinstance(people, list) and any(
            isinstance(p, dict) and p.get("capacity", 1) != 1 for p in people
        ):
            return "many-to-one"
        return "one-to-one"
    return None


def next_guidance(
    project=".",
    scenario="auto",
    market_path=None,
    preferences_path=None,
    output=None,
    collection=None,
    field_dir=None,
    contacts_path=None,
):
    root = Path(project).resolve()
    explicit_market = market_path is not None
    explicit_preferences = preferences_path is not None
    market_path = Path(market_path).resolve() if market_path else root / "market.json"
    preferences_path = (
        Path(preferences_path).resolve()
        if preferences_path
        else root / "preferences.json"
    )
    output = Path(output).resolve() if output else root / "report"
    field_dir = Path(field_dir).resolve() if field_dir else root / "field"
    contacts_path = Path(contacts_path).resolve() if contacts_path else None
    market = read_json(market_path) if market_path.is_file() else None
    state = None
    if (root / ".roth").is_dir():
        from .storage import Store

        state = Store(
            root
        ).load()  # append-only immutable snapshots permit a read-only load
    detected = _shape(market) if market is not None else None
    if not explicit_market and state and state["market"]:
        detected = _shape(state["market"])
    if scenario == "auto":
        scenario = detected
    elif detected and scenario != detected:
        return _response(
            scenario,
            "resolve_scenario_conflict",
            "The requested scenario conflicts with the supplied market or initialized project. Select the intended project/input files before proceeding.",
            detected_scenario=detected,
            requested_scenario=scenario,
        )
    if scenario is None:
        return _response(
            None,
            "identify_scenario",
            "Use the user's description and existing conversation to identify the structure. Ask only what is missing; do not infer the method from labels such as students or internships. Then rerun agent next with --scenario.",
            questions=[
                question(
                    "structure",
                    "Are we matching two distinct sides, forming teams and assigning projects, assigning reviewers to submissions, or handling another structure?",
                    [s["id"] for s in SCENARIOS],
                ),
                question(
                    "preferences",
                    "Who ranks whom, and do we already have rankings, need human responses, or want organizer-authorized model delegation?",
                ),
            ],
            scenario_rules=SCENARIOS,
            examples=[
                action(
                    ["roth", "--project", root, "agent", "next", "--scenario", s],
                    "Continue after identifying the scenario",
                )
                for s in ("one-to-one", "many-to-one", "teams", "reviews")
            ],
        )
    if scenario not in {"one-to-one", "many-to-one", "teams", "reviews"}:
        return _response(
            scenario,
            "unsupported_scenario",
            "Explain the scope limit and help the organizer select another formulation or tool. Do not silently split capacities, invent projects, or relabel one pool as two sides to claim the unsupported mechanism.",
            supported=False,
            scenario_rules=SCENARIOS,
        )
    data = None
    collecting = (
        scenario in {"teams", "reviews"}
        and market is not None
        and (
            collection == "human"
            or (
                (field_dir / ".roth").is_dir()
                and collection not in {"rankings", "delegated"}
            )
        )
    )
    if collecting:
        from .agent_collection import collection_guidance

        data, preferences_path = collection_guidance(
            scenario, market, market_path, preferences_path, field_dir, contacts_path
        )
    if data is not None:
        pass
    elif scenario == "reviews":
        from .agent_reviews import review_guidance

        data = review_guidance(
            market, market_path, preferences_path, output, collection
        )
    elif scenario == "teams":
        data = _teams(market, market_path, preferences_path, output, collection)
    else:
        data = _stable_market(
            root,
            state,
            market,
            market_path,
            preferences_path,
            collection,
            explicit_market,
            explicit_preferences,
            scenario,
        )
    data["rerun"] = [
        "roth",
        "--project",
        str(root),
        "agent",
        "next",
        "--scenario",
        scenario,
        "--output",
        str(data.get("next_output", output)),
    ]
    if explicit_market or scenario in {"teams", "reviews"}:
        data["rerun"] += ["--market", str(market_path)]
    if explicit_preferences or scenario in {"teams", "reviews"}:
        data["rerun"] += [
            "--preferences",
            str(data.get("next_preferences", preferences_path)),
        ]
    if scenario in {"teams", "reviews"}:
        data["rerun"] += ["--field-dir", str(field_dir)]
        if contacts_path:
            data["rerun"] += ["--contacts", str(contacts_path)]
    if collection:
        data["rerun"] += ["--collection", collection]
    if scenario == "many-to-one":
        data["matching_contract"] = {
            "capacities": "Nonnegative integer upper bounds, default one; at most one side may exceed one. Zero closes a position. Vacant slots are allowed.",
            "preferences": "Rank individuals independently of the other assigned partners. Include all acceptable candidates; capacity does not limit ranking length.",
            "scope": "Couples, minimum fill quotas, requirements on group composition, and many-to-many assignments require a different formulation.",
            "review": "Report all partners, filled and vacant slots, and assigned-partner rank lists. Participant match rates count anyone with at least one partner; slot fill rates count assignments.",
        }
    data["agent_contract"] = [
        "Explain the next decision in plain language; use prior answers rather than asking again.",
        "Execute applicable actions within the user's existing authorization, then rerun guidance.",
        "Questions are for the calling agent to resolve with the user when context is insufficient; Roth does not send them.",
        "Keep real inputs separate from synthetic examples. Never fill missing preferences with fabricated answers.",
        "External model calls and invitations require authorization; local guidance neither performs nor authorizes them.",
    ]
    return data


def _teams(market, market_path, preferences_path, output, collection):
    from .teams import evaluate_assignment, validate_team_inputs, validate_team_market

    if market is None:
        return _response(
            "teams",
            "define_market",
            "Gather the student roster, project descriptions, and organizer rules; write the team market file. One team uses each project at most once. Reuse settled decisions.",
            questions=[
                question(
                    "rosters",
                    "Which students and projects participate, and what are their stable IDs and display names?",
                ),
                question(
                    "team_size",
                    "What is the target size, are smaller/larger teams allowed, and what are the minimum/maximum sizes?",
                ),
                question(
                    "objective",
                    "What weight should teammate preferences receive, and which project or teammate exclusions are hard constraints?",
                ),
            ],
            input_contract={
                "market_file": str(market_path),
                "fields": [
                    "students: [{id, name}]",
                    "projects: [{id, name}]",
                    "config: {target_size, allow_smaller, allow_larger, min_size, max_size, social_weight}",
                ],
                "reference": "https://github.com/expectedparrot/roth/blob/main/docs/teams.md",
            },
            explanation="Target sizes take priority over preference gains. This optimizes normalized Borda scores; it does not promise stability or strategy-proofness.",
        )
    try:
        market = validate_team_market(market)
    except RothError as error:
        return _response(
            "teams",
            "repair_market",
            "Correct the market definition before collecting or solving preferences.",
            issues=[str(error)],
        )
    if collection == "delegated":
        return _response(
            "teams",
            "unsupported_collection",
            "Roth's delegated scoring workflow currently belongs to two-sided stable matching. For teams, obtain completed explicit project and teammate rankings; do not feed this market to score plan.",
            supported=False,
        )
    if not preferences_path.is_file():
        return _response(
            "teams",
            "collect_preferences",
            "Ask each student for project and teammate rankings, best first, and record completed submissions in the preference file. Missing submissions must remain missing.",
            input_contract={
                "preferences_file": str(preferences_path),
                "record_fields": [
                    "student_id",
                    "projects",
                    "teammates",
                    "unacceptable_projects",
                    "incompatible_teammates",
                    "complete",
                    "source",
                ],
            },
            collection="Collect through a suitable survey or directly and convert responses to this JSON contract. Use agent next --collection human for native team assessment/ranking surveys, or import explicit records.",
            scoring="Partial and empty completed rankings are permitted. Unranked options score zero but remain distinct from hard exclusions. An incompatibility from either student prohibits pairing.",
            participants=[p["id"] for p in market["students"]],
        )
    try:
        market, preferences = validate_team_inputs(market, read_json(preferences_path))
    except RothError as error:
        return _response(
            "teams",
            "repair_preferences",
            "Resolve incomplete or invalid student submissions; preserve genuine omissions and exclusions.",
            issues=[str(error)],
        )
    input_hash = digest({"market": market, "preferences": preferences})
    old_result = output / "result.json"
    if old_result.is_file():
        result = read_json(old_result)
        if result.get("input_hash") == input_hash:
            try:
                checked = evaluate_assignment(
                    market, preferences, result["assignments"]
                )
                if (
                    checked["teams"] != result["teams"]
                    or abs(checked["total_score"] - result["total_score"]) > 1e-8
                ):
                    raise RothError(
                        "Saved result does not agree with independently recomputed assignments and scores"
                    )
            except (RothError, KeyError, TypeError) as error:
                return _response(
                    "teams",
                    "inspect_result",
                    "The saved result failed verification. Preserve it and investigate before presenting it as a valid solution.",
                    issues=[str(error)],
                )
            if (output / "index.html").is_file():
                data = _response(
                    "teams",
                    "review_results",
                    "Open the report and explain the teams, project ranks, received teammate preferences, and students who received an unranked project. Discuss compromises rather than treating the aggregate objective as everyone's satisfaction.",
                    report=str(output / "index.html"),
                    statistics=checked["statistics"],
                    solution_status=result.get("solution_status"),
                    input_hash=input_hash,
                    explanation="Feasibility and scores were rechecked. Equal-score optima can differ. No stability or strategy-proofness guarantee.",
                )
                data["complete"] = result.get("solution_status") == "optimal"
                if not data["complete"]:
                    data["questions"] = [
                        question(
                            "solver_limit",
                            "The saved assignment is feasible but not proven optimal. Should we accept it or rerun with more solver time into a new directory?",
                        )
                    ]
                return data
    destination = fresh_path(output)
    if importlib.util.find_spec("scipy") is None:
        checkout = Path(__file__).resolve().parents[2]
        install = [sys.executable, "-m", "pip", "install"]
        install += (
            ["-e", f"{checkout}[teams]"]
            if (checkout / "pyproject.toml").is_file()
            else ["roth[teams] @ git+https://github.com/expectedparrot/roth.git@main"]
        )
        return _response(
            "teams",
            "install_solver",
            "Install the optional team solver in the environment running Roth, then rerun guidance.",
            actions=[
                action(
                    install,
                    "Install SciPy/HiGHS solver extra",
                    mutates=True,
                    network=True,
                )
            ],
        )
    return _response(
        "teams",
        "solve",
        "The input files are complete and valid. Explain the organizer's size/score policy and solve the joint assignment. Feasibility is determined by the solver; no exclusions will be relaxed.",
        config=market["config"],
        input_hash=input_hash,
        existing_output="Preserved; a fresh output directory is selected."
        if output.exists()
        else None,
        actions=[
            action(
                [
                    "roth",
                    "teams",
                    "solve",
                    market_path,
                    "--preferences",
                    preferences_path,
                    "--output",
                    destination,
                ],
                "Solve teams and projects and export frozen inputs and report",
                mutates=True,
            )
        ],
        next_output=str(destination),
    )


def _stable_market(
    root,
    state,
    market,
    market_path,
    preferences_path,
    collection,
    explicit_market,
    explicit_preferences,
    scenario="one-to-one",
):
    from .market import eligible, policy, validate_market, validate_preferences
    from .workflow import freeze, ingest_preferences, status

    if state and state["market"]:
        if explicit_market and market is not None:
            try:
                supplied = validate_market(market)
            except RothError as error:
                return _response(
                    scenario,
                    "repair_market",
                    "Correct the supplied market file.",
                    issues=[str(error)],
                )
            if supplied != state["market"]:
                return _response(
                    scenario,
                    "resolve_market_revision",
                    "The supplied market differs from the initialized market. Inspect the changes; use configure for organizer policy revisions or a separate project for a different roster. Do not silently reinitialize the store.",
                )
        market = state["market"]
    elif market is None:
        return _response(
            scenario,
            "define_market",
            "Gather the two participant lists and organizer rules. Write market.json with participants tagged left/right; capacity defaults to one; at most one side may have capacity above one. Use nonnegative integer capacities, including zero for closed positions. Do not manufacture a second side for a roommate problem.",
            questions=[
                question(
                    "sides",
                    "Who is on each side, which side can accept several partners, and what is each participant’s maximum capacity?",
                ),
                question(
                    "policies",
                    "Which side proposes, what makes a partner unacceptable or ineligible, and can participants remain unmatched?",
                ),
                question(
                    "collection",
                    "Do we have explicit rankings, need human ranking surveys, or want organizer-authorized delegated preferences?",
                    ["rankings", "human", "delegated"],
                ),
            ],
            input_contract={
                "market_file": str(market_path),
                "fields": [
                    "participants: [{id, side, name, capacity (default 1), profile, preferences, contact}]",
                    "config: {proposing_side, delegation, side_policies, unknown_policy}",
                ],
                "reference": "https://github.com/expectedparrot/roth/blob/main/docs/contracts.md",
            },
            explanation="Capacities are upper bounds, not required fill levels. Preferences must rank individuals independently of other partners (responsive preferences); couples, group composition requirements, and capacities above one on both sides are unsupported. Rank all acceptable candidates, not just as many as capacity. Deferred acceptance allows unmatched participants. The organizer sets direct/delegated/confirmation policies, possibly separately by side.",
        )
    else:
        try:
            market = validate_market(market)
        except RothError as error:
            return _response(
                scenario,
                "repair_market",
                "Correct the market definition before initialization.",
                issues=[str(error)],
            )
        return _response(
            scenario,
            "initialize",
            "Initialize this validated stable-matching market; preferences are imported or collected separately.",
            actions=[
                action(
                    ["roth", "--project", root, "init", market_path],
                    "Initialize the market",
                    mutates=True,
                )
            ],
        )
    prefix = ["roth", "--project", str(root)]
    current = status(state)
    if current.get("complete") and not explicit_preferences:
        exported = current["report"]
        report = exported.get("report") if isinstance(exported, dict) else None
        if report and Path(report).is_file():
            data = _response(
                scenario,
                "review_results",
                "Explain all assignments, unmatched reasons, filled and vacant slots, assigned-partner rank lists, proposer sensitivity, and candidate coverage. Describe stability relative to the frozen submitted/inferred preferences.",
                report=report,
                progress=current,
            )
            data["complete"] = True
            return data
        run = current["runs"][-1]
        return _response(
            scenario,
            "export_report",
            "The recorded report file is missing. Export the saved run into a fresh directory.",
            actions=[
                action(
                    prefix
                    + [
                        "report",
                        "--run",
                        run,
                        "--output",
                        fresh_path(root / f"report-{run}"),
                    ],
                    "Re-export saved assignments",
                    mutates=True,
                )
            ],
        )
    # Default fixture files are not assumed authoritative over a completed project.
    should_import = explicit_preferences or (
        collection in (None, "rankings") and current["missing"]
    )
    if preferences_path.is_file() and should_import:
        try:
            incoming = validate_preferences(market, read_json(preferences_path))
            changes = [
                r
                for r in incoming
                if state["preferences"].get(r["participant_id"]) != r
            ]
            if changes:
                trial = deepcopy(state)
                ingest_preferences(trial, incoming)
                return _response(
                    scenario,
                    "import_preferences",
                    "Import the existing completed preference records, preserving their declared source. Do not substitute synthetic fixtures for human submissions.",
                    actions=[
                        action(
                            prefix + ["preferences", "import", preferences_path],
                            "Import completed rankings",
                            mutates=True,
                        )
                    ],
                )
        except RothError as error:
            return _response(
                scenario,
                "review_preference_import",
                "The preference file is invalid or conflicts with active records. Determine which submissions are authoritative and whether an explicit revision is intended; preserve previous history.",
                issues=[str(error)],
            )
    if current.get("complete") and explicit_preferences:
        # The explicitly supplied file introduced no changes; inspect saved results.
        return _stable_market(
            root,
            state,
            market,
            market_path,
            preferences_path,
            collection,
            False,
            False,
            scenario,
        )
    if current["missing"] and not current["fields"] and not current["score_plans"]:
        if collection is None:
            policies = sorted({policy(market, p) for p in current["missing"]})
            return _response(
                scenario,
                "choose_collection",
                "Find out how the remaining participants will supply preferences, using the organizer's existing policy. Rerun with --collection rankings, human, or delegated.",
                questions=[
                    question(
                        "collection",
                        "Will the remaining preferences come from existing ranking files, human surveys, or delegated model evaluations?",
                        ["rankings", "human", "delegated"],
                    )
                ],
                missing=current["missing"],
                organizer_policies=policies,
                explanation="A delegation permission permits model inference; it does not mean a model run has already occurred.",
            )
        if collection == "rankings":
            return _response(
                scenario,
                "collect_preferences",
                "Collect the missing completed rankings into the preference file, then rerun guidance. Preserve unknown candidates, explicit rejections, and nonresponse as different states.",
                missing=current["missing"],
                preferences_file=str(preferences_path),
            )
        if collection == "delegated" and all(
            policy(market, p) == "direct" for p in current["missing"]
        ):
            return _response(
                scenario,
                "configure_delegation",
                "The organizer currently requires direct preferences. Resolve whether to enable delegated or confirmation-required rankings and record that policy with configure before building scoring plans.",
                questions=[
                    question(
                        "delegation",
                        "Which sides may delegate, and must participants confirm inferred rankings?",
                        ["delegated", "confirm", "different policy by side"],
                    )
                ],
                actions=[
                    action(
                        prefix + ["configure", "--help"],
                        "Inspect organizer policy command",
                    )
                ],
            )
        if collection == "human":
            # Human rankings are valid even when the organizer permits delegation.
            graph = eligible(market)
            kind = (
                "screening"
                if any(len(graph[p]) > 15 for p in current["missing"])
                else "ranking"
            )
            argv = prefix + [
                "field",
                "build",
                "--name",
                "rankings_1",
                "--kind",
                kind,
                "--output",
                fresh_path(root / "rankings"),
            ]
            for pid in current["missing"]:
                argv += ["--participant", pid]
            return _response(
                scenario,
                "build_human_surveys",
                "Build and review personalized rankings. For long lists, use screening batches or an explicit shortlist rather than exceeding the review budget. Review handoff recipients before authorized external publication and email delivery.",
                actions=[
                    action(
                        argv,
                        "Build survey packages without sending invitations",
                        mutates=True,
                    )
                ],
                setup="Native survey packages require Roth's fielding extra. Humanize publication and email delivery are external ep steps.",
            )
    recommended = list(current.get("next", []))
    if not recommended:
        return _response(
            scenario,
            "inspect_progress",
            "Inspect the project before choosing another action.",
            progress=current,
        )
    argv = prefix + recommended[1:]
    verb = recommended[1:3]
    phase = "continue_workflow"
    explanation = current.get(
        "needs",
        "Follow the next step from the saved project state, then rerun agent next.",
    )
    questions = []
    if verb == ["field", "status"]:
        phase = "collect_human_responses"
        explanation = "Inspect field status and the saved handoff. Externally retrieve completed responses and import them against the registered survey packages. Do not treat missing responses as rejections or automatically send invitations."
    elif verb == ["score", "plan"]:
        phase = "plan_delegation"
        explanation = "Select the model, candidate shortlist size, and evaluation budget, then build a scoring plan. Decide whether to include the optional A-versus-B calibration/held-out benchmark before final scoring."
        questions = [
            question(
                "scoring",
                "Which model and evaluation budget should be used, and should we include the optional preference benchmark?",
            )
        ]
    elif verb == ["score", "status"]:
        phase = "collect_model_results"
        explanation = "Inspect outstanding scoring tasks and the saved handoff. Execute external model calls only within authorization, import Results, and preserve calibration versus held-out benchmark separation."
    elif verb == ["score", "apply"]:
        phase = "apply_model_preferences"
        explanation = "Check scoring coverage and any requested benchmark before applying scores. Follow organizer confirmation requirements; do not bypass confirmation or overwrite human rankings."
    elif verb == ["preferences", "freeze"]:
        pending = [
            pid
            for pid, row in state["preferences"].items()
            if row["source"] == "delegated"
            and policy(market, pid) == "confirm"
            and not row["confirmed"]
        ]
        if pending:
            existing = [
                name
                for name, field in state["fields"].items()
                if field["kind"] == "confirmation"
                and set(field["packages"]) - set(field["responses"])
            ]
            if existing:
                follow = prefix + ["field", "status", "--name", existing[-1]]
            else:
                follow = prefix + [
                    "field",
                    "build",
                    "--name",
                    f"confirmation_{len(state['fields']) + 1}",
                    "--kind",
                    "confirmation",
                    "--output",
                    fresh_path(root / "confirmation"),
                ]
                for pid in pending:
                    follow += ["--participant", pid]
            return _response(
                scenario,
                "confirm_preferences",
                "The organizer requires these participants to confirm their inferred rankings before matching. Collect confirmations through the fielding workflow, preserving the original scores and responses.",
                participants=pending,
                actions=[
                    action(
                        follow,
                        "Collect required participant confirmations",
                        mutates=not bool(existing),
                    )
                ],
            )
        try:
            freeze(deepcopy(state), recommended[-1])
        except RothError as error:
            return _response(
                scenario,
                "resolve_before_freeze",
                "The preferences are complete but cannot yet be frozen. Resolve the reported coverage, benchmark, policy, or evidence issue; do not bypass the organizer's requirements.",
                issues=[str(error)],
            )
        phase = "freeze_preferences"
        explanation = "Freeze the exact active cohort and preference records. Explain source and evaluation coverage; excluding nonrespondents requires an explicit organizer decision."
    elif recommended[1] == "match":
        phase = "match"
        explanation = "Run deferred acceptance on the frozen snapshot and compare proposing sides. Explain why some participants may remain unmatched."
    elif recommended[1] == "report":
        phase = "export_report"
        argv[argv.index("--output") + 1] = str(fresh_path(root / recommended[-1]))
        explanation = "Export the report, then explain assignments, preference statistics, unmatched reasons, and the scope of the stability check."
    elif verb == ["field", "build"]:
        phase = "build_surveys"
        explanation = "Build the required ranking or preference-instruction surveys. Handle long lists with screening or explicit shortlists; review the instrument before authorized external Humanize fielding."
    readonly = "--help" in argv or verb in (["field", "status"], ["score", "status"])
    return _response(
        scenario,
        phase,
        explanation,
        progress=current,
        questions=questions,
        actions=[action(argv, explanation, mutates=not readonly)],
    )
