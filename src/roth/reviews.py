"""Peer-review allocation with exact coverage, bounded workloads, and conflicts.

The binary assignment MILP maximizes additive preference/expertise scores.
Validation and independent verification require no optional dependencies.
"""

from copy import deepcopy
import math

from .common import RothError, digest, identifier, number, require
from .teams import borda


def _integer(value, label):
    require(type(value) is int and value >= 0, f"{label} must be a nonnegative integer")
    return value


def _ids(value, allowed, label, nonempty=False):
    require(
        isinstance(value, list) and all(isinstance(p, str) for p in value),
        f"{label} must be an ID list",
    )
    require(
        len(value) == len(set(value)) and set(value) <= set(allowed),
        f"{label}: duplicate or unknown IDs",
    )
    require(not nonempty or value, f"{label} must not be empty")
    return value


def validate_review_market(raw):
    require(isinstance(raw, dict), "Review market must be an object")
    market = deepcopy(raw)
    require(
        not set(market)
        - {
            "schema_version",
            "mode",
            "name",
            "synthetic",
            "reviewers",
            "submissions",
            "config",
            "eligible_pairs",
            "excluded_pairs",
        },
        "Unknown review market fields",
    )
    require(market.get("schema_version", "1.0") == "1.0", "Unknown review schema")
    require(market.get("mode", "reviews") == "reviews", "Expected reviews mode")
    market.update(schema_version="1.0", mode="reviews")
    require(type(market.get("synthetic", False)) is bool, "synthetic must be boolean")
    config = market.get("config", {})
    require(isinstance(config, dict), "config must be an object")
    require(
        not set(config)
        - {
            "min_reviews",
            "max_reviews",
            "reviews_per_submission",
            "scoring",
            "exclude_teammates",
        },
        "Unknown review configuration",
    )
    config = {
        "min_reviews": 3,
        "max_reviews": 3,
        "reviews_per_submission": 3,
        "scoring": "borda",
        "exclude_teammates": True,
        **config,
    }
    for field in ("min_reviews", "max_reviews", "reviews_per_submission"):
        _integer(config[field], field)
    require(
        config["min_reviews"] <= config["max_reviews"],
        "min_reviews exceeds max_reviews",
    )
    require(
        config["scoring"] in ("borda", "scores", "none"),
        "scoring must be borda, scores, or none",
    )
    require(
        type(config["exclude_teammates"]) is bool, "exclude_teammates must be boolean"
    )
    market["config"] = config
    used = set()
    for field, title, keys in (
        ("reviewers", "name", {"id", "name", "team", "min_reviews", "max_reviews"}),
        (
            "submissions",
            "title",
            {"id", "title", "authors", "reviews_required", "description"},
        ),
    ):
        require(
            isinstance(market.get(field), list) and market[field],
            f"Provide a nonempty {field} list",
        )
        for item in market[field]:
            require(
                isinstance(item, dict) and not set(item) - keys,
                f"Invalid or unknown {field} fields",
            )
            pid = identifier(item.get("id"))
            require(pid not in used, f"Duplicate reviewer/submission ID: {pid}")
            used.add(pid)
            require(
                isinstance(item.get(title), str) and item[title].strip(),
                f"Missing {title} for {pid}",
            )
            if field == "reviewers":
                if "team" in item:
                    identifier(item["team"])
                for bound in ("min_reviews", "max_reviews"):
                    item[bound] = _integer(
                        item.get(bound, config[bound]), f"{pid}: {bound}"
                    )
                require(
                    item["min_reviews"] <= item["max_reviews"],
                    f"{pid}: min_reviews exceeds max_reviews",
                )
            else:
                item["reviews_required"] = _integer(
                    item.get("reviews_required", config["reviews_per_submission"]),
                    f"{pid}: reviews_required",
                )
                require(
                    isinstance(item.get("description", ""), str),
                    "description must be text",
                )
    reviewers = {r["id"] for r in market["reviewers"]}
    submissions = {p["id"] for p in market["submissions"]}
    for paper in market["submissions"]:
        # Authors use the same identity namespace as reviewers. Authors who do
        # not review can be listed with min_reviews=max_reviews=0.
        _ids(paper.get("authors"), reviewers, f"{paper['id']}: authors", nonempty=True)
    for field in ("eligible_pairs", "excluded_pairs"):
        if field not in market:
            continue
        require(isinstance(market[field], list), f"{field} must be a list")
        seen = set()
        for edge in market[field]:
            require(
                isinstance(edge, list)
                and len(edge) == 2
                and all(isinstance(p, str) for p in edge),
                f"{field} entries must be [reviewer_id, submission_id]",
            )
            a, b = edge
            require(
                a in reviewers and b in submissions and (a, b) not in seen,
                f"{field}: duplicate or invalid edge",
            )
            seen.add((a, b))
    return market


