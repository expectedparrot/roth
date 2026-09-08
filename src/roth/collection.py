"""Durable human collection for file-based team and review optimization.

All external Humanize actions are handoffs. Questionnaire artifacts and response
history are append-only; completion and ranking validity are derived from saved
answers, not from the existence of a preference file.
"""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4, UUID

from .common import digest, require, write_json
from .storage import Store

RANK = "Include in my ranking"
NEUTRAL = "No preference / insufficient information"
EXCLUDE = "Exclude (hard constraint)"


def validate_market(mode, market):
    if mode == "teams":
        from .teams import validate_team_market

        return validate_team_market(market)
    from .reviews import validate_review_market

    result = validate_review_market(market)
    require(
        result["config"]["scoring"] != "none",
        "scoring=none has no human preferences to collect",
    )
    return result


def domains(mode, market):
    """Return public option descriptions only; never serialize contact/author data."""
    if mode == "teams":
        people = market["students"]
        return people, {
            p["id"]: {
                "projects": market["projects"],
                "teammates": [q for q in people if q["id"] != p["id"]],
            }
            for p in people
        }
    from .reviews import exclusion_reasons

    blocked = exclusion_reasons(market)
    people = market["reviewers"]
    return people, {
        p["id"]: {
            "submissions": [
                s for s in market["submissions"] if (p["id"], s["id"]) not in blocked
            ]
        }
        for p in people
    }


def public_option(person):
    text = f"{person.get('name', person.get('title'))} [{person['id']}]"
    if person.get("description"):
        text += f"\n{person['description']}"
    return text


def load_collection(directory, mode=None):
    store = Store(directory)
    state = store.load()
    require("collection" in state, "No saved collection in this directory")
    col = state["collection"]
    require(
        mode is None or col["mode"] == mode, "Collection belongs to a different mode"
    )
    return store, state, col


def build_collection(
    mode, raw_market, output, contacts=None, batch_size=10, max_options=15, native=True
):
    market = validate_market(mode, raw_market)
    require(
        type(batch_size) is int
        and batch_size > 0
        and type(max_options) is int
        and max_options > 0,
        "Survey budgets must be positive integers",
    )
    people, options = domains(mode, market)
    contacts = {} if contacts is None else contacts
    require(
        isinstance(contacts, dict) and set(contacts) <= {p["id"] for p in people},
        "Contacts must map known respondent IDs to contact objects",
    )
    for pid, contact in contacts.items():
        require(
            isinstance(contact, dict) and not set(contact) - {"email", "respondent_id"},
            f"Invalid contact for {pid}",
        )
        email = contact.get("email")
        require(
            email is None
            or (
                isinstance(email, str)
                and email.count("@") == 1
                and all(email.split("@"))
                and not any(c.isspace() for c in email)
                and not any(c in email for c in ",;<>")
            ),
            f"Invalid email for {pid}",
        )
    root = Path(output).resolve()
    require(not root.exists(), "Collection directory already exists")
    if native:
        from .edsl_bridge import edsl_module

        edsl_module()  # fail before creating files if the optional dependency is absent
    people = {
        p["id"]: {
            "id": p["id"],
            "name": p["name"],
            "contact": deepcopy(contacts.get(p["id"], {})),
        }
        for p in people
    }
    col = {
        "mode": mode,
        "market": market,
        "market_hash": digest(market),
        "people": people,
        "options": options,
        "native": native,
        "max_options": max_options,
        "batch_size": batch_size,
        "nonce": uuid4().hex[:12],
        "packages": {},
        "responses": {},
        "submissions": {},
        "registrations": {},
        "exports": [],
        "rounds": [],
    }
    packages = {}
    scores = mode == "reviews" and market["config"]["scoring"] == "scores"
    for pid, ds in options.items():
        for domain, candidates in ds.items():
            chunks = [
                candidates[i : i + batch_size]
                for i in range(0, len(candidates), batch_size)
            ] or [[]]
            for b, chunk in enumerate(chunks):
                package_id = f"c{col['nonce']}_a_{digest([pid, domain, b])[:16]}"
                header = f"For {people[pid]['name']}: assess {domain}. No preference or insufficient information gives zero score and remains assignable. Exclude means a hard constraint; use it only when this option must not be assigned. "
                if mode == "teams" and domain == "teammates":
                    header += (
                        "An exclusion from either person prevents them sharing a team. "
                    )
                if scores:
                    header += "Rate suitability/expertise from 0 (lowest) to 100 (highest) in increments of 10. A score of 0 is assignable; it is not an exclusion. "
                else:
                    header += "Select options you want to rank. In the next step, rank the selected options together across all batches. "
                questions = [
                    {
                        "kind": "multiple_choice",
                        "question_name": f"assess_{i}",
                        "question_text": header + "\n" + public_option(c),
                        "question_options": (
                            [str(i) for i in range(0, 101, 10)] if scores else [RANK]
                        )
                        + [NEUTRAL, EXCLUDE],
                        "mapping": {"candidate": c["id"]},
                    }
                    for i, c in enumerate(chunk)
                ]
                if not questions:
                    questions = [
                        {
                            "kind": "multiple_choice",
                            "question_name": "empty",
                            "question_text": header
                            + "There are no eligible options in this section. Confirm completion.",
                            "question_options": ["Confirm empty section"],
                        }
                    ]
                packages[package_id] = {
                    "id": package_id,
                    "participant_id": pid,
                    "domain": domain,
                    "stage": "assessment",
                    "questions": questions,
                    "candidates": [c["id"] for c in chunk],
                }
    root.mkdir(parents=True)
    write_json(root / "market.json", market)
    write_json(root / "submitted-market.json", raw_market)
    _write_round(col, root, packages, "assessment")
    store = Store(root)
    with store.lock(create=True):
        state = store.load()
        state["collection"] = col
        store.commit(
            state, "collection.build", {"mode": mode, "market_hash": col["market_hash"]}
        )
    return collection_status(root)


