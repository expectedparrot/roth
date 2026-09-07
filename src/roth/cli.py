"""JSON-first CLI. Domain operations live in their owning modules."""

from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys

from . import __version__
from .common import RothError, digest, read_json, require, write_json
from .storage import Store


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RothError(message, "USAGE_ERROR")


def parser():
    p = Parser(
        prog="roth",
        description="Two-sided preference collection and one-to-one stable matching",
    )
    p.add_argument("--project", default=".", help="Directory containing .roth")
    p.add_argument("--human", action="store_true", help="Pretty human-readable output")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("version", "capabilities", "guide", "status", "next", "validate"):
        sub.add_parser(name)
    init = sub.add_parser(
        "init", help="Initialize a market from JSON, or two side files"
    )
    init.add_argument("market", nargs="?")
    init.add_argument("--left")
    init.add_argument("--right")
    config = sub.add_parser("configure", help="Record organizer policy changes")
    config.add_argument("config", help="JSON object of config settings")
    ex = sub.add_parser("example").add_subparsers(dest="action", required=True)
    create = ex.add_parser("create", help="Create a fictional internship project")
    create.add_argument("directory")
    create.add_argument("--students", type=int, default=12)
    create.add_argument("--internships", type=int, default=10)
    for name in ("scores", "benchmark"):
        q = ex.add_parser(name, help="Write explicitly synthetic local fixture answers")
        q.add_argument("--name", required=True, help="Score plan or benchmark name")
        q.add_argument("--output", required=True)
        if name == "benchmark":
            q.add_argument(
                "--split", choices=["calibration", "evaluation", "all"], default="all"
            )
    demo = sub.add_parser(
        "demo", help="Create and run the complete offline internship example"
    )
    demo.add_argument("directory")
    pref = sub.add_parser("preferences").add_subparsers(dest="action", required=True)
    pi = pref.add_parser("import")
    pi.add_argument("input")
    pi.add_argument("--replace", action="store_true")
    pf = pref.add_parser("freeze")
    pf.add_argument("--name", required=True)
    pf.add_argument("--exclude", action="append", default=[])
    pref.add_parser("show")
    match = sub.add_parser("match")
    match.add_argument("--snapshot", required=True)
    match.add_argument("--name", required=True)
    match.add_argument("--proposing-side", choices=["left", "right"])
    match.add_argument("--no-compare", action="store_true")
    stats = sub.add_parser("stats")
    stats.add_argument("--run")
    report = sub.add_parser("report")
    report.add_argument("--run", required=True)
    report.add_argument("--output", required=True)
    field = sub.add_parser("field").add_subparsers(dest="action", required=True)
    fb = field.add_parser("build")
    fb.add_argument("--name", required=True)
    fb.add_argument("--output")
    fb.add_argument(
        "--kind",
        choices=["ranking", "screening", "instructions", "confirmation"],
        default="ranking",
    )
    fb.add_argument("--plan")
    fb.add_argument("--max-options", type=int, default=15)
    fb.add_argument("--batch-size", type=int, default=10)
    fb.add_argument("--participant", action="append")
    fb.add_argument(
        "--json-only",
        action="store_true",
        help="Write previews and JSON contracts without native EDSL",
    )
    fi = field.add_parser("import")
    fi.add_argument("input")
    fi.add_argument("--name", required=True)
    fi.add_argument("--edsl", action="store_true")
    fi.add_argument("--replace", action="store_true")
    fr = field.add_parser("register")
    fr.add_argument("--field", required=True)
    fr.add_argument("--package", required=True)
    fr.add_argument("--uuid", required=True)
    fr.add_argument("--delivery")
    fr.add_argument("--status-json")
    fs = field.add_parser("status")
    fs.add_argument("--name", required=True)
    score = sub.add_parser("score").add_subparsers(dest="action", required=True)
    sp = score.add_parser("plan")
    sp.add_argument("--name", required=True)
    sp.add_argument("--output", required=True)
    sp.add_argument("--model", required=True)
    sp.add_argument(
        "--parameters", help="JSON file containing explicit model generation parameters"
    )
    sp.add_argument("--k", type=int, default=10)
    sp.add_argument("--budget", type=int, default=10000)
    sp.add_argument("--seed", type=int, default=17)
    sp.add_argument("--audit", type=int, default=0)
    sp.add_argument("--expand")
    sp.add_argument("--calibration")
    sp.add_argument("--json-only", action="store_true")
    si = score.add_parser("import")
    si.add_argument("input")
    si.add_argument("--name", required=True)
    si.add_argument("--edsl", action="store_true")
    si.add_argument("--source", choices=["delegated", "synthetic"], default="delegated")
    sa = score.add_parser("apply")
    sa.add_argument("--name", required=True)
    sa.add_argument("--replace", action="store_true")
    ss = score.add_parser("status")
    ss.add_argument("--name", required=True)
    sr = score.add_parser("retry", help="Package only missing scoring tasks")
    sr.add_argument("--name", required=True)
    sr.add_argument("--output", required=True)
    bench = sub.add_parser("benchmark").add_subparsers(dest="action", required=True)
    bb = bench.add_parser("build")
    bb.add_argument("--name", required=True)
    bb.add_argument("--scores", required=True)
    bb.add_argument("--output", required=True)
    bb.add_argument("--pairs", type=int, default=6)
    bb.add_argument("--seed", type=int, default=17)
    bb.add_argument("--json-only", action="store_true")
    bp = bench.add_parser("predict")
    bp.add_argument("--name", required=True)
    bp.add_argument("--scores", required=True)
    bp.add_argument("--label", required=True)
    bi = bench.add_parser("import")
    bi.add_argument("input")
    bi.add_argument("--name", required=True)
    bi.add_argument("--edsl", action="store_true")
    bi.add_argument("--source", choices=["human", "synthetic"], default="human")
    for name in ("report", "retire"):
        b = bench.add_parser(name)
        b.add_argument("--name", required=True)
    return p


