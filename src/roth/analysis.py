"""Descriptive statistics with explicit denominators and coverage."""

from collections import Counter
from itertools import combinations
from statistics import mean
import random

from .market import eligible, participants


def rate(numerator, denominator):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def preference_statistics(market, preferences, active=None, matches=None):
    index, graph = participants(market), eligible(market)
    active = set(active if active is not None else index)
    partners = {p: [] for p in active}
    for a, b in matches or []:
        partners[a].append(b)
        partners[b].append(a)
    report = {}
    for side in ("left", "right"):
        ids = sorted(p for p in active if index[p]["side"] == side)
        respondents = [p for p in ids if p in preferences]
        orders = {
            p: [c for c in preferences[p]["ranking"] if c in active]
            for p in respondents
        }
        demand = Counter(order[0] for order in orders.values() if order)
        top3 = Counter(c for order in orders.values() for c in order[:3])
        exposure = Counter(
            c for p in respondents for c in preferences[p]["evaluated"] if c in active
        )
        all_ranks = {
            p: sorted(orders[p].index(c) + 1 for c in partners[p] if c in orders[p])
            for p in respondents
            if partners[p]
        }
        ranks = {
            p: rs[0]
            for p, rs in all_ranks.items()
            if index[p].get("capacity", 1) <= 1 and rs
        }
        flat_ranks = [r for rs in all_ranks.values() for r in rs]
        slots = sum(index[p].get("capacity", 1) for p in ids)
        filled = sum(len(partners[p]) for p in ids)
        common, agree = 0, 0
        # Bound diagnostic work independently of market size.
        rng = random.Random(17)
        sampled_respondents = sorted(rng.sample(respondents, min(30, len(respondents))))
        sampled_candidates = False
        for a, b in combinations(sampled_respondents, 2):
            ar, br = (
                {c: i for i, c in enumerate(orders[a])},
                {c: i for i, c in enumerate(orders[b])},
            )
            shared = sorted(set(ar) & set(br))
            sampled_candidates |= len(shared) > 20
            shared = sorted(rng.sample(shared, min(20, len(shared))))
            for c, d in combinations(shared, 2):
                common += 1
                agree += (ar[c] < ar[d]) == (br[c] < br[d])
        potential = sum(len(graph[p] & active) for p in ids)
        evaluated = sum(
            len(set(preferences[p]["evaluated"]) & active) for p in respondents
        )
        decided = sum(
            len(
                set(preferences[p]["ranking"] + preferences[p]["unacceptable"]) & active
            )
            for p in respondents
        )
        report[side] = {
            "participants": len(ids),
            "completion": rate(len(respondents), len(ids)),
            "evaluation_coverage": rate(evaluated, potential),
            "decision_coverage": rate(decided, potential),
            "unresolved_directions": potential - decided,
            "explicit_rejections": sum(
                len(set(preferences[p]["unacceptable"]) & active) for p in respondents
            ),
            "list_lengths": {p: len(order) for p, order in orders.items()},
            "first_choice_demand": dict(sorted(demand.items())),
            "top_3_demand": dict(sorted(top3.items())),
            "evaluated_exposure": dict(sorted(exposure.items())),
            "top_3_per_evaluation": {
                c: rate(top3[c], exposure[c]) for c in sorted(exposure)
            },
            "first_choice_hhi": sum(
                (n / sum(demand.values())) ** 2 for n in demand.values()
            )
            if demand
            else None,
            "common_candidate_order_agreement": rate(agree, common),
            "order_agreement_sampling": {
                "respondents": len(sampled_respondents),
                "respondent_population": len(respondents),
                "max_shared_candidates_per_pair": 20,
                "candidate_sampling_used": sampled_candidates,
                "seed": 17,
            },
            "match_rate": rate(sum(bool(partners[p]) for p in ids), len(ids)),
            "capacity": slots,
            "filled_slots": filled,
            "unfilled_slots": slots - filled,
            "slot_fill_rate": rate(filled, slots),
            "assigned_counts": {p: len(partners[p]) for p in ids},
            "assigned_partner_rank_lists": all_ranks,
            "assigned_partner_ranks": ranks,
            "mean_assigned_rank_among_matched": mean(flat_ranks)
            if flat_ranks
            else None,
            "top_1_assignment": rate(
                sum(1 in rs for rs in all_ranks.values()), len(ids)
            ),
            "top_3_assignment": rate(
                sum(any(r <= 3 for r in rs) for rs in all_ranks.values()), len(ids)
            ),
            "sources": dict(Counter(preferences[p]["source"] for p in respondents)),
        }
    mutual = []
    for p in sorted(active):
        if index[p]["side"] == "left" and p in preferences:
            for c in preferences[p]["ranking"][:3]:
                if (
                    c in active
                    and c in preferences
                    and p in preferences[c]["ranking"][:3]
                ):
                    mutual.append([p, c])
    return {
        "by_side": report,
        "mutual_top_3": mutual,
        "rank_scope": "submitted lists within the active cohort; not full-market ranks",
        "outcome_denominators": "match_rate and top_k_assignment count participants with at least one qualifying partner; slot_fill_rate counts filled capacity. Mean assigned rank counts each assignment. assigned_partner_ranks is the legacy scalar field for unit-capacity participants; rank_lists includes all assignments.",
        "note": "Ordinal ranks and model scores are not cardinal welfare. Exposure is evaluated exposure, not measured page views.",
    }
