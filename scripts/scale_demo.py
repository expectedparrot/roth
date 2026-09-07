"""Measure candidate-expansion work using explicit fictional preferences only."""

import json
from pathlib import Path
import tempfile
import time
import argparse

from roth.common import write_json
from roth.delegation import build_plan, ingest_scores, apply_scores
from roth.example import internship_example
from roth.matching import deferred_acceptance, verify_matching
from roth.storage import empty_state
from roth.workflow import freeze, run_matching


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="examples/scale-summary.json")
    args = parser.parse_args()
    market, preferences = internship_example(200, 150)
    state = empty_state()
    state["market"] = market
    fixtures = {r["participant_id"]: r for r in preferences}
    left = {p: r["ranking"] for p, r in fixtures.items() if p.startswith("s")}
    right = {p: r["ranking"] for p, r in fixtures.items() if p.startswith("i")}
    exhaustive = deferred_acceptance(left, right)
    summary = {
        "synthetic": True,
        "students": 200,
        "internships": 150,
        "exhaustive_directed_evaluations": 60000,
        "full_fixture_matches": len(exhaustive["matches"]),
        "rounds": [],
    }
    with tempfile.TemporaryDirectory(prefix="roth-scale-") as temp:
        for k, previous in ((5, None), (10, "k5")):
            start = time.perf_counter()
            name = f"k{k}"
            plan_summary = build_plan(
                state,
                name,
                Path(temp) / name,
                "test",
                k=k,
                budget=7000,
                expand=previous,
                native=False,
            )
            plan = state["score_plans"][name]
            rows = []
            for task in plan["tasks"]:
                if task["task_id"] in state["scores"]:
                    continue
                pref, c = fixtures[task["participant_id"]], task["candidate_id"]
                rank = pref["ranking"]
                rows.append(
                    {
                        "task_id": task["task_id"],
                        "acceptability": "acceptable" if c in rank else "unacceptable",
                        "score": 100 * (1 - rank.index(c) / len(rank))
                        if c in rank
                        else 0,
                        "evidence": ["Synthetic full-ranking fixture"],
                        "explanation": "No model inference",
                    }
                )
            ingest_scores(state, name, rows, source="synthetic")
            apply_scores(state, name, replace=bool(previous))
            freeze(state, name)
            run = run_matching(state, name, name)
            full_check = verify_matching(left, right, run["matches"])
            summary["rounds"].append(
                {
                    "k": k,
                    "directed_evaluations": plan_summary["directed_evaluations"],
                    "new_evaluations": len(rows),
                    "cached": plan_summary["cached"],
                    "matches": len(run["matches"]),
                    "stable_on_retrieved_graph": run["verification"]["stable"],
                    "blocking_pairs_under_full_fixture": len(
                        full_check["blocking_pairs"]
                    ),
                    "elapsed_seconds": round(time.perf_counter() - start, 3),
                }
            )
    summary["interpretation"] = (
        "Retrieval cuts synthetic evaluation counts. Stability on the retrieved graph does not establish full-market stability; expansion need not eliminate all omitted blocking pairs. Times measure local fixture processing, not LLM latency."
    )
    path = write_json(args.output, summary)
    print(json.dumps({"output": path, **summary}, indent=2))


if __name__ == "__main__":
    main()
