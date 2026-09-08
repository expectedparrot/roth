"""Joint team formation and project assignment using a two-stage MILP.

Project IDs label teams: at most one team may occupy a project. SciPy/HiGHS
is optional and imported only by solve_teams. Scores are not cardinal welfare,
and this mechanism makes no stability or strategy-proofness claim.
"""

from copy import deepcopy
from itertools import combinations
import math
import time

from .common import RothError, digest, identifier, number, require


def validate_team_market(market):
    require(isinstance(market, dict), "Team market must be an object")
    market = deepcopy(market)
    require(market.get("schema_version", "1.0") == "1.0", "Unknown team schema")
    market["schema_version"] = "1.0"
    require(type(market.get("synthetic", False)) is bool, "synthetic must be boolean")
    all_ids = set()
    for side in ("students", "projects"):
        people = market.get(side)
        require(isinstance(people, list) and people, f"Provide a nonempty {side} list")
        for person in people:
            require(isinstance(person, dict), f"Each {side} entry must be an object")
            pid = identifier(person.get("id"))
            require(pid not in all_ids, f"Duplicate participant/project ID: {pid}")
            all_ids.add(pid)
            require(
                isinstance(person.get("name"), str) and person["name"].strip(),
                f"Missing name for {pid}",
            )
    config = market.get("config", {})
    require(isinstance(config, dict), "config must be an object")
    allowed = {
        "target_size",
        "allow_smaller",
        "allow_larger",
        "min_size",
        "max_size",
        "social_weight",
    }
    require(
        not set(config) - allowed,
        f"Unknown team configuration: {sorted(set(config) - allowed)}",
    )
    target = config.get("target_size", 3)
    require(type(target) is int and target >= 2, "target_size must be an integer >= 2")
    for flag in ("allow_smaller", "allow_larger"):
        require(type(config.get(flag, False)) is bool, f"{flag} must be boolean")
    smaller, larger = (
        config.get("allow_smaller", False),
        config.get("allow_larger", False),
    )
    low = config.get("min_size", max(2, target - 1) if smaller else target)
    high = config.get("max_size", target + 1 if larger else target)
    require(
        type(low) is int and type(high) is int and 2 <= low <= target <= high,
        "Team sizes must satisfy 2 <= min_size <= target_size <= max_size",
    )
    require(smaller or low == target, "min_size below target requires allow_smaller")
    require(larger or high == target, "max_size above target requires allow_larger")
    weight = number(config.get("social_weight", 0.5), 0, 1)
    market["config"] = dict(
        target_size=target,
        allow_smaller=smaller,
        allow_larger=larger,
        min_size=low,
        max_size=high,
        social_weight=weight,
    )
    closed = market.get("closed_projects", [])
    require(
        isinstance(closed, list)
        and all(isinstance(p, str) for p in closed)
        and len(closed) == len(set(closed))
        and set(closed) <= {p["id"] for p in market["projects"]},
        "closed_projects must contain unique known project IDs",
    )
    return market


def validate_team_inputs(market, preferences):
    market = validate_team_market(market)
    students = {p["id"] for p in market["students"]}
    projects = {p["id"] for p in market["projects"]}
    require(
        isinstance(preferences, list), "Preferences must be an array of student records"
    )
    rows = {}
    keys = {
        "student_id",
        "projects",
        "teammates",
        "unacceptable_projects",
        "incompatible_teammates",
        "complete",
        "source",
    }
    for raw in preferences:
        require(isinstance(raw, dict), "Each preference record must be an object")
        require(
            not set(raw) - keys, f"Unknown preference fields: {sorted(set(raw) - keys)}"
        )
        pid = raw.get("student_id")
        require(
            isinstance(pid, str) and pid in students and pid not in rows,
            f"Unknown or duplicate student: {pid}",
        )
        require(
            raw.get("complete") is True, f"Completed preferences required for {pid}"
        )
        row = deepcopy(raw)
        for field, options in (
            ("projects", projects),
            ("teammates", students - {pid}),
            ("unacceptable_projects", projects),
            ("incompatible_teammates", students - {pid}),
        ):
            values = row.get(
                field,
                [] if field.startswith(("unacceptable", "incompatible")) else None,
            )
            require(
                isinstance(values, list) and all(isinstance(v, str) for v in values),
                f"{pid}: {field} must be a list of IDs",
            )
            require(
                len(values) == len(set(values)) and set(values) <= options,
                f"{pid}: duplicate, self, or unknown IDs in {field}",
            )
            row[field] = values
        require(
            not set(row["projects"]) & set(row["unacceptable_projects"]),
            f"{pid}: ranked and unacceptable project",
        )
        require(
            not set(row["teammates"]) & set(row["incompatible_teammates"]),
            f"{pid}: ranked and incompatible teammate",
        )
        row.setdefault("source", "human")
        require(
            row["source"] in {"human", "synthetic"},
            "Team preference source must be human or synthetic",
        )
        rows[pid] = row
    require(
        set(rows) == students,
        f"Missing student submissions: {sorted(students - set(rows))}",
    )
    return market, [rows[p["id"]] for p in market["students"]]