def _write_round(col, root, packages, name):
    from .fielding import write_field_artifacts

    folder = root / name
    field = {
        "name": name,
        "kind": "optimization_collection",
        "mode": col["mode"],
        "market_hash": col["market_hash"],
        "packages": packages,
        "output": str(folder),
    }
    write_field_artifacts(
        field,
        col["people"],
        folder,
        col["native"],
        register_command=["roth", col["mode"], "field", "register", str(root)],
    )
    for p in packages.values():
        p["folder"] = str(folder / p["id"])
    col["packages"].update(packages)
    col["rounds"].append(
        {
            "name": name,
            "preview": str(folder / "preview.html"),
            "handoff": str(folder / "handoff.json"),
            "packages": list(packages),
        }
    )


def assessment(col):
    decisions = {pid: {d: {} for d in ds} for pid, ds in col["options"].items()}
    missing = []
    active = {}
    for key, p in col["packages"].items():
        if p["stage"] != "assessment":
            continue
        row = col["responses"].get(key)
        if row is None:
            missing.append(key)
            continue
        active[key] = row
        for q in p["questions"]:
            if "mapping" in q:
                decisions[p["participant_id"]][p["domain"]][
                    q["mapping"]["candidate"]
                ] = row["answers"][q["question_name"]]
    return decisions, missing, digest(active)


def derive_preferences(col):
    decisions, missing, context = assessment(col)
    required = []
    rank_packages = {}
    for p in col["packages"].values():
        if p["stage"] == "ranking" and p["assessment_hash"] == context:
            rank_packages[p["participant_id"], p["domain"]] = p
    scores = col["mode"] == "reviews" and col["market"]["config"]["scoring"] == "scores"
    rows = []
    for pid, ds in decisions.items():
        row = {
            "student_id" if col["mode"] == "teams" else "reviewer_id": pid,
            "complete": True,
        }
        sources = [
            r["source"]
            for key, r in col["responses"].items()
            if col["packages"][key]["participant_id"] == pid
            and (
                col["packages"][key]["stage"] == "assessment"
                or col["packages"][key].get("assessment_hash") == context
            )
        ]
        row["source"] = "synthetic" if "synthetic" in sources else "human"
        for domain, values in ds.items():
            rejected = sorted(c for c, v in values.items() if v == EXCLUDE)
            if col["mode"] == "teams":
                row[
                    "unacceptable_projects"
                    if domain == "projects"
                    else "incompatible_teammates"
                ] = rejected
            else:
                row["unacceptable"] = rejected
            if scores:
                row["scores"] = {
                    c: float(v)
                    for c, v in values.items()
                    if v not in (NEUTRAL, EXCLUDE)
                }
                continue
            selected = sorted(c for c, v in values.items() if v == RANK)
            order = selected
            if len(selected) > 1:
                package = rank_packages.get((pid, domain))
                response = col["responses"].get(package["id"]) if package else None
                if response is None:
                    required.append(
                        {
                            "participant_id": pid,
                            "domain": domain,
                            "selected": selected,
                            "package_id": package["id"] if package else None,
                        }
                    )
                else:
                    q = package["questions"][0]
                    order = [
                        q["mapping"][label] for label in response["answers"]["ranking"]
                    ]
            row[domain if col["mode"] == "teams" else "ranking"] = order
        rows.append(row)
    order = [
        p["id"]
        for p in col["market"]["students" if col["mode"] == "teams" else "reviewers"]
    ]
    rows.sort(key=lambda r: order.index(r.get("student_id", r.get("reviewer_id"))))
    return rows, missing, required, context