def guide():
    return {
        "workflow": [
            "roth example create internship-demo",
            "roth --project internship-demo preferences import internship-demo/preferences.json",
            "roth --project internship-demo preferences freeze --name main",
            "roth --project internship-demo match --snapshot main --name main",
            "roth --project internship-demo report --run main --output internship-demo/report",
        ],
        "human_fielding": "field build → inspect preview and handoff.json → externally create Humanize survey → field register → authorize email delivery → externally retrieve Results → field import --edsl → preferences freeze",
        "delegated": "Organizer configure delegation → collect preference instructions → score plan → inspect jobs/cost → external ep run → score import → optional benchmark → score apply → optional confirmation field → preferences freeze → match",
        "benchmark": "benchmark build freezes baseline predictions → import calibration answers only → score plan --calibration → score import → benchmark predict --label revised → import held-out answers → benchmark report → score apply",
        "large_human": "field build --kind screening --batch-size 10 → import every batch → field build --kind ranking for one cross-batch order; use a score plan shortlist if necessary",
        "expansion": "score plan --expand previous --k LARGER --audit N; retained edges and cached evaluations are reused. Freeze a new snapshot and compare outcomes.",
        "defaults": {
            "capacity": 1,
            "proposing_side": "left",
            "delegation": "direct",
            "benchmark": "advisory",
            "unknown": "excluded edges, recorded as unknown",
            "ranking_budget": 15,
        },
        "execution": "Roth builds offline artifacts and ingests results. It does not send emails, publish surveys, or run paid inference. Handoff commands are argv arrays for explicit external execution.",
        "remaining_hosted_validation": "Pilot ranking presentation, participant binding, delivery retries, and response metadata on the configured Humanize service before recruitment.",
    }


