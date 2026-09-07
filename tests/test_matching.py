import random

import pytest

from roth import deferred_acceptance, verify_matching
from roth.common import RothError


def all_matchings(left, right):
    ids = list(left)

    def visit(i, used, pairs):
        if i == len(ids):
            yield pairs
            return
        yield from visit(i + 1, used, pairs)
        a = ids[i]
        for b in right:
            if b not in used and b in left[a] and a in right[b]:
                yield from visit(i + 1, used | {b}, pairs + [[a, b]])

    return visit(0, set(), [])


def oracle_stable(left, right, pairs):
    lp, rp = dict(pairs), {b: a for a, b in pairs}

    def better(order, new, old):
        return new in order and (old is None or order.index(new) < order.index(old))

    return not any(
        better(left[a], b, lp.get(a)) and better(right[b], a, rp.get(b))
        for a in left
        for b in right
        if lp.get(a) != b
    )


def test_known_proposer_difference():
    left = {"a": ["x", "y"], "b": ["y", "x"]}
    right = {"x": ["b", "a"], "y": ["a", "b"]}
    assert deferred_acceptance(left, right)["matches"] == [["a", "x"], ["b", "y"]]
    assert deferred_acceptance(left, right, "right")["matches"] == [
        ["a", "y"],
        ["b", "x"],
    ]


def test_random_markets_against_exhaustive_stable_set():
    rng = random.Random(101)
    for _ in range(90):
        left = {f"a{i}": [] for i in range(rng.randrange(1, 5))}
        right = {f"b{i}": [] for i in range(rng.randrange(1, 5))}
        for own, other in ((left, right), (right, left)):
            for p in own:
                own[p] = rng.sample(list(other), rng.randrange(len(other) + 1))
        stable = [
            m for m in all_matchings(left, right) if oracle_stable(left, right, m)
        ]
        assert stable
        for side in ("left", "right"):
            result = deferred_acceptance(left, right, side)
            assert result["matches"] in stable
            own = left if side == "left" else right
            actual = dict(
                result["matches"]
                if side == "left"
                else [e[::-1] for e in result["matches"]]
            )
            for candidate in stable:
                alternative = dict(
                    candidate if side == "left" else [e[::-1] for e in candidate]
                )
                for p, order in own.items():
                    rank = order.index(actual[p]) if p in actual else len(order)
                    other_rank = (
                        order.index(alternative[p]) if p in alternative else len(order)
                    )
                    assert rank <= other_rank


def test_verifier_detects_blocking_and_infeasibility():
    left, right = {"a": ["x"], "b": ["x"]}, {"x": ["a", "b"]}
    assert verify_matching(left, right, [["b", "x"]])["blocking_pairs"] == [["a", "x"]]
    assert not verify_matching(left, right, [["a", "x"], ["b", "x"]])["feasible"]
    assert not verify_matching(left, right, [["a", "missing"]])["stable"]


def test_empty_unbalanced_rejection():
    result = deferred_acceptance({"a": [], "b": ["x"]}, {"x": []})
    assert result["matches"] == []
    assert result["unmatched"]["a"] == "no_acceptable_candidates"
    assert result["unmatched"]["b"] == "no_mutually_acceptable_candidates"
    assert deferred_acceptance({}, {})["matches"] == []


@pytest.mark.parametrize(
    "left,right",
    [
        ({"a": ["x", "x"]}, {"x": ["a"]}),
        ({"a": ["z"]}, {"x": []}),
        ({"a": []}, {"a": []}),
    ],
)
def test_invalid_rankings(left, right):
    with pytest.raises(RothError):
        deferred_acceptance(left, right)
