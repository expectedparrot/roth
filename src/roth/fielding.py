"""Personalized, immutable human fielding packages and strict answer ingestion."""

from __future__ import annotations
import copy
import html
import json
from pathlib import Path
import random

from .common import digest, identifier, require, write_json
from .market import eligible, participants, policy
from .workflow import ingest_preferences

OUTSIDE = "Remain unmatched"
UNKNOWN = "Insufficient information"
ACCEPT = "Acceptable"
REJECT = "Unacceptable"


def profile_text(person):
    return f"{person['name']} [{person['id']}]\n" + json.dumps(
        person.get("profile", {}), ensure_ascii=False, indent=2
    )


def screen_decisions(state, pid):
    if pid in state.get("screening", {}):
        return dict(state["screening"][pid])
    decisions = {}
    for field in state["fields"].values():
        if field["kind"] == "screening":
            for package_id, submission in field.get("responses", {}).items():
                package = field["packages"][package_id]
                if package["participant_id"] == pid:
                    decisions.update(submission["decisions"])
    return decisions


def instruction_context(market):
    context = copy.deepcopy(market)
    for p in context["participants"]:
        p.pop("preferences", None)
    return digest(context)


def build_field(
    state,
    name,
    output,
    kind="ranking",
    plan_name=None,
    max_options=15,
    batch_size=10,
    native=True,
    only=None,
):
    identifier(name)
    require(name not in state["fields"], "Field name already exists")
    require(max_options > 0 and batch_size > 0, "Survey budgets must be positive")
    market = state["market"]
    require(market is not None, "Import a market first")
    people, graph = participants(market), eligible(market)
    ids = sorted(only or people)
    require(set(ids) <= set(people), "Unknown participant")
    if plan_name:
        require(plan_name in state["score_plans"], "Unknown shortlist plan")
        plan = state["score_plans"][plan_name]
        require(
            plan["market_hash"] == digest(market),
            "Shortlist plan belongs to an older market",
        )
        graph = {p: set() for p in people}
        for a, b in plan["edges"]:
            graph[a].add(b)
            graph[b].add(a)
    packages = {}
    for pid in ids:
        candidates = sorted(graph[pid])
        screened = screen_decisions(state, pid)
        if kind == "ranking" and screened:
            candidates = [c for c in candidates if screened.get(c) == ACCEPT]
        if kind == "confirmation":
            require(
                pid in state["preferences"]
                and state["preferences"][pid]["source"] == "delegated",
                f"No delegated ranking to confirm for {pid}",
            )
            candidates = state["preferences"][pid]["ranking"]
        if kind in {"ranking", "confirmation"}:
            require(
                len(candidates) <= max_options,
                f"{pid} has {len(candidates)} candidates, over budget {max_options}; screen in batches, use --plan, or raise --max-options explicitly",
            )
        chunks = (
            [
                candidates[i : i + batch_size]
                for i in range(0, len(candidates), batch_size)
            ]
            if kind == "screening"
            else [candidates]
        )
        for batch, chunk in enumerate(chunks):
            package_id = f"{name}_{pid}_{batch + 1}"
            questions = []
            header = f"Preference survey for {people[pid]['name']}. Organizer policy: {policy(market, pid)}.\n"
            if people[pid].get("capacity", 1) != 1:
                header += f"You may receive up to {people[pid]['capacity']} partners. Rank individuals independently of your other partners, and include all acceptable candidates, not just your top few. 'Remain unmatched' marks the cutoff for leaving an additional slot empty.\n"
            if kind == "instructions":
                questions.append(
                    {
                        "kind": "free_text",
                        "question_name": "preferences",
                        "question_text": header
                        + "Describe what you seek, your tradeoffs, dealbreakers, and when you prefer remaining unmatched.",
                    }
                )
            elif kind == "confirmation":
                text = "\n\n".join(
                    f"{i + 1}. {profile_text(people[c])}" for i, c in enumerate(chunk)
                )
                questions.append(
                    {
                        "kind": "multiple_choice",
                        "question_name": "confirm",
                        "question_text": header
                        + "Confirm this acceptable ranking, best first. Candidates omitted from this list will not be matched to you.\n"
                        + text,
                        "question_options": ["Confirm", "Request revision"],
                    }
                )
            elif kind == "screening":
                for i, c in enumerate(chunk):
                    questions.append(
                        {
                            "kind": "multiple_choice",
                            "question_name": f"accept_{i}",
                            "question_text": header
                            + profile_text(people[c])
                            + "\nWould you accept this partner rather than remain unmatched?",
                            "question_options": [ACCEPT, REJECT, UNKNOWN],
                            "mapping": {"candidate": c},
                        }
                    )
            elif chunk:
                rng = random.Random(digest([name, pid]))
                shown = list(chunk)
                rng.shuffle(shown)
                labels = {f"{people[c]['name']} [{c}]": c for c in shown}
                text = header + "\n\n".join(profile_text(people[c]) for c in shown)
                text += "\nRank ALL options best first. Place 'Remain unmatched' above every unacceptable partner. For candidates with insufficient information, select that status below; their position will be ignored."
                questions.append(
                    {
                        "kind": "rank",
                        "question_name": "ranking",
                        "question_text": text,
                        "question_options": list(labels) + [OUTSIDE],
                        "num_selections": len(labels) + 1,
                        "use_code": True,
                        "mapping": labels,
                    }
                )
                for i, c in enumerate(shown):
                    questions.append(
                        {
                            "kind": "multiple_choice",
                            "question_name": f"known_{i}",
                            "question_text": f"Could you assess {people[c]['name']} [{c}]?",
                            "question_options": ["Assessed", UNKNOWN],
                            "mapping": {"candidate": c},
                        }
                    )
            else:
                questions.append(
                    {
                        "kind": "multiple_choice",
                        "question_name": "empty",
                        "question_text": header
                        + "There are no candidates in this ranking round. Submit an empty acceptable list?",
                        "question_options": [
                            "Submit empty list",
                            "Request more candidates",
                        ],
                    }
                )
            packages[package_id] = {
                "id": package_id,
                "participant_id": pid,
                "candidates": chunk,
                "questions": questions,
                "screened": screened,
                "preference_hash": digest(state["preferences"].get(pid)),
                "source": "human",
                "complete": False,
            }
    field = {
        "name": name,
        "kind": kind,
        "market_hash": digest(market),
        "packages": packages,
        "responses": {},
        "submissions": {},
        "instruction_context": instruction_context(market),
        "candidate_scope": "shortlist" if plan_name else "eligible_market",
        "output": str(Path(output).resolve()),
    }
    write_field_artifacts(field, people, output, native)
    state["fields"][name] = field
    return {
        "name": name,
        "packages": len(packages),
        "output": field["output"],
        "native": native,
        "questions": sum(len(p["questions"]) for p in packages.values()),
        "network_executed": False,
    }