def borda(ranking, option_count):
    """Fixed-universe Borda: M-rank, not list_length-rank; singleton gets 1."""
    return {
        pid: max(1, option_count) - rank if option_count > 1 else 1
        for rank, pid in enumerate(ranking, 1)
    }


def score_tables(market, preferences):
    return {
        row["student_id"]: {
            "projects": borda(row["projects"], len(market["projects"])),
            "teammates": borda(row["teammates"], len(market["students"]) - 1),
        }
        for row in preferences
    }


def evaluate_assignment(market, preferences, assignments):
    """Independently verify a discrete assignment and recompute its score."""
    market, preferences = validate_team_inputs(market, preferences)
    students = [p["id"] for p in market["students"]]
    projects = [p["id"] for p in market["projects"]]
    require(
        isinstance(assignments, dict) and set(assignments) == set(students),
        "Assignment must contain every student exactly once",
        "INVALID_SOLUTION",
    )
    require(
        all(p in projects for p in assignments.values()),
        "Unknown assigned project",
        "INVALID_SOLUTION",
    )
    require(
        not set(assignments.values()) & set(market.get("closed_projects", [])),
        "Assignment uses a closed project",
        "INVALID_SOLUTION",
    )
    config = market["config"]
    teams = {p: [i for i in students if assignments[i] == p] for p in projects}
    teams = {p: members for p, members in teams.items() if members}
    require(
        all(config["min_size"] <= len(t) <= config["max_size"] for t in teams.values()),
        "Assignment violates team size bounds",
        "INVALID_SOLUTION",
    )
    rows = {r["student_id"]: r for r in preferences}
    scores = score_tables(market, preferences)
    project_scale = max(1, len(projects) - 1)
    social_scale = max(1, len(students) - 2) * (config["target_size"] - 1)
    outcomes = []
    for i in students:
        p, row = assignments[i], rows[i]
        peers = [j for j in teams[p] if j != i]
        require(
            p not in row["unacceptable_projects"],
            f"{i}: unacceptable assigned project",
            "INVALID_SOLUTION",
        )
        require(
            not set(peers) & set(row["incompatible_teammates"]),
            f"{i}: incompatible assigned teammate",
            "INVALID_SOLUTION",
        )
        project_points = scores[i]["projects"].get(p, 0)
        social_points = sum(scores[i]["teammates"].get(j, 0) for j in peers)
        project_score, social_score = (
            project_points / project_scale,
            social_points / social_scale,
        )
        outcomes.append(
            {
                "student_id": i,
                "project_id": p,
                "teammates": peers,
                "project_rank": row["projects"].index(p) + 1
                if p in row["projects"]
                else None,
                "project_borda": project_points,
                "teammate_borda": social_points,
                "project_score": project_score,
                "social_score": social_score,
                "combined_score": (1 - config["social_weight"]) * project_score
                + config["social_weight"] * social_score,
                "ranked_teammates_received": sum(j in row["teammates"] for j in peers),
            }
        )
    deviation = sum(abs(len(t) - config["target_size"]) for t in teams.values())
    return {
        "valid": True,
        "teams": [{"project_id": p, "students": t} for p, t in teams.items()],
        "unused_projects": [p for p in projects if p not in teams],
        "students": outcomes,
        "size_deviation": deviation,
        "total_score": sum(o["combined_score"] for o in outcomes),
        "statistics": {
            "students": len(students),
            "teams": len(teams),
            "project_first_choices": sum(o["project_rank"] == 1 for o in outcomes),
            "project_top_three": sum(
                o["project_rank"] is not None and o["project_rank"] <= 3
                for o in outcomes
            ),
            "unranked_project_assignments": sum(
                o["project_rank"] is None for o in outcomes
            ),
            "students_with_ranked_teammate": sum(
                o["ranked_teammates_received"] > 0 for o in outcomes
            ),
            "minimum_individual_score": min(o["combined_score"] for o in outcomes),
            "mean_project_score": sum(o["project_score"] for o in outcomes)
            / len(students),
            "mean_social_score": sum(o["social_score"] for o in outcomes)
            / len(students),
        },
    }


