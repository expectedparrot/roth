"""Organizer counterfactuals from verified, frozen reports; no survey or state writes."""

from copy import deepcopy
from pathlib import Path

from .common import (
    RothError,
    digest,
    identifier,
    number,
    read_json,
    require,
    write_json,
)
from .matching import deferred_acceptance, verify_matching


def stable_inputs(market, preferences):
    from .market import capacities, participants, validate_market, validate_preferences

    market = validate_market(market)
    require(
        isinstance(preferences, dict) and preferences,
        "Frozen preferences must be a nonempty object",
    )
    rows = validate_preferences(market, list(preferences.values()))
    require(
        {r["participant_id"] for r in rows} == set(preferences),
        "Preference keys disagree with respondent IDs",
    )
    require(
        all(r["participant_id"] == p for p, r in preferences.items()),
        "Incorrect preference key",
    )
    people = participants(market)
    sides = [
        {
            p: [c for c in r["ranking"] if c in preferences]
            for p, r in preferences.items()
            if people[p]["side"] == side
        }
        for side in ("left", "right")
    ]
    return market, sides, capacities(market, preferences)


def verify_result(mode, market, preferences, result):
    """Recheck saved assignments against their own frozen input constraints."""
    if mode == "stable":
        market, (left, right), quotas = stable_inputs(market, preferences)
        checked = verify_matching(left, right, result["matches"], quotas)
        require(
            checked["stable"],
            "Baseline matching is infeasible or unstable",
            "INVALID_SOLUTION",
        )
        expected = deferred_acceptance(left, right, result["proposing_side"], quotas)
        require(
            all(
                result.get(k) == expected[k]
                for k in (
                    "matches",
                    "capacities",
                    "vacancies",
                    "unmatched",
                    "verification",
                )
            ),
            "Saved matching disagrees with frozen preferences or capacities",
            "INVALID_SOLUTION",
        )
        return market, preferences
    if mode == "reviews":
        from .reviews import validate_review_inputs
        from .review_report import verify_review_result

        market, preferences = validate_review_inputs(market, preferences)
        verify_review_result(market, preferences, result)
    else:
        from .teams import evaluate_assignment, validate_team_inputs

        market, preferences = validate_team_inputs(market, preferences)
        require(
            result.get("mode") == "teams"
            and result.get("input_hash")
            == digest({"market": market, "preferences": preferences}),
            "Team result belongs to different inputs",
            "INVALID_SOLUTION",
        )
        checked = evaluate_assignment(market, preferences, result["assignments"])
        require(
            all(result.get(k) == v for k, v in checked.items()),
            "Saved team outcomes disagree with assignments",
            "INVALID_SOLUTION",
        )
        phases = result.get("solver", {}).get("phases", {})
        optimal = all(
            phases.get(p, {}).get("optimal") is True
            for p in ("team_size", "preferences")
        )
        require(
            result.get("solution_status") in ("optimal", "feasible_limit")
            and (result["solution_status"] == "optimal") == optimal,
            "Inconsistent team solver status",
            "INVALID_SOLUTION",
        )
    return market, preferences


def load_baseline(directory):
    root = Path(directory)
    market, preferences = (
        read_json(root / "market.json"),
        read_json(root / "preferences.json"),
    )
    require(
        not ((root / "matches.json").exists() and (root / "result.json").exists()),
        "Ambiguous report: both matching and optimization results",
    )
    result = read_json(
        root / ("matches.json" if (root / "matches.json").exists() else "result.json")
    )
    require(
        isinstance(market, dict) and isinstance(result, dict),
        "Baseline market and result must be objects",
    )
    mode = "stable" if "participants" in market else result.get("mode")
    require(mode in ("stable", "teams", "reviews"), "Unsupported baseline report mode")
    market, preferences = verify_result(mode, market, preferences, result)
    evidence = {"assignments_verified": True, "snapshot_hash_verified": False}
    if mode == "stable" and (root / "snapshot.json").exists():
        snapshot = read_json(root / "snapshot.json")
        checksum = snapshot.pop("hash")
        require(
            checksum == digest(snapshot) == result.get("snapshot_hash")
            and snapshot["market"] == market
            and snapshot["preferences"] == preferences
            and set(snapshot["active"]) == set(preferences),
            "Saved snapshot does not match report inputs/result",
            "INTEGRITY_ERROR",
        )
        evidence["snapshot_hash_verified"] = True
    return {
        "mode": mode,
        "market": market,
        "preferences": preferences,
        "result": result,
        "verification": evidence,
    }