def write_field_artifacts(field, people, output, native, register_command=None):
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    handoffs, previews = [], []
    for package_id, package in field["packages"].items():
        folder = directory / package_id
        person = people[package["participant_id"]]
        if native:
            from .edsl_bridge import build_survey_package

            build_survey_package(folder, package["questions"], person, package_id)
        else:
            folder.mkdir()
        write_json(folder / "question-map.json", package)
        args = [
            "ep",
            "humanize",
            "create",
            "--jobs",
            str((folder / "jobs.ep").resolve()),
            "--schema",
            str((folder / "humanize-schema.json").resolve()),
            "--name",
            package_id,
        ]
        if person.get("contact", {}).get("email"):
            args += ["--delivery_map", str((folder / "delivery-map.json").resolve())]
        handoffs.append(
            {
                "package_id": package_id,
                "native_built": native,
                "create": args,
                "register": (
                    register_command
                    or [
                        "roth",
                        "field",
                        "register",
                        "--field",
                        field["name"],
                    ]
                )
                + [
                    "--package",
                    package_id,
                    "--uuid",
                    "<human-survey-uuid>",
                ],
                "recipient_configured": bool(person.get("contact", {}).get("email")),
                "mutates": True,
                "network": True,
                "requires_authorization": True,
            }
        )
        previews.append(f"<h2>{html.escape(person['name'])}</h2>")
        for q in package["questions"]:
            previews.append(f"<pre>{html.escape(q['question_text'])}</pre>")
            if "question_options" in q:
                previews.append(
                    "<ol>"
                    + "".join(
                        f"<li>{html.escape(str(o))}</li>" for o in q["question_options"]
                    )
                    + "</ol>"
                )
    write_json(directory / "manifest.json", field)
    write_json(directory / "handoff.json", handoffs)
    write_json(
        directory / "responses-template.json",
        [
            {
                "package_id": p["id"],
                "participant_id": p["participant_id"],
                "submission_id": "replace-with-stable-submission-id",
                "answers": {q["question_name"]: None for q in p["questions"]},
            }
            for p in field["packages"].values()
        ],
    )
    (directory / "preview.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Roth survey preview</title><style>body{max-width:850px;margin:40px auto;padding:20px;font:17px system-ui}pre{white-space:pre-wrap;background:#f0f5f4;padding:18px}h2{border-top:2px solid #386;padding-top:25px}</style><h1>Survey preview</h1><p>Static instrument preview; hosted presentation requires a Humanize pilot.</p>'
        + "".join(previews)
        + "</html>"
    )