def solve_teams(market, preferences, time_limit=60):
    market, preferences = validate_team_inputs(market, preferences)
    number(time_limit, 0.001)
    try:
        import numpy as np
        import scipy
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix
    except ImportError as error:
        raise RothError(
            "Team optimization requires the optional solver: pip install 'roth[teams]' (or pip install -e '.[teams]' from a checkout)",
            "MISSING_DEPENDENCY",
        ) from error
    students = [p["id"] for p in market["students"]]
    projects = [p["id"] for p in market["projects"]]
    n, m = len(students), len(projects)
    config = market["config"]
    low, high, target = config["min_size"], config["max_size"], config["target_size"]
    require(
        math.ceil(n / high)
        <= min(m - len(market.get("closed_projects", [])), n // low),
        f"Cannot place {n} students into available projects with teams of {low}–{high}; change size bounds or open project count",
        "INFEASIBLE",
    )
    scores = score_tables(market, preferences)
    pref = {r["student_id"]: r for r in preferences}
    weight = config["social_weight"]
    objective, integrality, upper = [], [], []

    def variable(cost=0, integer=False, bound=1):
        idx = len(objective)
        objective.append(cost)
        integrality.append(int(integer))
        upper.append(bound)
        return idx

    x = {
        (i, p): variable(
            -(1 - weight) * scores[i]["projects"].get(p, 0) / max(1, m - 1),
            True,
            0
            if p in pref[i]["unacceptable_projects"]
            or p in market.get("closed_projects", [])
            else 1,
        )
        for i in students
        for p in projects
    }
    active = {p: variable(integer=True) for p in projects}
    deviation = {p: variable(bound=max(target, high)) for p in projects}
    row_index, col_index, values, lower_bounds, upper_bounds = [], [], [], [], []

    def constraint(coefficients, lower=-np.inf, upper=np.inf):
        row = len(lower_bounds)
        for index, coefficient in coefficients.items():
            row_index.append(row)
            col_index.append(index)
            values.append(coefficient)
        lower_bounds.append(lower)
        upper_bounds.append(upper)

    for i in students:
        constraint({x[i, p]: 1 for p in projects}, 1, 1)
    for p in projects:
        members = {x[i, p]: 1 for i in students}
        constraint({**members, active[p]: -low}, 0)
        constraint({**members, active[p]: -high}, upper=0)
        constraint({**members, active[p]: -target, deviation[p]: -1}, upper=0)
        constraint({**members, active[p]: -target, deviation[p]: 1}, 0)
    for i, j in combinations(students, 2):
        excluded = (
            j in pref[i]["incompatible_teammates"]
            or i in pref[j]["incompatible_teammates"]
        )
        coefficient = (
            weight
            * (scores[i]["teammates"].get(j, 0) + scores[j]["teammates"].get(i, 0))
            / (max(1, n - 2) * (target - 1))
        )
        for p in projects:
            if excluded:
                constraint({x[i, p]: 1, x[j, p]: 1}, upper=1)
            elif coefficient:
                z = variable(-coefficient)
                constraint({z: 1, x[i, p]: -1}, upper=0)
                constraint({z: 1, x[j, p]: -1}, upper=0)
                constraint({z: 1, x[i, p]: -1, x[j, p]: -1}, -1)

    started = time.monotonic()

    def optimize(cost):
        matrix = coo_matrix(
            (values, (row_index, col_index)), shape=(len(lower_bounds), len(objective))
        ).tocsc()
        return milp(
            np.asarray(cost),
            integrality=np.asarray(integrality),
            bounds=Bounds(np.zeros(len(objective)), upper),
            constraints=LinearConstraint(matrix, lower_bounds, upper_bounds),
            options={
                "time_limit": max(0.001, time_limit - (time.monotonic() - started)),
                "mip_rel_gap": 0.0,
            },
        )

    def decode(result):
        require(
            result.x is not None,
            "Solver returned no feasible assignment",
            "SOLVER_LIMIT",
        )
        assigned = {}
        for i in students:
            chosen = [p for p in projects if result.x[x[i, p]] > 0.5]
            require(
                len(chosen) == 1
                and all(
                    abs(result.x[x[i, p]] - round(result.x[x[i, p]])) < 1e-5
                    for p in projects
                ),
                "Nonintegral solver assignment",
                "INVALID_SOLUTION",
            )
            assigned[i] = chosen[0]
        return assigned

    def metadata(result):
        def finite(key):
            value = getattr(result, key, None)
            return float(value) if value is not None and math.isfinite(value) else None

        return {
            "status_code": int(result.status),
            "message": str(result.message),
            "optimal": result.status == 0,
            "objective": finite("fun"),
            "dual_bound": finite("mip_dual_bound"),
            "relative_gap": finite("mip_gap"),
        }

    size_cost = np.zeros(len(objective))
    size_cost[list(deviation.values())] = 1
    first = optimize(size_cost)
    if first.status == 2:
        raise RothError(
            "No feasible team assignment satisfies the size bounds and exclusions. Check incompatible pairs and project exclusions; no constraints were relaxed.",
            "INFEASIBLE",
        )
    require(
        first.status in (0, 1),
        f"Team size solver failed: {first.message}",
        "SOLVER_ERROR",
    )
    assignments = decode(first)
    evaluated = evaluate_assignment(market, preferences, assignments)
    phases = {"team_size": metadata(first)}
    optimal = False
    if first.status == 0:
        constraint(
            {idx: 1 for idx in deviation.values()},
            upper=evaluated["size_deviation"] + 1e-7,
        )
        second = optimize(objective)
        require(
            second.status in (0, 1),
            f"Preference solver failed: {second.message}",
            "SOLVER_ERROR",
        )
        phases["preferences"] = metadata(second)
        if second.x is not None:
            assignments = decode(second)
            updated = evaluate_assignment(market, preferences, assignments)
            require(
                updated["size_deviation"] == evaluated["size_deviation"],
                "Solver violated optimal team sizes",
                "INVALID_SOLUTION",
            )
            require(
                abs(updated["total_score"] + second.fun) < 1e-5,
                "Solver score disagrees with independently evaluated assignment",
                "INVALID_SOLUTION",
            )
            evaluated = updated
            optimal = second.status == 0
    return {
        "schema_version": "1.0",
        "mode": "teams",
        "method": "joint_borda_milp",
        "input_hash": digest({"market": market, "preferences": preferences}),
        "preference_sources": sorted({r["source"] for r in preferences}),
        "config": config,
        "assignments": assignments,
        **evaluated,
        "solution_status": "optimal" if optimal else "feasible_limit",
        "solver": {
            "name": "HiGHS via scipy.optimize.milp",
            "scipy_version": scipy.__version__,
            "time_limit_seconds": time_limit,
            "elapsed_seconds": time.monotonic() - started,
            "variables": len(objective),
            "constraints": len(lower_bounds),
            "phases": phases,
        },
        "scoring": {
            "borda": "M-rank over the full option universe; singleton gets 1",
            "unlisted": "0 points; retained as unranked, allowed unless explicitly excluded",
            "project_divisor": max(1, m - 1),
            "social_divisor": max(1, n - 2) * (target - 1),
            "objective_order": [
                "minimize total absolute team-size deviation",
                "maximize weighted Borda score",
            ],
            "guarantees": "Feasibility checked independently. No stability or strategy-proofness guarantee.",
        },
    }