def prepare_scenarios(baseline, scenarios):
    """Restricted organizer changes; no roster, ranking, source, or exclusion edits."""
    require(
        isinstance(scenarios, list) and scenarios, "Scenarios must be a nonempty array"
    )
    prepared, used = [], {"baseline"}
    mode = baseline["mode"]
    allowed = {
        "stable": {"capacities", "proposing_side"},
        "teams": {"config", "close_projects"},
        "reviews": {"reviewer_bounds", "reviews_required"},
    }[mode]
    for spec in scenarios:
        require(isinstance(spec, dict), "Each scenario must be an object")
        name = identifier(spec.get("name"))
        require(
            name.casefold() not in used,
            "Duplicate or reserved scenario name (case insensitive)",
        )
        used.add(name.casefold())
        require(
            not set(spec) - {"name"} - allowed,
            f"Unsupported {mode} scenario fields: {sorted(set(spec) - {'name'} - allowed)}",
        )
        market = deepcopy(baseline["market"])
        prefs = deepcopy(baseline["preferences"])
        side = baseline["result"].get("proposing_side")
        if mode == "stable":
            changes = spec.get("capacities", {})
            require(
                isinstance(changes, dict) and set(changes) <= set(prefs),
                "capacities must map active participant IDs to absolute capacities",
            )
            for p in market["participants"]:
                if p["id"] in changes:
                    p["capacity"] = changes[p["id"]]
            side = spec.get("proposing_side", side)
            require(side in ("left", "right"), "Invalid proposing side")
            if "proposing_side" in spec:
                market["config"]["proposing_side"] = side
            market, _, _ = stable_inputs(market, prefs)
        elif mode == "teams":
            from .teams import validate_team_inputs

            config = spec.get("config", {})
            require(isinstance(config, dict), "config must be an object")
            market["config"].update(config)
            closed = spec.get("close_projects", [])
            require(
                isinstance(closed, list)
                and all(isinstance(p, str) for p in closed)
                and len(closed) == len(set(closed)),
                "close_projects must be a unique ID list",
            )
            if closed:
                market["closed_projects"] = sorted(
                    set(market.get("closed_projects", [])) | set(closed)
                )
            market, prefs = validate_team_inputs(market, prefs)
        else:
            from .reviews import validate_review_inputs

            bounds, required = (
                spec.get("reviewer_bounds", {}),
                spec.get("reviews_required", {}),
            )
            require(
                isinstance(bounds, dict)
                and set(bounds) <= {r["id"] for r in market["reviewers"]},
                "Unknown reviewer bounds ID",
            )
            require(
                isinstance(required, dict)
                and set(required) <= {p["id"] for p in market["submissions"]},
                "Unknown submission coverage ID",
            )
            for r in market["reviewers"]:
                changes = bounds.get(r["id"], {})
                require(
                    isinstance(changes, dict)
                    and not set(changes) - {"min_reviews", "max_reviews"},
                    "Only min_reviews/max_reviews can change",
                )
                r.update(changes)
            for p in market["submissions"]:
                if p["id"] in required:
                    p["reviews_required"] = required[p["id"]]
            market, prefs = validate_review_inputs(market, prefs)
        prepared.append(
            {
                "name": name,
                "changes": deepcopy(spec),
                "market": market,
                "preferences": prefs,
                "proposing_side": side,
            }
        )
    return prepared