def exclusion_reasons(market):
    """Organizer exclusions only; self-review can never be enabled."""
    people = {r["id"]: r for r in market["reviewers"]}
    allowed = (
        set(map(tuple, market["eligible_pairs"]))
        if "eligible_pairs" in market
        else None
    )
    blocked = set(map(tuple, market.get("excluded_pairs", [])))
    reasons = {}
    for rid, reviewer in people.items():
        for paper in market["submissions"]:
            edge = rid, paper["id"]
            why = []
            if rid in paper["authors"]:
                why.append("self_review")
            if (
                market["config"]["exclude_teammates"]
                and reviewer.get("team")
                and any(
                    people[a].get("team") == reviewer["team"]
                    for a in paper["authors"]
                    if a != rid
                )
            ):
                why.append("teammate_review")
            if allowed is not None and edge not in allowed:
                why.append("ineligible")
            if edge in blocked:
                why.append("organizer_conflict")
            if why:
                reasons[edge] = why
    return reasons


def validate_review_inputs(raw_market, raw_preferences):
    market = validate_review_market(raw_market)
    require(isinstance(raw_preferences, list), "Review preferences must be an array")
    scoring = market["config"]["scoring"]
    if scoring == "none":
        require(
            not raw_preferences,
            "scoring=none requires an empty preference array; do not silently discard supplied preferences",
        )
        return market, []
    people = {r["id"] for r in market["reviewers"]}
    papers = {p["id"] for p in market["submissions"]}
    blocked = exclusion_reasons(market)
    rows = {}
    for raw in raw_preferences:
        require(isinstance(raw, dict), "Review preference must be an object")
        require(
            not set(raw)
            - {
                "reviewer_id",
                "ranking",
                "scores",
                "unacceptable",
                "complete",
                "source",
            },
            "Unknown review preference fields",
        )
        rid = raw.get("reviewer_id")
        require(
            isinstance(rid, str) and rid in people and rid not in rows,
            f"Unknown or duplicate reviewer: {rid}",
        )
        require(
            raw.get("complete") is True, f"Completed preferences required for {rid}"
        )
        row = deepcopy(raw)
        options = {p for p in papers if (rid, p) not in blocked}
        row["unacceptable"] = _ids(
            row.get("unacceptable", []), options, f"{rid}: unacceptable"
        )
        if scoring == "borda":
            require(
                "scores" not in row,
                "Use ranking with scoring=borda; scores would be ignored",
            )
            _ids(row.get("ranking"), options, f"{rid}: ranking")
            expressed = set(row["ranking"])
        else:
            require(
                "ranking" not in row,
                "Use scores with scoring=scores; ranking would be ignored",
            )
            require(
                isinstance(row.get("scores"), dict) and set(row["scores"]) <= options,
                f"{rid}: scores must map eligible submission IDs to numbers",
            )
            for value in row["scores"].values():
                number(value, 0, 100)
            expressed = set(row["scores"])
        require(
            not expressed & set(row["unacceptable"]),
            f"{rid}: preferred and unacceptable submission",
        )
        row.setdefault("source", "human")
        require(
            row["source"] in ("human", "organizer", "synthetic"),
            "Review source must be human, organizer, or synthetic",
        )
        rows[rid] = row
    require(
        set(rows) == people,
        f"Missing reviewer submissions: {sorted(people - set(rows))}",
    )
    return market, [rows[r["id"]] for r in market["reviewers"]]


def review_edges(market, preferences):
    reasons = exclusion_reasons(market)
    for row in preferences:
        for pid in row["unacceptable"]:
            reasons.setdefault((row["reviewer_id"], pid), []).append("unacceptable")
    return [
        (r["id"], p["id"])
        for r in market["reviewers"]
        for p in market["submissions"]
        if (r["id"], p["id"]) not in reasons
    ], reasons


def review_scores(market, preferences):
    """Fixed eligible universe for Borda, before individual unacceptable options."""
    blocked = exclusion_reasons(market)
    result = {}
    for row in preferences:
        rid = row["reviewer_id"]
        if market["config"]["scoring"] == "borda":
            count = sum((rid, p["id"]) not in blocked for p in market["submissions"])
            result[rid] = {
                p: v / max(1, count - 1)
                for p, v in borda(row["ranking"], count).items()
            }
        else:
            result[rid] = {p: value / 100 for p, value in row["scores"].items()}
    return result


