"""Preference revisions, immutable snapshots, matching runs, and workflow guidance."""

import copy
from datetime import datetime, timezone

from .analysis import preference_statistics
from .common import digest, identifier, require
from .market import capacities, eligible, participants, policy, validate_preferences
from .matching import deferred_acceptance


def ingest_preferences(state, rows, replace=False, origin=None):
    require(state["market"] is not None, "Import a market first")
    rows = validate_preferences(state["market"], rows)
    changes = []
    for row in rows:
        pid = row["participant_id"]
        old = state["preferences"].get(pid)
        if old == row:
            continue
        require(
            old is None or replace,
            f"Preference already exists for {pid}; use --replace for an explicit revision",
        )
        require(
            not (old and old["source"] == "human" and row["source"] != "human"),
            f"Cannot replace human preferences with inferred or synthetic preferences for {pid}",
        )
        if row["source"] == "delegated":
            require(
                policy(state["market"], pid) != "direct",
                f"Organizer has not enabled delegation for {pid}",
            )
        changes.append(row)
    for row in changes:
        state["preference_history"].append(
            {
                "record": copy.deepcopy(row),
                "origin": origin,
                "revision": len(state["preference_history"]) + 1,
            }
        )
        state["preferences"][row["participant_id"]] = row
    return {"imported": len(changes), "unchanged": len(rows) - len(changes)}


def freeze(state, name, exclude=()):
    identifier(name)
    require(name not in state["snapshots"], f"Snapshot {name} already exists")
    market = state["market"]
    require(market is not None, "Import a market first")
    index, graph = participants(market), eligible(market)
    require(set(exclude) <= set(index), "Unknown excluded participant")
    active = sorted(set(index) - set(exclude))
    require(active, "Cannot freeze an empty cohort")
    missing = [p for p in active if p not in state["preferences"]]
    require(
        not missing,
        f"Missing completed preferences: {', '.join(missing)}",
        "INCOMPLETE_COHORT",
    )
    prefs = {p: copy.deepcopy(state["preferences"][p]) for p in active}
    unresolved = {}
    for p, row in prefs.items():
        if row.get("score_plan"):
            from .benchmark import preference_evidence_hash

            require(
                row.get("human_evidence_hash") == preference_evidence_hash(state, p),
                f"Pairwise evidence changed for {p}; reapply scores before freezing",
            )
        unresolved[p] = sorted(
            (graph[p] & set(active)) - set(row["ranking"] + row["unacceptable"])
        )
        if row["source"] == "delegated":
            require(
                not row.get("market_hash") or row["market_hash"] == digest(market),
                f"Delegated preferences for {p} belong to an older market",
            )
            require(policy(market, p) != "direct", f"Delegation disabled for {p}")
            require(
                policy(market, p) != "confirm" or row["confirmed"],
                f"Participant confirmation required for {p}",
            )
            if market["config"]["benchmark_policy"] == "gate":
                reports = [
                    b.get("report", {}).get("participants", {}).get(p)
                    for b in state["benchmarks"].values()
                    if b.get("evaluation_score_hash") == row.get("score_hash")
                    and not b.get("retired")
                ]
                acceptable = [
                    r
                    for r in reports
                    if r
                    and r["overall"]["denominator"]
                    >= market["config"]["benchmark_min_answers"]
                    and r["overall"]["rate"]
                    >= market["config"]["benchmark_min_accuracy"]
                ]
                require(
                    acceptable,
                    f"No passing benchmark for current delegated preferences of {p}",
                )
    require(
        market["config"]["unknown_policy"] != "require_complete"
        or not any(unresolved.values()),
        "Unevaluated/undecided candidates remain; complete preferences or change unknown_policy",
    )
    snapshot = {
        "name": name,
        "market": copy.deepcopy(market),
        "active": active,
        "excluded": sorted(exclude),
        "preferences": prefs,
        "unknown": unresolved,
        "coverage": "restricted"
        if any(unresolved.values())
        else "complete_for_active_cohort",
        "preference_sources": sorted({r["source"] for r in prefs.values()}),
        "benchmark_reports": {
            name: copy.deepcopy(b["report"])
            for name, b in state["benchmarks"].items()
            if b.get("report") and b["market_hash"] == digest(market)
        },
        "cohort_scope": "reduced" if exclude else "all_participants",
    }
    snapshot["hash"] = digest(snapshot)
    state["snapshots"][name] = snapshot
    return snapshot


