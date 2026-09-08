"""Market and preference contracts. Unknown candidates are never rejections."""

from __future__ import annotations

import copy
import csv
from pathlib import Path

from .common import identifier, read_json, require

DEFAULTS = {
    "proposing_side": "left",
    "delegation": "direct",
    "side_policies": {},
    "unknown_policy": "exclude",
    "benchmark_policy": "advisory",
    "benchmark_min_accuracy": 0.8,
    "benchmark_min_answers": 5,
    "deadline": None,
}


def validate_market(raw):
    require(isinstance(raw, dict), "Market must be an object")
    market = copy.deepcopy(raw)
    require(market.get("schema_version", "1.0") == "1.0", "Unsupported market schema")
    market["schema_version"] = "1.0"
    require(isinstance(market.get("participants"), list), "participants must be a list")
    ids = set()
    for person in market["participants"]:
        require(isinstance(person, dict), "Participant must be an object")
        pid = identifier(person.get("id"))
        require(pid not in ids, f"Duplicate participant: {pid}")
        ids.add(pid)
        require(person.get("side") in ("left", "right"), f"Invalid side for {pid}")
        require(
            type(person.get("capacity", 1)) is int and person.get("capacity", 1) >= 0,
            f"Capacity must be a nonnegative integer for {pid}",
        )
        require(
            isinstance(person.get("name"), str) and person["name"].strip(),
            f"Missing name for {pid}",
        )
        require(
            isinstance(person.get("profile", {}), dict),
            f"profile must be an object for {pid}",
        )
        require(
            isinstance(person.get("preferences", ""), str),
            "preferences must be natural-language text",
        )
        require(
            isinstance(person.get("contact", {}), dict), "contact must be an object"
        )
        require(
            not {"email", "contact", "preferences"}.intersection(
                person.get("profile", {})
            ),
            "Keep email, contact, and private preferences outside public profile",
        )
    require(ids, "Market has no participants")
    from .matching import validate_capacities

    validate_capacities(
        {p["id"] for p in market["participants"] if p["side"] == "left"},
        {p["id"] for p in market["participants"] if p["side"] == "right"},
        capacities(market),
    )
    config = {**DEFAULTS, **market.get("config", {})}
    require(not set(config) - set(DEFAULTS), "Unknown market configuration key")
    require(config["proposing_side"] in ("left", "right"), "Invalid proposing side")
    policies = {"direct", "delegated", "confirm"}
    require(
        config["delegation"] in policies,
        "delegation must be direct, delegated, or confirm",
    )
    require(
        isinstance(config["side_policies"], dict), "side_policies must be an object"
    )
    require(set(config["side_policies"]) <= {"left", "right"}, "Invalid side override")
    require(
        all(p in policies for p in config["side_policies"].values()),
        "Invalid side policy",
    )
    require(
        config["unknown_policy"] in {"exclude", "require_complete"},
        "Invalid unknown policy",
    )
    require(
        config["benchmark_policy"] in {"advisory", "gate"}, "Invalid benchmark policy"
    )
    from .common import number

    number(config["benchmark_min_accuracy"], 0, 1)
    require(
        type(config["benchmark_min_answers"]) is int
        and config["benchmark_min_answers"] > 0,
        "benchmark_min_answers must be positive",
    )
    if config["deadline"] is not None:
        from datetime import datetime

        parsed = datetime.fromisoformat(config["deadline"])
        require(parsed.tzinfo is not None, "Deadline must include a timezone")
    market["config"] = config
    index = participants(market)
    for field in ("eligible_pairs", "excluded_pairs"):
        if field in market:
            require(isinstance(market[field], list), f"{field} must be a list")
            seen = set()
            for edge in market[field]:
                require(
                    isinstance(edge, list) and len(edge) == 2,
                    "Edges must be [left_id, right_id]",
                )
                a, b = edge
                require(
                    a in index
                    and b in index
                    and index[a]["side"] == "left"
                    and index[b]["side"] == "right",
                    "Invalid market edge",
                )
                require((a, b) not in seen, "Duplicate market edge")
                seen.add((a, b))
    return market