def review_feasibility(market, preferences):
    """Necessary checks; passing these does not prove joint feasibility."""
    edges, _ = review_edges(market, preferences)
    demand = sum(p["reviews_required"] for p in market["submissions"])
    low = sum(r["min_reviews"] for r in market["reviewers"])
    high = sum(r["max_reviews"] for r in market["reviewers"])
    issues = []
    if not low <= demand <= high:
        issues.append(
            f"Total demand {demand} lies outside reviewer workload bounds [{low}, {high}]"
        )
    for p in market["submissions"]:
        available = sum(b == p["id"] for a, b in edges)
        if p["reviews_required"] > available:
            issues.append(
                f"{p['id']}: needs {p['reviews_required']} distinct reviewers but only {available} edges are allowed"
            )
    for r in market["reviewers"]:
        available = sum(a == r["id"] for a, b in edges)
        if r["min_reviews"] > available:
            issues.append(
                f"{r['id']}: minimum load {r['min_reviews']} exceeds {available} allowed submissions"
            )
    return {
        "necessary_checks_pass": not issues,
        "issues": issues,
        "review_demand": demand,
        "minimum_supply": low,
        "maximum_supply": high,
        "eligible_edges": len(edges),
        "note": "Necessary checks only; shared bottlenecks can still make the full assignment infeasible.",
    }


def evaluate_reviews(market, preferences, assignments):
    market, preferences = validate_review_inputs(market, preferences)
    require(
        isinstance(assignments, list), "Assignments must be a list", "INVALID_SOLUTION"
    )
    edges, _ = review_edges(market, preferences)
    allowed, seen = set(edges), set()
    scores = review_scores(market, preferences)
    rows = {r["reviewer_id"]: r for r in preferences}
    loads = {r["id"]: [] for r in market["reviewers"]}
    coverage = {p["id"]: [] for p in market["submissions"]}
    outcomes = []
    for edge in assignments:
        require(
            isinstance(edge, (list, tuple))
            and len(edge) == 2
            and all(isinstance(p, str) for p in edge),
            "Assignments must be [reviewer_id, submission_id] pairs",
            "INVALID_SOLUTION",
        )
        rid, pid = edge
        require(
            (rid, pid) in allowed and (rid, pid) not in seen,
            f"Duplicate, unknown, or excluded assignment: {edge}",
            "INVALID_SOLUTION",
        )
        seen.add((rid, pid))
        loads[rid].append(pid)
        coverage[pid].append(rid)
        row = rows.get(rid, {})
        rank = (
            row.get("ranking", []).index(pid) + 1
            if pid in row.get("ranking", [])
            else None
        )
        outcomes.append(
            {
                "reviewer_id": rid,
                "submission_id": pid,
                "rank": rank,
                "score": scores.get(rid, {}).get(pid, 0),
                "expressed_preference": pid in row.get("ranking", [])
                or pid in row.get("scores", {}),
            }
        )
    for r in market["reviewers"]:
        require(
            r["min_reviews"] <= len(loads[r["id"]]) <= r["max_reviews"],
            f"{r['id']}: workload outside bounds",
            "INVALID_SOLUTION",
        )
    for p in market["submissions"]:
        require(
            len(coverage[p["id"]]) == p["reviews_required"],
            f"{p['id']}: incorrect review coverage",
            "INVALID_SOLUTION",
        )
    return {
        "valid": True,
        "total_score": sum(o["score"] for o in outcomes),
        "reviewers": {r: sorted(ps) for r, ps in loads.items()},
        "submissions": {p: sorted(rs) for p, rs in coverage.items()},
        "outcomes": sorted(
            outcomes, key=lambda o: (o["reviewer_id"], o["submission_id"])
        ),
        "statistics": {
            "assignments": len(assignments),
            "reviewers": len(loads),
            "submissions": len(coverage),
            "reviewer_loads": {r: len(ps) for r, ps in loads.items()},
            "submission_coverage": {p: len(rs) for p, rs in coverage.items()},
            "min_reviewer_load": min(map(len, loads.values())),
            "max_reviewer_load": max(map(len, loads.values())),
            "top_three_assignments": sum(
                o["rank"] is not None and o["rank"] <= 3 for o in outcomes
            )
            if market["config"]["scoring"] == "borda"
            else None,
            "assignments_without_expressed_preference": sum(
                not o["expressed_preference"] for o in outcomes
            )
            if market["config"]["scoring"] != "none"
            else None,
            "mean_assignment_score": sum(o["score"] for o in outcomes) / len(outcomes)
            if outcomes
            else None,
        },
    }


