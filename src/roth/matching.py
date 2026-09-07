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


def verify_matching(left, right, matches):
    _validate(left, right)
    errors, blocking = [], []
    lpartner, rpartner = {}, {}
    for pair in matches:
        require(
            isinstance(pair, (list, tuple)) and len(pair) == 2, "Matches must be pairs"
        )
        a, b = pair
        if a not in left or b not in right:
            errors.append({"pair": pair, "reason": "unknown_or_wrong_side"})
            continue
        if a in lpartner or b in rpartner:
            errors.append({"pair": pair, "reason": "capacity_violation"})
        if b not in left[a] or a not in right[b]:
            errors.append({"pair": pair, "reason": "not_mutually_acceptable"})
        lpartner[a], rpartner[b] = b, a
    lr = {p: {c: i for i, c in enumerate(r)} for p, r in left.items()}
    rr = {p: {c: i for i, c in enumerate(r)} for p, r in right.items()}
    for a in left:
        for b in left[a]:
            if a not in rr[b] or lpartner.get(a) == b:
                continue
            if lr[a][b] < lr[a].get(lpartner.get(a), float("inf")) and rr[b][a] < rr[
                b
            ].get(rpartner.get(b), float("inf")):
                blocking.append([a, b])
    return {
        "feasible": not errors,
        "stable": not errors and not blocking,
        "errors": errors,
        "blocking_pairs": blocking,
    }


def deferred_acceptance(left, right, proposing_side="left"):
    """Return pairs in left/right order; omitted candidates are unavailable edges.

    Stability concerns the supplied strict preferences, not unknown preferences.
    Each participant may remain unmatched, and capacities are exactly one.
    """
    _validate(left, right)
    require(proposing_side in {"left", "right"}, "Invalid proposing side")
    proposers, receivers = (left, right) if proposing_side == "left" else (right, left)
    ranks = {r: {p: i for i, p in enumerate(order)} for r, order in receivers.items()}
    queue = deque(sorted(proposers))
    next_index = dict.fromkeys(proposers, 0)
    held, trace = {}, []
    while queue:
        p = queue.popleft()
        if next_index[p] >= len(proposers[p]):
            continue
        r = proposers[p][next_index[p]]
        next_index[p] += 1
        previous = held.get(r)
        accepted = p in ranks[r] and (
            previous is None or ranks[r][p] < ranks[r][previous]
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
            held[r] = p
            if previous is not None:
                queue.append(previous)
        else:
            queue.append(p)
    matches = sorted(
        ([p, r] if proposing_side == "left" else [r, p]) for r, p in held.items()
    )
    check = verify_matching(left, right, matches)
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
                    "no_acceptable_candidates"
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
    }
