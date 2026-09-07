"""Fictional, reproducible internship fixtures. No generated model output."""

import random
from .market import validate_market


def internship_example(students=12, internships=10, seed=17):
    rng = random.Random(seed)
    roles = [
        "Data analysis",
        "Software development",
        "Policy research",
        "Design",
        "Climate research",
    ]
    skills = [
        "Python and statistics",
        "Python and web development",
        "Writing and economics",
        "Design and user research",
        "Python and environmental science",
    ]
    names = [
        "Alex",
        "Blair",
        "Casey",
        "Devon",
        "Emery",
        "Finley",
        "Gray",
        "Harper",
        "Indigo",
        "Jules",
        "Kai",
        "Lane",
    ]
    people = []
    for i in range(students):
        people.append(
            {
                "id": f"s{i + 1:03d}",
                "side": "left",
                "name": f"{names[i % len(names)]} {i + 1}",
                "profile": {
                    "skills": skills[i % 5],
                    "coursework": roles[i % 5],
                    "project": f"Completed a {roles[i % 5].lower()} team project",
                    "availability": "June–August",
                    "location": "Remote" if i % 3 else "Boston",
                },
                "preferences": f"I want {roles[i % 5].lower()} experience and strong mentoring. I prefer remote work and value learning over pay.",
                "contact": {"respondent_id": f"student-{i + 1}"},
            }
        )
    for i in range(internships):
        people.append(
            {
                "id": f"i{i + 1:03d}",
                "side": "right",
                "name": f"{roles[i % 5]} — Fictional Lab {i + 1}",
                "profile": {
                    "work": roles[i % 5],
                    "preferred_skills": skills[i % 5],
                    "dates": "June–August",
                    "hours_per_week": 30,
                    "location": "Remote" if i % 2 else "Boston",
                    "pay_per_hour_usd": 20 + 2 * (i % 6),
                    "mentoring": "Daily guidance" if i % 2 else "Weekly guidance",
                },
                "preferences": f"Seek {skills[i % 5]}. Value practical project experience and willingness to learn. Must be available June–August.",
                "contact": {"respondent_id": f"employer-representative-{i + 1}"},
            }
        )
    market = validate_market(
        {
            "name": "Fictional internship placement",
            "side_labels": {"left": "Students", "right": "Internships"},
            "synthetic": True,
            "participants": people,
            "config": {"delegation": "delegated"},
        }
    )
    rows = []
    for person in people:
        options = [p["id"] for p in people if p["side"] != person["side"]]
        rng.shuffle(options)
        rejected = options[-2:] if len(options) > 3 else []
        order = [p for p in options if p not in rejected]
        if person["id"] == f"s{students:03d}":
            rejected, order = options, []
        rows.append(
            {
                "participant_id": person["id"],
                "ranking": order,
                "unacceptable": rejected,
                "evaluated": options,
                "complete": True,
                "source": "synthetic",
                "confirmed": False,
            }
        )
    return market, rows