def solve_reviews(raw_market, raw_preferences, time_limit=60):
    market, preferences = validate_review_inputs(raw_market, raw_preferences)
    number(time_limit, 0.001)
    checks = review_feasibility(market, preferences)
    require(checks["necessary_checks_pass"], "; ".join(checks["issues"]), "INFEASIBLE")
    edges, _ = review_edges(market, preferences)
    scores = review_scores(market, preferences)
    if not edges:
        assignments, metadata, optimal = (
            [],
            {"message": "Empty feasible allocation", "optimal": True},
            True,
        )
    else:
        try:
            import numpy as np
            import scipy
            from scipy.optimize import Bounds, LinearConstraint, milp
            from scipy.sparse import coo_matrix
        except ImportError as error:
            raise RothError(
                "Review optimization requires SciPy/HiGHS: install 'roth[reviews]' or pip install -e '.[reviews]' from a checkout",
                "MISSING_DEPENDENCY",
            ) from error
        reviewers = {r["id"]: i for i, r in enumerate(market["reviewers"])}
        papers = {
            p["id"]: i + len(reviewers) for i, p in enumerate(market["submissions"])
        }
        row_ids, col_ids = [], []
        for j, (rid, pid) in enumerate(edges):
            row_ids += [reviewers[rid], papers[pid]]
            col_ids += [j, j]
        matrix = coo_matrix(
            (np.ones(len(row_ids)), (row_ids, col_ids)),
            shape=(len(reviewers) + len(papers), len(edges)),
        ).tocsc()
        lower = [r["min_reviews"] for r in market["reviewers"]] + [
            p["reviews_required"] for p in market["submissions"]
        ]
        upper = [r["max_reviews"] for r in market["reviewers"]] + [
            p["reviews_required"] for p in market["submissions"]
        ]
        cost = np.asarray([-scores.get(r, {}).get(p, 0) for r, p in edges])
        result = milp(
            cost,
            integrality=np.ones(len(edges)),
            bounds=Bounds(np.zeros(len(edges)), np.ones(len(edges))),
            constraints=LinearConstraint(matrix, lower, upper),
            options={"time_limit": time_limit, "mip_rel_gap": 0.0},
        )
        if result.status == 2:
            raise RothError(
                "No feasible review allocation satisfies coverage, workloads, and conflicts. Shared eligibility bottlenecks may prevent coverage even when total counts fit. No constraints were relaxed.",
                "INFEASIBLE",
            )
        require(
            result.status in (0, 1),
            f"Review solver failed: {result.message}",
            "SOLVER_ERROR",
        )
        require(
            result.x is not None,
            "Solver limit reached without a feasible allocation",
            "SOLVER_LIMIT",
        )
        require(
            len(result.x) == len(edges)
            and all(
                math.isfinite(float(v)) and min(abs(v), abs(v - 1)) < 1e-5
                for v in result.x
            ),
            "Invalid or nonintegral solver assignment",
            "INVALID_SOLUTION",
        )
        assignments = [
            list(edge) for edge, value in zip(edges, result.x) if value > 0.5
        ]
        checked = evaluate_reviews(market, preferences, assignments)
        require(
            result.fun is not None
            and math.isfinite(float(result.fun))
            and abs(checked["total_score"] + result.fun) < 1e-5,
            "Solver score disagrees with independently evaluated assignment",
            "INVALID_SOLUTION",
        )
        optimal = result.status == 0

        def finite(key):
            v = getattr(result, key, None)
            return float(v) if v is not None and math.isfinite(v) else None

        bound = finite("mip_dual_bound")
        metadata = {
            "name": "SciPy/HiGHS",
            "scipy_version": scipy.__version__,
            "status_code": int(result.status),
            "message": str(result.message),
            "optimal": optimal,
            "score_upper_bound": -bound if bound is not None else None,
            "relative_gap": finite("mip_gap"),
            "time_limit_seconds": time_limit,
        }
    assignments.sort()
    checked = evaluate_reviews(market, preferences, assignments)
    return {
        "schema_version": "1.0",
        "mode": "reviews",
        "method": "additive_review_assignment_milp",
        "input_hash": digest({"market": market, "preferences": preferences}),
        "solution_status": "optimal" if optimal else "feasible_limit",
        "assignments": sorted(assignments),
        **checked,
        "solver": metadata,
        "scoring": market["config"]["scoring"],
        "sources": sorted({r["source"] for r in preferences}),
        "note": "Coverage and workloads are hard constraints. Unranked/unscored eligible edges score zero and may be assigned; exclusions are forbidden. No stability or strategy-proofness claim. Equal-score optima can differ.",
    }