def run_matching(state, snapshot_name, name, side=None, compare=True):
    identifier(name)
    require(name not in state["runs"], f"Run {name} already exists")
    require(snapshot_name in state["snapshots"], "Unknown snapshot")
    snapshot = state["snapshots"][snapshot_name]
    market, prefs, active = (
        snapshot["market"],
        snapshot["preferences"],
        set(snapshot["active"]),
    )
    index = participants(market)
    left, right = {}, {}
    for p, row in prefs.items():
        (left if index[p]["side"] == "left" else right)[p] = [
            c for c in row["ranking"] if c in active
        ]
    side = side or market["config"]["proposing_side"]
    quotas = capacities(market, active)
    result = deferred_acceptance(left, right, side, quotas)
    result.update(
        {
            "name": name,
            "snapshot": snapshot_name,
            "snapshot_hash": snapshot["hash"],
            "scope": {
                k: snapshot[k]
                for k in ("coverage", "cohort_scope", "preference_sources")
            },
            "benchmarks": snapshot.get("benchmark_reports", {}),
            "statistics": preference_statistics(
                market, prefs, active, result["matches"]
            ),
        }
    )
    if compare:
        reverse = deferred_acceptance(
            left, right, "right" if side == "left" else "left", quotas
        )
        result["comparison"] = {
            "proposing_side": reverse["proposing_side"],
            "matches": reverse["matches"],
            "changed_pairs": sorted(
                set(map(tuple, result["matches"])) ^ set(map(tuple, reverse["matches"]))
            ),
            "statistics": preference_statistics(
                market, prefs, active, reverse["matches"]
            ),
        }
    state["runs"][name] = result
    return result


def status(state):
    market = state["market"]
    if market is None:
        return {"initialized": False, "next": ["roth", "init", "market.json"]}
    index = participants(market)
    missing = sorted(set(index) - set(state["preferences"]))
    result = {
        "initialized": True,
        "participants": len(index),
        "completed": len(state["preferences"]),
        "missing": missing,
        "snapshots": list(state["snapshots"]),
        "runs": list(state["runs"]),
        "fields": list(state["fields"]),
        "score_plans": list(state["score_plans"]),
        "benchmarks": list(state["benchmarks"]),
        "config": market["config"],
    }
    current_snapshots = [
        name
        for name, s in state["snapshots"].items()
        if s["market"] == market
        and all(s["preferences"][p] == state["preferences"].get(p) for p in s["active"])
    ]
    current_runs = [
        name for name, r in state["runs"].items() if r["snapshot"] in current_snapshots
    ]
    # A deliberate reduced cohort can be complete while excluded people remain nonrespondents.
    if missing and not current_snapshots:
        plans = [
            name
            for name, p in state["score_plans"].items()
            if p["market_hash"] == digest(market)
        ]
        fields = [
            name
            for name, f in state["fields"].items()
            if f["kind"] != "benchmark" and set(f["packages"]) - set(f["responses"])
        ]
        if fields:
            result["next"] = ["roth", "field", "status", "--name", fields[-1]]
            result["needs"] = (
                "Collect and import pending field responses using the registered handoff."
            )
        elif plans:
            from .delegation import score_status

            pending = score_status(state, plans[-1])["missing"]
            result["next"] = [
                "roth",
                "score",
                "status" if pending else "apply",
                "--name",
                plans[-1],
            ]
        else:
            direct = [p for p in missing if policy(market, p) == "direct"]
            instructions = [
                p
                for p in missing
                if policy(market, p) != "direct"
                and not index[p].get("preferences", "").strip()
            ]
            targets = direct or instructions
            if targets:
                result["next"] = [
                    "roth",
                    "field",
                    "build",
                    "--name",
                    f"survey_{len(state['fields']) + 1}",
                    "--kind",
                    "ranking" if direct else "instructions",
                ]
                for p in targets:
                    result["next"] += ["--participant", p]
            else:
                result["next"] = ["roth", "score", "plan", "--help"]
                result["needs"] = (
                    "Organizer must choose a model and evaluation budget for the scoring plan."
                )
    elif not current_snapshots:
        result["next"] = [
            "roth",
            "preferences",
            "freeze",
            "--name",
            f"snapshot_{len(state['snapshots']) + 1}",
        ]
    elif not current_runs:
        result["next"] = [
            "roth",
            "match",
            "--snapshot",
            current_snapshots[-1],
            "--name",
            f"run_{len(state['runs']) + 1}",
        ]
    else:
        run_name = current_runs[-1]
        if run_name in state.get("exports", {}):
            result["complete"] = True
            result["report"] = state["exports"][run_name]
            result["next"] = []
        else:
            result["next"] = [
                "roth",
                "report",
                "--run",
                run_name,
                "--output",
                f"report-{run_name}",
            ]
    deadline = market["config"].get("deadline")
    result["deadline_passed"] = bool(
        deadline and datetime.now(timezone.utc) > datetime.fromisoformat(deadline)
    )
    return result