def create_example(directory, students=12, internships=10, run=False):
    from .example import internship_example
    from .workflow import ingest_preferences, freeze, run_matching
    from .report import export_report

    require(students > 0 and internships > 0, "Example sizes must be positive")
    root = Path(directory)
    require(not root.exists(), "Example directory already exists")
    root.mkdir(parents=True)
    market, preferences = internship_example(students, internships)
    write_json(root / "market.json", market)
    write_json(root / "preferences.json", preferences)
    store = Store(root)
    with store.lock(create=True):
        state = store.load()
        state["market"] = market
        state["example_preferences"] = preferences
        if run:
            ingest_preferences(state, preferences)
            freeze(state, "main")
            run_matching(state, "main", "main")
        store.commit(state, "example.create", {"synthetic": True})
    result = {
        "project": str(root.resolve()),
        "students": students,
        "internships": internships,
        "synthetic": True,
    }
    if run:
        result.update(export_report(state, "main", root / "report"))
        from .fielding import build_field

        with store.lock():
            state = store.load()
            state.setdefault("exports", {})["main"] = {
                "report": result["report"],
                "directory": result["directory"],
            }
            result["surveys"] = build_field(
                state, "preview", root / "surveys", native=False
            )
            store.commit(state, "field.build", {"name": "preview"})
    return result