def outcomes(mode, baseline_market, preferences, result, scenario_market):
    """Evaluate every outcome on the baseline's fixed ranking/score scale."""
    if mode == "teams":
        from .teams import score_tables

        scores = score_tables(baseline_market, preferences)
        rows = {r["student_id"]: r for r in preferences}
        assigned, config = result["assignments"], baseline_market["config"]
        output = {}
        for i, p in assigned.items():
            peers = sorted(j for j in assigned if j != i and assigned[j] == p)
            project_score = scores[i]["projects"].get(p, 0) / max(
                1, len(baseline_market["projects"]) - 1
            )
            social_score = sum(scores[i]["teammates"].get(j, 0) for j in peers) / (
                max(1, len(rows) - 2) * (config["target_size"] - 1)
            )
            output[i] = {
                "assigned": [p],
                "teammates": peers,
                "load": len(peers),
                "ranks": [
                    rows[i]["projects"].index(p) + 1
                    if p in rows[i]["projects"]
                    else None
                ],
                "project_score": project_score,
                "social_score": social_score,
                "score": (1 - config["social_weight"]) * project_score
                + config["social_weight"] * social_score,
            }
        return output
    if mode == "reviews":
        from .reviews import review_scores

        scores = review_scores(baseline_market, preferences)
        rows = {r["reviewer_id"]: r for r in preferences}
        output = {}
        for r, ps in result["reviewers"].items():
            ranking = rows.get(r, {}).get("ranking", [])
            scored = baseline_market["config"]["scoring"] != "none"
            score = sum(scores.get(r, {}).get(p, 0) for p in ps) if scored else None
            output[r] = {
                "assigned": sorted(ps),
                "load": len(ps),
                "score": score,
                "mean_score": score / len(ps) if scored and ps else None,
                "ranks": [
                    ranking.index(p) + 1 if p in ranking else None for p in sorted(ps)
                ],
            }
        return output
    from .market import capacities

    quotas = capacities(scenario_market, preferences)
    assigned = {p: [] for p in preferences}
    for a, b in result["matches"]:
        assigned[a].append(b)
        assigned[b].append(a)
    return {
        p: {
            "assigned": sorted(ps),
            "load": len(ps),
            "capacity": quotas[p],
            "vacancies": quotas[p] - len(ps),
            "ranks": [preferences[p]["ranking"].index(c) + 1 for c in sorted(ps)],
        }
        for p, ps in assigned.items()
    }


def change_label(mode, before, after):
    if mode == "stable":
        n = max(len(before["ranks"]), len(after["ranks"]))
        a, b = (
            sorted(row["ranks"]) + [float("inf")] * (n - len(row["ranks"]))
            for row in (before, after)
        )
        better, worse = (
            any(y < x for x, y in zip(a, b)),
            any(y > x for x, y in zip(a, b)),
        )
        return (
            "mixed"
            if better and worse
            else "better_ranks"
            if better
            else "worse_ranks"
            if worse
            else "equal"
        )
    if before["score"] is None:
        return "unscored"
    if mode == "reviews" and before["load"] != after["load"]:
        return "workload_changed"
    delta = after["score"] - before["score"]
    return (
        "higher_score" if delta > 1e-8 else "lower_score" if delta < -1e-8 else "equal"
    )


def compare_outcomes(baseline, scenario):
    mode, market, prefs = baseline["mode"], baseline["market"], baseline["preferences"]
    before = outcomes(mode, market, prefs, baseline["result"], market)
    after = outcomes(mode, market, prefs, scenario["result"], scenario["market"])
    roster = market[
        {"stable": "participants", "teams": "students", "reviews": "reviewers"}[mode]
    ]
    people = {p["id"]: p for p in roster}
    rows, counts = [], {}
    for p in sorted(before):
        a, b = before[p], after[p]
        label = change_label(mode, a, b)
        counts[label] = counts.get(label, 0) + 1
        changed = a["assigned"] != b["assigned"] or a.get("teammates") != b.get(
            "teammates"
        )
        rows.append(
            {
                "participant_id": p,
                "name": people[p]["name"],
                "side": people[p].get("side"),
                "changed": changed,
                "before": a,
                "after": b,
                "added": sorted(set(b["assigned"]) - set(a["assigned"])),
                "removed": sorted(set(a["assigned"]) - set(b["assigned"])),
                "preference_change": label,
                "score_delta": b["score"] - a["score"]
                if a.get("score") is not None
                else None,
            }
        )
    return {
        "participants": rows,
        "counts": counts,
        "changed_participants": sum(r["changed"] for r in rows),
        "unchanged_participants": sum(not r["changed"] for r in rows),
    }