def collection_status(directory, mode=None):
    _, _, col = load_collection(directory, mode)
    rows, missing, rankings, context = derive_preferences(col)
    missing_people = sorted(
        {col["packages"][p]["participant_id"] for p in missing}
        | {r["participant_id"] for r in rankings}
    )
    return {
        "mode": col["mode"],
        "market_hash": col["market_hash"],
        "field_dir": str(Path(directory).resolve()),
        "complete": not missing and not rankings,
        "participants": len(col["people"]),
        "completed_participants": len(col["people"]) - len(missing_people),
        "missing_participants": missing_people,
        "missing_assessment_packages": missing,
        "ranking_needed": rankings if not missing else [],
        "assessment_hash": context,
        "native": col["native"],
        "missing_email_contacts": [
            pid
            for pid, person in col["people"].items()
            if not person["contact"].get("email")
        ],
        "rounds": col["rounds"],
        "registrations": col["registrations"],
        "exports": col["exports"],
        "preferences_hash": digest(rows) if not missing and not rankings else None,
        "note": "No invitations sent. No preference / insufficient information remains assignable with zero score; hard exclusions are separate.",
    }


def build_rankings(directory, max_options=None):
    root = Path(directory).resolve()
    store = Store(root)
    with store.lock():
        state = store.load()
        col = state["collection"]
        rows, missing, needed, context = derive_preferences(col)
        require(
            not missing,
            "Complete all assessment batches before cross-batch ranking",
            "INCOMPLETE_COHORT",
        )
        limit = col["max_options"] if max_options is None else max_options
        require(type(limit) is int and limit > 0, "max_options must be positive")
        require(needed, "No outstanding rankings to build")
        require(
            all(n["package_id"] is None for n in needed),
            "A current ranking round already exists; import its responses",
        )
        too_long = [
            f"{n['participant_id']} {n['domain']}: {len(n['selected'])}"
            for n in needed
            if len(n["selected"]) > limit
        ]
        require(
            not too_long,
            "Selected lists exceed ranking budget: "
            + ", ".join(too_long)
            + ". Explicitly raise --max-options or have respondents revise their selections; no options were dropped.",
            "RANKING_BUDGET",
        )
        packages = {}
        round_name = f"ranking_{len(col['rounds'])}"
        for n in needed:
            pid, domain = n["participant_id"], n["domain"]
            key = f"c{col['nonce']}_r_{digest([pid, domain, context])[:16]}"
            options = {p["id"]: p for p in col["options"][pid][domain]}
            labels = {
                f"{options[c].get('name', options[c].get('title'))} [{c}]": c
                for c in n["selected"]
            }
            packages[key] = {
                "id": key,
                "participant_id": pid,
                "domain": domain,
                "stage": "ranking",
                "assessment_hash": context,
                "candidates": n["selected"],
                "questions": [
                    {
                        "kind": "rank",
                        "question_name": "ranking",
                        "question_text": f"For {col['people'][pid]['name']}: rank these selected {domain} best first across all assessment batches. Rank every displayed option once. Unselected options retain zero score; exclusions from the assessment remain hard constraints.",
                        "question_options": list(labels),
                        "mapping": labels,
                    }
                ],
            }
        _write_round(col, root, packages, round_name)
        col["max_options"] = limit
        store.commit(state, "collection.rank", {"assessment_hash": context})
    return collection_status(root)


def import_responses(directory, submissions, replace=False, source="human"):
    store = Store(directory)
    with store.lock():
        state = store.load()
        col = state["collection"]
        require(source in ("human", "synthetic"), "Invalid response source")
        require(
            source != "synthetic" or col["market"].get("synthetic") is True,
            "Synthetic responses require an explicitly synthetic market",
        )
        require(isinstance(submissions, list), "Responses must be an array")
        seen = set()
        changed = 0
        _, _, context = assessment(col)
        stages = set()
        # State is only committed after the entire import validates.
        for raw in submissions:
            require(isinstance(raw, dict), "Response must be an object")
            key = raw.get("package_id")
            require(
                isinstance(key, str) and key in col["packages"] and key not in seen,
                "Unknown or duplicate package",
            )
            seen.add(key)
            p = col["packages"][key]
            stages.add(p["stage"])
            require(
                raw.get("participant_id") == p["participant_id"],
                "Wrong respondent for package",
            )
            sid = raw.get("submission_id")
            require(
                isinstance(sid, str) and sid.strip(), "Missing stable submission_id"
            )
            token = digest([key, sid])
            record = {**deepcopy(raw), "source": source}
            prior = col["submissions"].get(token)
            if prior:
                require(prior == record, "Same submission ID has conflicting content")
                continue  # replay must not roll back a later revision
            require(
                p["stage"] != "ranking" or p["assessment_hash"] == context,
                "Ranking is stale after assessment revisions; build a new round",
            )
            old = col["responses"].get(key)
            require(
                old is None or replace,
                "Response exists; use --replace for an explicit revision",
            )
            require(
                not old or old["source"] != "human" or source == "human",
                "Cannot replace a human response with synthetic answers",
            )
            answers = raw.get("answers")
            require(
                isinstance(answers, dict)
                and set(answers) == {q["question_name"] for q in p["questions"]},
                "Missing or unexpected answer fields",
            )
            for q in p["questions"]:
                value = answers[q["question_name"]]
                if q["kind"] == "rank":
                    require(
                        isinstance(value, list)
                        and all(isinstance(v, str) for v in value)
                        and len(value) == len(q["question_options"])
                        and set(value) == set(q["question_options"]),
                        "Ranking must contain each displayed option exactly once",
                    )
                else:
                    require(
                        isinstance(value, str) and value in q["question_options"],
                        f"Missing or invalid answer: {q['question_name']}",
                    )
            col["submissions"][token] = record
            col["responses"][key] = record
            changed += 1
        require(len(stages) <= 1, "Import assessments and rankings in separate calls")
        if changed:
            store.commit(
                state,
                "collection.import",
                {"imported": changed, "source": source, "replace": replace},
            )
    return {"imported": changed, **collection_status(directory)}


