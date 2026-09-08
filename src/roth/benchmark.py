"""Pairwise calibration with predictions frozen before held-out answers arrive."""

from __future__ import annotations
from collections import defaultdict
import copy
from itertools import combinations
from pathlib import Path
import random

from .analysis import rate
from .common import digest, identifier, require, write_json
from .fielding import profile_text, write_field_artifacts
from .market import participants

CHOICES = [
    "Strongly prefer A",
    "Somewhat prefer A",
    "Indifferent",
    "Somewhat prefer B",
    "Strongly prefer B",
    "Insufficient information",
]
ACCEPTABILITY = ["Acceptable", "Unacceptable", "Insufficient information"]


def direction(choice):
    return (
        "A"
        if choice in CHOICES[:2]
        else "B"
        if choice in CHOICES[3:5]
        else "tie"
        if choice == "Indifferent"
        else "unknown"
    )


def directional_scores(state, name):
    from .delegation import score_bundle

    bundle = score_bundle(state, name)
    values = {
        (t["participant_id"], t["candidate_id"]): state["scores"][t["task_id"]]
        for t in state["score_plans"][name]["tasks"]
    }
    return bundle, values


def build_benchmark(state, name, output, scores, pairs=6, seed=17, native=True):
    identifier(name)
    require(
        name not in state["benchmarks"] and name not in state["fields"],
        "Benchmark name already exists",
    )
    require(
        pairs >= 2, "Need at least two pairs to separate calibration and evaluation"
    )
    bundle, values = directional_scores(state, scores)
    require(
        state["score_plans"][scores]["market_hash"] == digest(state["market"]),
        "Score plan is stale",
    )
    people = participants(state["market"])
    rng = random.Random(seed)
    questions, packages = [], {}
    for pid in sorted(people):
        candidates = sorted(c for p, c in values if p == pid)
        possible = list(combinations(candidates, 2))
        if len(possible) < 2:
            continue
        representative = rng.sample(possible, min((pairs + 1) // 2, len(possible) - 1))
        remaining = [p for p in possible if p not in representative]
        diagnostic = sorted(
            remaining,
            key=lambda edge: (
                abs(values[pid, edge[0]]["score"] - values[pid, edge[1]]["score"]),
                edge,
            ),
        )[: pairs - len(representative)]
        selected = [(pair, "representative") for pair in representative] + [
            (pair, "diagnostic") for pair in diagnostic
        ]
        rng.shuffle(selected)
        qdescriptors = []
        for i, ((a, b), selection) in enumerate(selected):
            if rng.random() < 0.5:
                a, b = b, a
            qid = f"{name}_{pid}_q{i + 1}"
            q = {
                "id": qid,
                "participant_id": pid,
                "a": a,
                "b": b,
                "selection": selection,
                "split": "calibration" if i % 2 == 0 else "evaluation",
            }
            questions.append(q)
            text = f"For {people[pid]['name']}, compare these options.\nA: {profile_text(people[a])}\n\nB: {profile_text(people[b])}"
            outside = "remain unmatched"
            if people[pid].get("capacity", 1) != 1:
                text += f"\nYour capacity is {people[pid]['capacity']}. Compare these individuals independently of your other partners, for an available slot."
                outside = "leave an additional slot empty"
            qdescriptors.extend(
                [
                    {
                        "kind": "multiple_choice",
                        "question_name": qid + "_choice",
                        "question_text": text,
                        "question_options": CHOICES,
                    },
                    {
                        "kind": "multiple_choice",
                        "question_name": qid + "_a",
                        "question_text": f"Would you accept option A rather than {outside}?",
                        "question_options": ACCEPTABILITY,
                    },
                    {
                        "kind": "multiple_choice",
                        "question_name": qid + "_b",
                        "question_text": f"Would you accept option B rather than {outside}?",
                        "question_options": ACCEPTABILITY,
                    },
                    {
                        "kind": "free_text",
                        "question_name": qid + "_why",
                        "question_text": "Explain the tradeoff, or enter 'No explanation'.",
                    },
                ]
            )
        # Separate calibration and evaluation invitations to allow intervening refinement.
        for split in ("calibration", "evaluation"):
            qids = [
                q["id"]
                for q in questions
                if q["participant_id"] == pid and q["split"] == split
            ]
            package_id = f"{name}_{pid}_{split}"
            packages[package_id] = {
                "id": package_id,
                "participant_id": pid,
                "questions": [
                    d
                    for d in qdescriptors
                    if any(d["question_name"].startswith(qid + "_") for qid in qids)
                ],
                "question_ids": qids,
                "split": split,
                "candidates": candidates,
            }
    require(questions, "Not enough scored candidates for a pairwise benchmark")
    benchmark = {
        "name": name,
        "market_hash": digest(state["market"]),
        "questions": questions,
        "answers": {},
        "predictions": {},
        "prediction_order": [],
        "seed": seed,
        "retired": False,
        "selection_score_hash": bundle["hash"],
        "source": "human",
    }
    state["benchmarks"][name] = benchmark
    freeze_predictions(state, name, scores, "baseline")
    field = {
        "name": name,
        "kind": "benchmark",
        "market_hash": digest(state["market"]),
        "packages": packages,
        "responses": {},
        "submissions": {},
        "output": str(Path(output).resolve()),
    }
    write_field_artifacts(field, people, output, native)
    write_json(
        Path(output) / "benchmark.json",
        {k: v for k, v in benchmark.items() if k != "predictions"},
    )
    write_json(
        Path(output) / "benchmark-answers-template.json",
        [
            {
                "question_id": q["id"],
                "choice": None,
                "a_acceptable": None,
                "b_acceptable": None,
                "explanation": "",
            }
            for q in questions
        ],
    )
    state["fields"][name] = field
    return {
        "name": name,
        "questions": len(questions),
        "participants": len({q["participant_id"] for q in questions}),
        "baseline_frozen": True,
        "output": field["output"],
    }


def freeze_predictions(state, name, scores, label):
    identifier(label)
    require(name in state["benchmarks"], "Unknown benchmark")
    benchmark = state["benchmarks"][name]
    require(not benchmark["retired"], "Benchmark has been retired")
    require(
        benchmark["market_hash"] == digest(state["market"]), "Benchmark market is stale"
    )
    require(label not in benchmark["predictions"], "Prediction label already exists")
    require(
        not any(
            q["split"] == "evaluation" and q["id"] in benchmark["answers"]
            for q in benchmark["questions"]
        ),
        "Held-out answers already revealed; create a fresh benchmark",
        "BENCHMARK_LEAKAGE",
    )
    bundle, scores_by_pair = directional_scores(state, scores)
    require(
        state["score_plans"][scores]["market_hash"] == benchmark["market_hash"],
        "Score plan is stale",
    )
    predictions = {}
    for q in benchmark["questions"]:
        pid, a, b = q["participant_id"], q["a"], q["b"]
        require(
            (pid, a) in scores_by_pair and (pid, b) in scores_by_pair,
            "Prediction scores omit a benchmark candidate",
        )
        av, bv = scores_by_pair[pid, a], scores_by_pair[pid, b]
        predictions[q["id"]] = {
            "direction": "A"
            if av["score"] > bv["score"]
            else "B"
            if av["score"] < bv["score"]
            else "tie",
            "a_acceptable": av["acceptability"],
            "b_acceptable": bv["acceptability"],
        }
    benchmark["predictions"][label] = {
        "scores": scores,
        "score_hash": bundle["hash"],
        "predictions": predictions,
    }
    benchmark.setdefault("prediction_order", []).append(label)
    return {
        "name": name,
        "label": label,
        "predictions_frozen": len(predictions),
        "score_hash": bundle["hash"],
    }


def import_answers(state, name, rows, source="human"):
    require(name in state["benchmarks"], "Unknown benchmark")
    benchmark = state["benchmarks"][name]
    require(
        benchmark["market_hash"] == digest(state["market"]), "Benchmark market is stale"
    )
    require(source in {"human", "synthetic"}, "Invalid benchmark source")
    require(
        source != "synthetic" or state["market"].get("synthetic"),
        "Synthetic benchmark requires synthetic market",
    )
    require(
        not benchmark["answers"] or benchmark["source"] == source,
        "Cannot mix synthetic and human benchmark answers",
    )
    questions = {q["id"]: q for q in benchmark["questions"]}
    seen, pending = set(), {}
    for row in rows:
        qid = row.get("question_id")
        require(
            qid in questions and qid not in seen,
            "Unknown or duplicate benchmark question",
        )
        seen.add(qid)
        require(row.get("choice") in CHOICES, "Invalid pairwise choice")
        require(
            row.get("a_acceptable") in ACCEPTABILITY
            and row.get("b_acceptable") in ACCEPTABILITY,
            "Missing separate acceptability answers",
        )
        require(isinstance(row.get("explanation", ""), str), "Explanation must be text")
        previous = benchmark["answers"].get(qid)
        require(
            previous is None or previous == row,
            "Answer already exists; preserve this benchmark and create a new round for revisions",
        )
        if questions[qid]["split"] == "evaluation":
            require(
                benchmark["predictions"],
                "Freeze predictions before importing evaluation answers",
            )
        pending[qid] = copy.deepcopy(row)
    benchmark["answers"].update(pending)
    benchmark["source"] = source
    return evaluate_benchmark(state, name)


def import_field_answers(state, name, submissions, source="human"):
    require(
        name in state["fields"] and state["fields"][name]["kind"] == "benchmark",
        "Not a benchmark field",
    )
    field = state["fields"][name]
    rows = []
    seen = set()
    for raw in submissions:
        package_id = raw.get("package_id")
        require(
            package_id in field["packages"] and package_id not in seen,
            "Unknown or duplicate benchmark package",
        )
        seen.add(package_id)
        package = field["packages"][package_id]
        require(
            raw.get("participant_id") == package["participant_id"],
            "Benchmark respondent mismatch",
        )
        answers = raw.get("answers", {})
        for qid in package["question_ids"]:
            rows.append(
                {
                    "question_id": qid,
                    "choice": answers.get(qid + "_choice"),
                    "a_acceptable": answers.get(qid + "_a"),
                    "b_acceptable": answers.get(qid + "_b"),
                    "explanation": answers.get(qid + "_why", ""),
                }
            )
    report = import_answers(state, name, rows, source)
    for raw in submissions:
        field["responses"][raw["package_id"]] = copy.deepcopy(raw)
    return report


def evaluate_benchmark(state, name):
    benchmark = state["benchmarks"][name]
    report = {
        "name": name,
        "source": benchmark["source"],
        "retired": benchmark["retired"],
        "models": {},
    }
    for label, prediction in benchmark["predictions"].items():
        groups = defaultdict(list)
        for q in benchmark["questions"]:
            if q["split"] == "evaluation" and q["id"] in benchmark["answers"]:
                answer = benchmark["answers"][q["id"]]
                predicted = prediction["predictions"][q["id"]]
                d = direction(answer["choice"])
                errors, assessed = 0, 0
                for key in ("a_acceptable", "b_acceptable"):
                    if answer[key] != "Insufficient information":
                        assessed += 1
                        errors += predicted[key] != answer[key].lower()
                groups[q["participant_id"]].append(
                    {
                        "selection": q["selection"],
                        "correct": d == predicted["direction"],
                        "direction": d,
                        "acceptability_errors": errors,
                        "acceptability_assessed": assessed,
                    }
                )
        participants_report = {}
        for pid in sorted({q["participant_id"] for q in benchmark["questions"]}):
            values = groups[pid]
            valid = [v for v in values if v["direction"] != "unknown"]
            participants_report[pid] = {
                "overall": rate(sum(v["correct"] for v in valid), len(valid)),
                "ties": sum(v["direction"] == "tie" for v in values),
                "insufficient_information": sum(
                    v["direction"] == "unknown" for v in values
                ),
                "acceptability_errors": rate(
                    sum(v["acceptability_errors"] for v in values),
                    sum(v["acceptability_assessed"] for v in values),
                ),
                "by_selection": {
                    selection: rate(
                        sum(v["correct"] for v in valid if v["selection"] == selection),
                        sum(v["selection"] == selection for v in valid),
                    )
                    for selection in ("representative", "diagnostic")
                },
            }
        report["models"][label] = {
            "score_hash": prediction["score_hash"],
            "participants": participants_report,
        }
    if report["models"]:
        latest = benchmark.get("prediction_order", list(report["models"]))[-1]
        report["participants"] = report["models"][latest]["participants"]
        benchmark["evaluation_score_hash"] = report["models"][latest]["score_hash"]
    report["note"] = (
        "Held-out directional agreement only; targeted questions and a small sample do not certify full preferences or retrieval coverage."
    )
    benchmark["report"] = report
    return report


def preference_evidence_hash(state, pid):
    market_hash = digest(state["market"])
    evidence = []
    for name, benchmark in sorted(state["benchmarks"].items()):
        if benchmark["market_hash"] != market_hash:
            continue
        for question in benchmark["questions"]:
            if (
                question["participant_id"] == pid
                and question["id"] in benchmark["answers"]
            ):
                evidence.append(
                    {
                        "benchmark": name,
                        "question": question,
                        "answer": benchmark["answers"][question["id"]],
                    }
                )
    return digest(evidence)


def constrain_ranking(state, pid, ranking, rejected):
    edges, human_accept, human_reject = set(), set(), set()
    for benchmark in state["benchmarks"].values():
        if benchmark["market_hash"] != digest(state["market"]):
            continue
        for q in benchmark["questions"]:
            if q["participant_id"] != pid or q["id"] not in benchmark["answers"]:
                continue
            answer = benchmark["answers"][q["id"]]
            a, b = q["a"], q["b"]
            for c, key in ((a, "a_acceptable"), (b, "b_acceptable")):
                if answer[key] == "Acceptable":
                    human_accept.add(c)
                elif answer[key] == "Unacceptable":
                    human_reject.add(c)
            d = direction(answer["choice"])
            if d == "A":
                edges.add((a, b))
            if d == "B":
                edges.add((b, a))
    require(
        not human_accept & human_reject,
        f"Conflicting human acceptability answers for {pid}; resolve in a new benchmark round",
    )

    # Detect cycles even when an involved candidate would not be matched.
    def topological(nodes, constraints, priority):
        outgoing, indegree = defaultdict(set), dict.fromkeys(nodes, 0)
        for a, b in constraints:
            if a in nodes and b in nodes and b not in outgoing[a]:
                outgoing[a].add(b)
                indegree[b] += 1
        result = []
        while len(result) < len(nodes):
            available = [c for c in nodes if indegree[c] == 0 and c not in result]
            require(
                available,
                f"Conflicting pairwise cycle for {pid}; human clarification required",
            )
            c = min(available, key=lambda x: (priority.get(x, len(priority)), x))
            result.append(c)
            for target in outgoing[c]:
                indegree[target] -= 1
        return result

    all_nodes = {c for edge in edges for c in edge}
    topological(all_nodes, edges, {})
    rejected = (set(rejected) - human_accept) | human_reject
    nodes = (set(ranking) | human_accept) - rejected
    require(
        not any(a in human_reject and b in human_accept for a, b in edges),
        f"Relative preference conflicts with acceptability for {pid}",
    )
    return topological(nodes, edges, {c: i for i, c in enumerate(ranking)}), rejected
