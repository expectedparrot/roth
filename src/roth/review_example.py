"""Explicit fictional classroom rankings for peer-review allocation."""

import random

from .reviews import exclusion_reasons, validate_review_inputs


def review_example(seed=41):
    topics = ["Climate", "Education", "Labor", "Technology"]
    reviewers = [
        {
            "id": f"s{i + 1:02d}",
            "name": f"Fictional Student {i + 1}",
            "team": f"t{i // 3 + 1}",
        }
        for i in range(12)
    ]
    submissions = [
        {
            "id": f"p{i + 1:02d}",
            "title": f"{topics[i % 4]} essay {i + 1}",
            "authors": [r["id"]],
            "description": f"A fictional classroom essay about {topics[i % 4].lower()}.",
        }
        for i, r in enumerate(reviewers)
    ]
    market = {
        "mode": "reviews",
        "name": "Fictional classroom peer review",
        "synthetic": True,
        "reviewers": reviewers,
        "submissions": submissions,
        "config": {
            "min_reviews": 3,
            "max_reviews": 3,
            "reviews_per_submission": 3,
            "scoring": "borda",
            "exclude_teammates": True,
        },
        "excluded_pairs": [["s01", "p04"]],
    }
    blocked = exclusion_reasons(market)
    rng = random.Random(seed)
    prefs = []
    for i, r in enumerate(reviewers):
        choices = [p["id"] for p in submissions if (r["id"], p["id"]) not in blocked]
        rng.shuffle(choices)
        choices.sort(key=lambda p: (int(p[1:]) - 1) % 4 != i % 4)
        unacceptable = choices[-1:] if i == 1 else []
        prefs.append(
            {
                "reviewer_id": r["id"],
                "ranking": [p for p in choices if p not in unacceptable],
                "unacceptable": unacceptable,
                "complete": True,
                "source": "synthetic",
            }
        )
    return validate_review_inputs(market, prefs)