def participants(market):
    return {p["id"]: p for p in market["participants"]}


def capacities(market, active=None):
    return {
        p["id"]: p.get("capacity", 1)
        for p in market["participants"]
        if active is None or p["id"] in active
    }


def eligible(market):
    index = participants(market)
    blocked = {tuple(x) for x in market.get("excluded_pairs", [])}
    pairs = market.get("eligible_pairs")
    if pairs is None:
        pairs = (
            (a, b)
            for a in index
            for b in index
            if index[a]["side"] == "left" and index[b]["side"] == "right"
        )
    graph = {pid: set() for pid in index}
    for a, b in pairs:
        if (a, b) not in blocked:
            graph[a].add(b)
            graph[b].add(a)
    return graph


def policy(market, pid):
    return market["config"]["side_policies"].get(
        participants(market)[pid]["side"], market["config"]["delegation"]
    )


def public_profile(person):
    return {
        "id": person["id"],
        "name": person["name"],
        "profile": person.get("profile", {}),
    }


def validate_preferences(market, rows):
    require(isinstance(rows, list), "Preference records must be a list")
    graph = eligible(market)
    seen = set()
    output = []
    for raw in rows:
        require(isinstance(raw, dict), "Preference record must be an object")
        row = copy.deepcopy(raw)
        pid = row.get("participant_id")
        require(
            pid in graph and pid not in seen, f"Unknown or duplicate respondent: {pid}"
        )
        seen.add(pid)
        for field in ("ranking", "unacceptable", "evaluated"):
            values = row.get(
                field,
                []
                if field != "evaluated"
                else row.get("ranking", []) + row.get("unacceptable", []),
            )
            require(
                isinstance(values, list) and all(isinstance(x, str) for x in values),
                f"{field} must be an ID list",
            )
            require(
                len(values) == len(set(values)),
                f"Duplicate {field} candidate for {pid}",
            )
            require(
                set(values) <= graph[pid],
                f"Ineligible or unknown {field} candidate for {pid}",
            )
            row[field] = values
        require(
            not set(row["ranking"]) & set(row["unacceptable"]),
            f"Ranked and rejected candidate for {pid}",
        )
        require(
            set(row["ranking"] + row["unacceptable"]) <= set(row["evaluated"]),
            "Decisions must refer to evaluated candidates",
        )
        require(
            row.get("complete") is True,
            f"Incomplete submission for {pid}; retain as raw field response until completed",
        )
        row.setdefault("source", "human")
        require(
            row["source"] in {"human", "delegated", "synthetic"},
            "Invalid preference source",
        )
        row.setdefault("confirmed", False)
        require(type(row["confirmed"]) is bool, "confirmed must be boolean")
        row["outside_option"] = "unmatched"
        output.append(row)
    return output


def load_side(path, side):
    path = Path(path)
    if path.suffix == ".csv":
        with path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            if row.get("capacity", "") == "":
                row.pop("capacity", None)
            else:
                try:
                    row["capacity"] = int(row["capacity"])
                except ValueError:
                    require(False, "CSV capacity must be an integer")
            for key in ("profile", "contact"):
                if row.get(key):
                    import json

                    row[key] = json.loads(row[key])
                else:
                    row[key] = {}
    elif path.suffix == ".ep" or path.is_dir():
        from .edsl_bridge import load_object

        rows = []
        for agent in load_object("AgentList", path):
            traits = dict(agent.traits)
            rows.append(
                {"id": traits.pop("id", agent.name), "name": agent.name, **traits}
            )
    else:
        data = read_json(path)
        rows = data if isinstance(data, list) else data["participants"]
    return [{**r, "side": side} for r in rows]