def dispatch(args, state):
    from .market import load_side, validate_market
    from .workflow import freeze, ingest_preferences, run_matching, status

    command, action = args.command, getattr(args, "action", None)
    if command == "init":
        require(state["market"] is None, "Market already initialized")
        require(
            bool(args.market) != bool(args.left or args.right),
            "Provide market JSON OR both --left and --right",
        )
        if args.market:
            raw = read_json(args.market)
        else:
            require(args.left and args.right, "Both --left and --right are required")
            raw = {
                "participants": load_side(args.left, "left")
                + load_side(args.right, "right")
            }
        state["market"] = validate_market(raw)
        return status(state), True
    require(state["market"] is not None, "Initialize a market first")
    if command == "configure":
        settings = read_json(args.config)
        require(isinstance(settings, dict), "Config must be an object")
        state["market"] = validate_market(
            {**state["market"], "config": {**state["market"]["config"], **settings}}
        )
        return {
            "config": state["market"]["config"],
            "note": "Existing snapshots are unchanged; rebuild field/scoring plans after policy changes.",
        }, True
    if command in {"status", "next"}:
        return status(state), False
    if command == "validate":
        from .matching import verify_matching
        from .market import participants, validate_preferences

        validate_market(state["market"])
        validate_preferences(state["market"], list(state["preferences"].values()))
        for snapshot in state["snapshots"].values():
            require(
                snapshot["hash"]
                == digest({k: v for k, v in snapshot.items() if k != "hash"}),
                "Snapshot hash mismatch",
            )
        for run in state["runs"].values():
            snapshot = state["snapshots"][run["snapshot"]]
            require(run["snapshot_hash"] == snapshot["hash"], "Run snapshot mismatch")
            people = participants(snapshot["market"])
            sides = {
                side: {
                    p: [c for c in r["ranking"] if c in snapshot["active"]]
                    for p, r in snapshot["preferences"].items()
                    if people[p]["side"] == side
                }
                for side in ("left", "right")
            }
            require(
                verify_matching(sides["left"], sides["right"], run["matches"])[
                    "stable"
                ],
                "Saved matching fails verification",
            )
        return {
            "valid": True,
            "snapshots": len(state["snapshots"]),
            "runs": len(state["runs"]),
            "history": "hash chain verified",
        }, False
    if command == "preferences":
        if action == "show":
            return state["preferences"], False
        if action == "import":
            return ingest_preferences(
                state,
                read_json(args.input),
                args.replace,
                {"input_hash": digest(read_json(args.input))},
            ), True
        if action == "freeze":
            return freeze(state, args.name, args.exclude), True
    if command == "match":
        return run_matching(
            state, args.snapshot, args.name, args.proposing_side, not args.no_compare
        ), True
    if command == "stats":
        from .analysis import preference_statistics

        if args.run:
            require(args.run in state["runs"], "Unknown run")
            return state["runs"][args.run]["statistics"], False
        return preference_statistics(state["market"], state["preferences"]), False
    if command == "report":
        from .report import export_report

        exported = export_report(state, args.run, args.output)
        state.setdefault("exports", {})[args.run] = exported
        return exported, True
    if command == "field":
        from .fielding import build_field, ingest_field, register_field

        if action == "build":
            return build_field(
                state,
                args.name,
                args.output or args.name,
                args.kind,
                args.plan,
                args.max_options,
                args.batch_size,
                not args.json_only,
                args.participant,
            ), True
        if action == "import":
            require(args.name in state["fields"], "Unknown field")
            if args.edsl:
                from .edsl_bridge import field_results

                rows = field_results(args.input, state["fields"][args.name]["packages"])
            else:
                rows = read_json(args.input)
            if state["fields"][args.name]["kind"] == "benchmark":
                from .benchmark import import_field_answers

                return import_field_answers(state, args.name, rows), True
            return ingest_field(state, args.name, rows, args.replace), True
        if action == "register":
            return register_field(
                state,
                args.field,
                args.package,
                args.uuid,
                args.delivery,
                read_json(args.status_json) if args.status_json else None,
            ), True
        if action == "status":
            require(args.name in state["fields"], "Unknown field")
            f = state["fields"][args.name]
            return {
                "name": args.name,
                "packages": len(f["packages"]),
                "responded": len(f["responses"]),
                "pending": sorted(set(f["packages"]) - set(f["responses"])),
                "registrations": {
                    p: state["registrations"][p]
                    for p in f["packages"]
                    if p in state["registrations"]
                },
            }, False
    if command == "score":
        from .delegation import build_plan, ingest_scores, apply_scores, score_status

        if action == "plan":
            return build_plan(
                state,
                args.name,
                args.output,
                args.model,
                args.k,
                args.budget,
                args.seed,
                args.expand,
                args.calibration,
                not args.json_only,
                args.audit,
                read_json(args.parameters) if args.parameters else None,
            ), True
        require(args.name in state["score_plans"], "Unknown score plan")
        if action == "import":
            if args.edsl:
                from .edsl_bridge import score_results

                rows = score_results(args.input, state["score_plans"][args.name])
            else:
                rows = read_json(args.input)
            return ingest_scores(state, args.name, rows, args.source), True
        if action == "apply":
            return apply_scores(state, args.name, args.replace), True
        if action == "status":
            return score_status(state, args.name), False
        if action == "retry":
            from .edsl_bridge import build_score_jobs

            plan = state["score_plans"][args.name]
            missing = set(score_status(state, args.name)["missing"])
            require(missing, "No missing scoring tasks")
            return build_score_jobs(
                args.output,
                [t for t in plan["tasks"] if t["task_id"] in missing],
                plan["id"],
            ), False
    if command == "benchmark":
        from .benchmark import (
            build_benchmark,
            freeze_predictions,
            import_answers,
            evaluate_benchmark,
            import_field_answers,
        )

        if action == "build":
            return build_benchmark(
                state,
                args.name,
                args.output,
                args.scores,
                args.pairs,
                args.seed,
                not args.json_only,
            ), True
        require(args.name in state["benchmarks"], "Unknown benchmark")
        if action == "predict":
            return freeze_predictions(state, args.name, args.scores, args.label), True
        if action == "import":
            if args.edsl:
                from .edsl_bridge import field_results

                return import_field_answers(
                    state,
                    args.name,
                    field_results(args.input, state["fields"][args.name]["packages"]),
                    args.source,
                ), True
            return import_answers(
                state, args.name, read_json(args.input), args.source
            ), True
        if action == "report":
            return evaluate_benchmark(state, args.name), False
        if action == "retire":
            state["benchmarks"][args.name]["retired"] = True
            return evaluate_benchmark(state, args.name), True
    if command == "example":
        require(
            state["market"].get("synthetic") and "example_preferences" in state,
            "Fixture generation requires the canned synthetic example",
        )
        fixtures = {r["participant_id"]: r for r in state["example_preferences"]}
        if action == "scores":
            require(args.name in state["score_plans"], "Unknown score plan")
            rows = []
            for t in state["score_plans"][args.name]["tasks"]:
                pref = fixtures[t["participant_id"]]
                c = t["candidate_id"]
                rows.append(
                    {
                        "task_id": t["task_id"],
                        "acceptability": "acceptable"
                        if c in pref["ranking"]
                        else "unacceptable",
                        "score": 100
                        * (1 - pref["ranking"].index(c) / max(1, len(pref["ranking"])))
                        if c in pref["ranking"]
                        else 0,
                        "evidence": ["Fictional fixture ranking; not model output"],
                        "explanation": "Deterministic synthetic demonstration",
                    }
                )
        else:
            require(args.name in state["benchmarks"], "Unknown benchmark")
            rows = []
            for q in state["benchmarks"][args.name]["questions"]:
                if args.split != "all" and q["split"] != args.split:
                    continue
                order = fixtures[q["participant_id"]]["ranking"]
                a, b = q["a"], q["b"]
                ar, br = (
                    order.index(a) if a in order else 999,
                    order.index(b) if b in order else 999,
                )
                rows.append(
                    {
                        "question_id": q["id"],
                        "choice": "Somewhat prefer A"
                        if ar < br
                        else "Somewhat prefer B"
                        if ar > br
                        else "Indifferent",
                        "a_acceptable": "Acceptable" if a in order else "Unacceptable",
                        "b_acceptable": "Acceptable" if b in order else "Unacceptable",
                        "explanation": "Fictional fixture choice",
                    }
                )
        return {
            "output": write_json(args.output, rows),
            "synthetic": True,
            "rows": len(rows),
        }, False
    raise RothError("Unknown command", "USAGE_ERROR")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = None
    try:
        args = parser().parse_args(argv)
        if args.command == "version":
            data = {"version": __version__, "schema_version": "1.0"}
        elif args.command == "capabilities":
            data = {
                "one_to_one": True,
                "many_to_one": False,
                "direct_surveys": True,
                "humanize_handoff": True,
                "delegated_scoring": True,
                "bidirectional_retrieval": "lexical",
                "pairwise_benchmark": True,
                "held_out_predictions": True,
                "core_network_required": False,
                "hosted_pilot_verified": False,
            }
        elif args.command == "guide":
            data = guide()
        elif args.command == "demo":
            data = create_example(args.directory, run=True)
        elif args.command == "example" and args.action == "create":
            data = create_example(args.directory, args.students, args.internships)
        else:
            store = Store(args.project)
            with store.lock(create=args.command == "init"):
                state = store.load()
                with redirect_stdout(io.StringIO()):
                    data, mutated = dispatch(args, state)
                if mutated:
                    store.commit(
                        state,
                        " ".join([args.command, getattr(args, "action", "")]),
                        {"argv": argv},
                    )
        next_steps = []
        if (
            isinstance(data, dict)
            and isinstance(data.get("next"), list)
            and data["next"]
        ):
            next_steps = [
                {
                    "argv": [
                        data["next"][0],
                        "--project",
                        str(Path(args.project).resolve()),
                        *data["next"][1:],
                    ],
                    "network": False,
                    "mutates": not (
                        "status" in data["next"] or "--help" in data["next"]
                    ),
                    "requires_authorization": False,
                }
            ]
        envelope = {
            "schema_version": "1.0",
            "status": "ok",
            "command": args.command,
            "argv": ["roth", *argv],
            "data": data,
            "warnings": [],
            "errors": [],
            "next_steps": next_steps,
        }
        print(
            json.dumps(
                data if args.human else envelope,
                indent=2 if args.human else None,
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        return 0
    except (RothError, OSError, ValueError, KeyError, TypeError) as error:
        envelope = {
            "schema_version": "1.0",
            "status": "error",
            "command": getattr(args, "command", None),
            "argv": ["roth", *argv],
            "data": {},
            "warnings": [],
            "errors": [
                {
                    "code": getattr(error, "code", "VALIDATION_ERROR"),
                    "message": str(error),
                }
            ],
            "next_steps": [],
        }
        print(json.dumps(envelope, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