def ingest_field(state, name, submissions, replace=False):
    require(name in state["fields"], "Unknown field")
    field = state["fields"][name]
    require(
        (
            field["kind"] == "instructions"
            and field.get("instruction_context") == instruction_context(state["market"])
        )
        or field["market_hash"] == digest(state["market"]),
        "Field belongs to an older market; build a new round",
    )
    require(isinstance(submissions, list), "Submissions must be a list")
    seen, changes = set(), []
    # Validate the entire import before any in-memory mutation.
    for raw in submissions:
        package_id = raw.get("package_id")
        require(
            package_id in field["packages"] and package_id not in seen,
            "Unknown or duplicate package in import",
        )
        seen.add(package_id)
        package = field["packages"][package_id]
        require(
            raw.get("participant_id") == package["participant_id"],
            "Wrong respondent for package",
        )
        require(
            isinstance(raw.get("submission_id"), str) and raw["submission_id"],
            "Missing stable submission_id",
        )
        token = f"{package_id}:{raw['submission_id']}"
        previous = field["submissions"].get(token)
        if previous:
            require(previous == raw, "Same submission ID has conflicting content")
            continue
        require(
            package_id not in field["responses"] or replace,
            "Response exists; use --replace for explicit revision",
        )
        answers = raw.get("answers")
        require(isinstance(answers, dict), "answers must be an object")
        for question in package["questions"]:
            key = question["question_name"]
            require(
                key in answers and answers[key] is not None, f"Missing answer {key}"
            )
            if question["kind"] == "multiple_choice":
                require(
                    answers[key] in question["question_options"],
                    f"Invalid answer for {key}",
                )
            elif question["kind"] == "rank":
                require(
                    isinstance(answers[key], list)
                    and len(answers[key]) == len(question["question_options"])
                    and set(answers[key]) == set(question["question_options"]),
                    "Ranking must contain every displayed option exactly once",
                )
            elif question["kind"] == "free_text":
                require(
                    isinstance(answers[key], str) and answers[key].strip(),
                    "Empty preference instructions",
                )
        changes.append((token, raw, package))
    result = {"imported": 0, "preferences_updated": 0}
    for token, raw, package in changes:
        answers, pid = raw["answers"], package["participant_id"]
        record = {"raw": raw}
        if field["kind"] == "screening":
            record["decisions"] = {
                q["mapping"]["candidate"]: answers[q["question_name"]]
                for q in package["questions"]
            }
            state.setdefault("screening", {}).setdefault(pid, {}).update(
                record["decisions"]
            )
        elif field["kind"] == "instructions":
            # Updating the market invalidates other prepared packages; defer all changes until end.
            record["instructions"] = answers["preferences"]
        elif field["kind"] == "confirmation":
            require(
                digest(state["preferences"].get(pid)) == package["preference_hash"],
                "Preferences changed since confirmation was prepared",
            )
            if answers["confirm"] == "Confirm":
                row = {**state["preferences"][pid], "confirmed": True}
                ingest_preferences(
                    state,
                    [row],
                    replace=True,
                    origin={"field": name, "submission": token},
                )
                result["preferences_updated"] += 1
        elif field["kind"] == "ranking":
            if answers.get("empty") == "Request more candidates":
                record["needs_expansion"] = True
            else:
                unknown = {
                    q["mapping"]["candidate"]
                    for q in package["questions"]
                    if q["question_name"].startswith("known_")
                    and answers[q["question_name"]] == UNKNOWN
                }
                rankq = next(
                    (q for q in package["questions"] if q["kind"] == "rank"), None
                )
                ranking, rejected = (
                    [],
                    [
                        c
                        for c, status in package["screened"].items()
                        if status == REJECT
                    ],
                )
                if rankq:
                    order = answers["ranking"]
                    cut = order.index(OUTSIDE)
                    ranking = [
                        rankq["mapping"][c]
                        for c in order[:cut]
                        if rankq["mapping"][c] not in unknown
                    ]
                    rejected += [
                        rankq["mapping"][c]
                        for c in order[cut + 1 :]
                        if rankq["mapping"][c] not in unknown
                    ]
                row = {
                    "participant_id": pid,
                    "ranking": ranking,
                    "unacceptable": sorted(set(rejected)),
                    "evaluated": sorted(
                        set(package["candidates"]) | set(package["screened"])
                    ),
                    "source": "human",
                    "complete": True,
                    "confirmed": True,
                }
                ingest_preferences(
                    state,
                    [row],
                    replace=replace,
                    origin={"field": name, "submission": token},
                )
                result["preferences_updated"] += 1
        field["responses"][package["id"]] = record
        field["submissions"][token] = copy.deepcopy(raw)
        result["imported"] += 1
    if field["kind"] == "instructions" and changes:
        people = participants(state["market"])
        for _, raw, package in changes:
            people[package["participant_id"]]["preferences"] = raw["answers"][
                "preferences"
            ]
    return result


