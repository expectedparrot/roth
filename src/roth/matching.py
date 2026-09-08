"""Deterministic deferred acceptance and an independent blocking-pair verifier."""

from collections import deque

from .common import require


def _validate(left, right):
    require(
        isinstance(left, dict) and isinstance(right, dict),
        "Preferences must be dictionaries",
    )
    require(not set(left) & set(right), "Sides must have disjoint IDs")
    for side, other in ((left, right), (right, left)):
        for pid, ranking in side.items():
            require(
                isinstance(ranking, list) and all(isinstance(x, str) for x in ranking),
                f"Invalid ranking for {pid}",
            )
            require(
                len(ranking) == len(set(ranking)), f"Duplicate preference for {pid}"
            )
            require(
                set(ranking) <= set(other), f"Unknown candidate in ranking for {pid}"
            )


def validate_capacities(left, right, capacities=None):
    """Default omitted IDs to one; only one side may have quotas above one."""
    capacities = {} if capacities is None else capacities
    require(isinstance(capacities, dict), "capacities must be an ID-to-integer object")
    require(set(capacities) <= set(left) | set(right), "Unknown capacity participant")
    result = {p: capacities.get(p, 1) for p in (*left, *right)}
    require(
        all(type(q) is int and q >= 0 for q in result.values()),
        "Capacity must be a nonnegative integer",
    )
    require(
        not (any(result[p] > 1 for p in left) and any(result[p] > 1 for p in right)),
        "Many-to-many capacities are not supported; only one side may exceed one",
    )
    return result


def verify_matching(left, right, matches, capacities=None):
    _validate(left, right)
    quotas = validate_capacities(left, right, capacities)
    errors, blocking = [], []
    partners = {p: set() for p in (*left, *right)}
    for pair in matches:
        require(
            isinstance(pair, (list, tuple)) and len(pair) == 2, "Matches must be pairs"
        )
        a, b = pair
        if a not in left or b not in right:
            errors.append({"pair": pair, "reason": "unknown_or_wrong_side"})
            continue
        if b in partners[a]:
            errors.append({"pair": pair, "reason": "duplicate_pair"})
        partners[a].add(b)
        partners[b].add(a)
        if len(partners[a]) > quotas[a] or len(partners[b]) > quotas[b]:
            errors.append({"pair": pair, "reason": "capacity_violation"})
        if b not in left[a] or a not in right[b]:
            errors.append({"pair": pair, "reason": "not_mutually_acceptable"})
    lr = {p: {c: i for i, c in enumerate(r)} for p, r in left.items()}
    rr = {p: {c: i for i, c in enumerate(r)} for p, r in right.items()}
    for a in left:
        for b in left[a]:
            if a not in rr[b] or b in partners[a]:
                continue

            def willing(p, candidate, ranks):
                return quotas[p] > 0 and (
                    len(partners[p]) < quotas[p]
                    or any(
                        ranks[candidate] < ranks.get(old, float("inf"))
                        for old in partners[p]
                    )
                )

            if willing(a, b, lr[a]) and willing(b, a, rr[b]):
                blocking.append([a, b])
    return {
        "feasible": not errors,
        "stable": not errors and not blocking,
        "errors": errors,
        "blocking_pairs": blocking,
    }


def deferred_acceptance(left, right, proposing_side="left", capacities=None):
    """Return pairs in left/right order; omitted candidates are unavailable edges.

    Stability concerns the supplied strict preferences, not unknown preferences.
    Capacities map participant IDs to nonnegative integers, defaulting to one.
    Only one side may exceed one. Preferences over sets must be responsive:
    accept each ranked partner into a vacant slot and prefer higher-ranked
    individuals independently of other partners. Either side may propose.
    """
    _validate(left, right)
    quotas = validate_capacities(left, right, capacities)
    require(proposing_side in {"left", "right"}, "Invalid proposing side")
    proposers, receivers = (left, right) if proposing_side == "left" else (right, left)
    ranks = {r: {p: i for i, p in enumerate(order)} for r, order in receivers.items()}
    queue = deque(sorted(proposers))
    next_index = dict.fromkeys(proposers, 0)
    held = {r: set() for r in receivers}
    assigned = {p: set() for p in proposers}
    trace = []
    while queue:
        p = queue.popleft()
        if len(assigned[p]) >= quotas[p] or next_index[p] >= len(proposers[p]):
            continue
        r = proposers[p][next_index[p]]
        next_index[p] += 1
        previous = (
            max(held[r], key=ranks[r].get)
            if held[r] and len(held[r]) >= quotas[r]
            else None
        )
        accepted = (
            quotas[r] > 0
            and p in ranks[r]
            and (
                len(held[r]) < quotas[r]
                or (previous is not None and ranks[r][p] < ranks[r][previous])
            )
        )
        trace.append(
            {
                "proposer": p,
                "receiver": r,
                "accepted": accepted,
                "displaced": previous if accepted else None,
            }
        )
        if accepted:
            held[r].add(p)
            assigned[p].add(r)
            if previous is not None:
                held[r].remove(previous)
                assigned[previous].remove(r)
                queue.append(previous)
        if len(assigned[p]) < quotas[p]:
            queue.append(p)
    matches = sorted(
        ([p, r] if proposing_side == "left" else [r, p])
        for r, ps in held.items()
        for p in ps
    )
    check = verify_matching(left, right, matches, quotas)
    require(
        check["stable"],
        "Internal error: matching failed verification",
        "INTERNAL_ERROR",
    )
    matched = {x for edge in matches for x in edge}
    unmatched = {}
    for side, other in ((left, right), (right, left)):
        for pid, order in side.items():
            if pid not in matched:
                unmatched[pid] = (
                    "zero_capacity"
                    if quotas[pid] == 0
                    else "no_acceptable_candidates"
                    if not order
                    else "no_mutually_acceptable_candidates"
                    if not any(pid in other[c] for c in order)
                    else "no_partner_in_stable_outcome"
                )
    return {
        "matches": matches,
        "unmatched": unmatched,
        "proposing_side": proposing_side,
        "trace": trace,
        "verification": check,
        "capacities": quotas,
        "vacancies": {
            p: quotas[p] - sum(p in edge for edge in matches) for p in quotas
        },
    }