def export_preferences(directory, output):
    store = Store(directory)
    with store.lock():
        state = store.load()
        col = state["collection"]
        rows, missing, needed, context = derive_preferences(col)
        require(
            not missing and not needed,
            "Collection is incomplete; import all assessment and required ranking responses",
            "INCOMPLETE_COHORT",
        )
        if col["mode"] == "teams":
            from .teams import validate_team_inputs

            _, rows = validate_team_inputs(col["market"], rows)
        else:
            from .reviews import validate_review_inputs

            _, rows = validate_review_inputs(col["market"], rows)
        path = Path(output).resolve()
        provenance = path.with_name(path.name + ".collection.json")
        require(
            not path.exists() and not provenance.exists(),
            "Preference output or provenance file already exists",
        )
        decisions, _, _ = assessment(col)
        audit = {
            "market_hash": col["market_hash"],
            "assessment_hash": context,
            "preferences_hash": digest(rows),
            "field_dir": str(Path(directory).resolve()),
            "decisions": decisions,
            "sources": sorted({r["source"] for r in rows}),
            "note": "No preference / insufficient information is retained here and maps to omitted zero-score options; it is not an exclusion.",
        }
        write_json(path, rows)
        write_json(provenance, audit)
        entry = {
            "path": str(path),
            "preferences_hash": digest(rows),
            "assessment_hash": context,
            "provenance": str(provenance),
        }
        col["exports"].append(entry)
        store.commit(state, "collection.export", entry)
    return {**entry, "complete": True}


def register_collection(directory, package_id, uuid, delivery=None):
    UUID(uuid)
    if delivery:
        UUID(delivery)
    store = Store(directory)
    with store.lock():
        state = store.load()
        col = state["collection"]
        require(
            col["native"],
            "JSON-only preview has no native Humanize artifact; build a native collection",
        )
        require(package_id in col["packages"], "Unknown package")
        package = col["packages"][package_id]
        require(
            package["stage"] != "ranking"
            or package["assessment_hash"] == assessment(col)[2],
            "Ranking package is stale; register the current round",
        )
        require(
            not any(
                v["uuid"] == uuid and k != package_id
                for k, v in col["registrations"].items()
            ),
            "Survey UUID already registered to another package",
        )
        old = col["registrations"].get(package_id)
        require(
            old is None or old["uuid"] == uuid,
            "Package already bound to a different survey",
        )
        entry = deepcopy(old or {"uuid": uuid, "deliveries": []})
        if delivery and delivery not in entry["deliveries"]:
            entry["deliveries"].append(delivery)
        col["registrations"][package_id] = entry
        store.commit(state, "collection.register", {"package_id": package_id, **entry})
        folder = Path(package["folder"])
        has_email = bool(
            col["people"][package["participant_id"]]["contact"].get("email")
        )
    return {
        **entry,
        "package_id": package_id,
        "external_actions": {
            "status": ["ep", "humanize", "status", uuid],
            "deliveries": ["ep", "humanize", "deliveries", "list", uuid],
            "invite": [
                "ep",
                "humanize",
                "deliveries",
                "create",
                uuid,
                "--name",
                package_id + "-invitation",
                "--routes",
                str(folder / "invitation-routes.json"),
            ]
            if has_email
            else None,
            "responses": [
                "ep",
                "humanize",
                "responses",
                uuid,
                "--output",
                str(folder / "results.ep"),
            ],
        },
        "note": "Inspect existing deliveries before retrying. Sending requires organizer authorization. No invitations or network actions executed.",
    }