def register_field(state, name, package_id, uuid, delivery=None, status_data=None):
    from uuid import UUID

    UUID(uuid)
    require(
        name in state["fields"] and package_id in state["fields"][name]["packages"],
        "Unknown field package",
    )
    require(
        all(
            r["uuid"] != uuid or k == package_id
            for k, r in state["registrations"].items()
        ),
        "Survey UUID already belongs to another package",
    )
    existing = state["registrations"].get(package_id)
    require(
        not existing or existing["uuid"] == uuid,
        "Package already registered with a different survey",
    )
    record = copy.deepcopy(
        existing
        or {"uuid": uuid, "field": name, "deliveries": [], "status_history": []}
    )
    if delivery:
        UUID(delivery)
        if delivery not in record["deliveries"]:
            record["deliveries"].append(delivery)
    if status_data is not None:
        record["status_history"].append(status_data)
    state["registrations"][package_id] = record
    folder = Path(state["fields"][name]["output"]) / package_id
    return {
        **record,
        "next_steps": {
            "status": ["ep", "humanize", "status", uuid],
            "deliveries": ["ep", "humanize", "deliveries", "list", uuid],
            "invite": [
                "ep",
                "humanize",
                "deliveries",
                "create",
                uuid,
                "--name",
                f"{package_id}-invitation",
                "--routes",
                str(folder / "invitation-routes.json"),
            ],
            "responses": [
                "ep",
                "humanize",
                "responses",
                uuid,
                "--output",
                str(folder / "results.ep"),
            ],
        },
        "invitation_note": "Inspect registered deliveries before retrying; invitation route selects never-contacted respondents. Sending requires organizer authorization.",
    }