def compare_reports(baseline_path, scenarios, output, time_limit=60):
    number(time_limit, 0.001)
    root = Path(output)
    require(not root.exists(), "Comparison output directory already exists")
    baseline = load_baseline(baseline_path)
    prepared = prepare_scenarios(baseline, scenarios)
    mode = baseline["mode"]
    # Validate every scenario before creating artifacts or calling a solver.
    runs = []
    for scenario in prepared:
        m, p = scenario["market"], scenario["preferences"]
        same = (
            m == baseline["market"]
            and p == baseline["preferences"]
            and scenario["proposing_side"] == baseline["result"].get("proposing_side")
        )
        try:
            if same:
                result = deepcopy(baseline["result"])
            elif mode == "stable":
                _, (left, right), quotas = stable_inputs(m, p)
                result = deferred_acceptance(
                    left, right, scenario["proposing_side"], quotas
                )
            elif mode == "teams":
                from .teams import solve_teams

                result = solve_teams(m, p, time_limit=time_limit)
            else:
                from .reviews import solve_reviews

                result = solve_reviews(m, p, time_limit=time_limit)
            verify_result(mode, m, p, result)
            scenario.update(
                result=result,
                status=result.get("solution_status", "stable"),
                reused_baseline=same,
            )
            scenario["comparison"] = compare_outcomes(baseline, scenario)
        except RothError as error:
            if error.code not in ("INFEASIBLE", "SOLVER_LIMIT"):
                raise
            scenario.update(
                status=error.code.lower(),
                error={"code": error.code, "message": str(error)},
            )
        runs.append(scenario)
    root.mkdir(parents=True, exist_ok=False)
    frozen = {
        "market": baseline["market"],
        "preferences": baseline["preferences"],
        "result": baseline["result"],
    }
    for filename, value in frozen.items():
        write_json(root / "baseline" / f"{filename}.json", value)
    # Preserve original submitted inputs and the snapshot when available.
    for filename in (
        "submitted-market.json",
        "submitted-preferences.json",
        "snapshot.json",
    ):
        if (Path(baseline_path) / filename).is_file():
            write_json(
                root / "baseline" / filename, read_json(Path(baseline_path) / filename)
            )
    write_json(root / "scenarios.json", scenarios)
    for run in runs:
        for key in ("market", "preferences", "result"):
            if key in run:
                write_json(root / run["name"] / f"{key}.json", run[key])
        write_json(
            root / run["name"] / "scenario.json",
            {
                k: v
                for k, v in run.items()
                if k not in ("market", "preferences", "result")
            },
        )
    manifest = {
        "schema_version": "1.0",
        "mode": mode,
        "synthetic": baseline["market"].get("synthetic", False),
        "baseline_hash": digest(frozen),
        "baseline_verification": baseline["verification"],
        "baseline_status": baseline["result"].get("solution_status", "stable"),
        "baseline_scope": baseline["result"].get("scope"),
        "preference_sources": sorted(
            {
                row["source"]
                for row in (
                    baseline["preferences"].values()
                    if mode == "stable"
                    else baseline["preferences"]
                )
            }
        ),
        "evaluation": "Baseline preferences, Borda universe, target-size divisor and social weight held fixed. Scenario objectives reported separately; scores are not measured welfare.",
        "scenarios": [
            {
                **{
                    k: v
                    for k, v in r.items()
                    if k not in ("market", "preferences", "result")
                },
                "input_hash": digest(
                    {"market": r["market"], "preferences": r["preferences"]}
                ),
                "result_hash": digest(r["result"]) if "result" in r else None,
                "objective_score": r.get("result", {}).get("total_score"),
                "statistics": r.get("result", {}).get("statistics"),
                "vacancies": r.get("result", {}).get("vacancies"),
            }
            for r in runs
        ],
    }
    write_json(root / "comparison.json", manifest)
    from .comparison_report import export_comparison_report

    export_comparison_report(root, baseline, manifest)
    return {
        "report": str((root / "index.html").resolve()),
        "directory": str(root.resolve()),
        "mode": mode,
        "scenarios": [
            {
                "name": r["name"],
                "status": r["status"],
                "counts": r.get("comparison", {}).get("counts"),
                "changed_participants": r.get("comparison", {}).get(
                    "changed_participants"
                ),
            }
            for r in runs
        ],
    }
