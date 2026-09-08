"""Small fictional classroom example with competing social/project rankings."""


def classroom_example():
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
    projects = [
        {"id": "climate", "name": "Campus climate dashboard"},
        {"id": "housing", "name": "Student housing survey"},
        {"id": "transit", "name": "Accessible campus transport"},
        {"id": "food", "name": "Food waste reduction"},
        {"id": "library", "name": "Library discovery tool"},
    ]
    students = [{"id": f"s{i + 1:02d}", "name": name} for i, name in enumerate(names)]
    market = {
        "schema_version": "1.0",
        "name": "Fictional student teams and projects",
        "synthetic": True,
        "students": students,
        "projects": projects,
        "config": {
            "target_size": 3,
            "allow_smaller": True,
            "allow_larger": True,
            "min_size": 2,
            "max_size": 4,
            "social_weight": 0.5,
        },
    }
    # Friendship circles conflict with project interests; these are hand-built
    # synthetic rankings, not survey responses or model-generated preferences.
    project_orders = [
        ["climate", "housing", "transit"],
        ["housing", "climate", "food"],
        ["transit", "housing", "library"],
        ["housing", "food", "climate"],
        ["food", "housing", "library"],
        ["climate", "transit", "housing"],
        ["transit", "library", "food"],
        ["library", "transit", "climate"],
        ["food", "transit", "housing"],
        ["food", "climate", "library"],
        ["climate", "food", "transit"],
        ["library", "food", "housing"],
    ]
    preferences = []
    for i, student in enumerate(students):
        circle = list(range((i // 3) * 3, (i // 3) * 3 + 3))
        peers = [j for j in circle if j != i] + [(i + 4) % len(students)]
        preferences.append(
            {
                "student_id": student["id"],
                "projects": project_orders[i],
                "teammates": [students[j]["id"] for j in peers],
                "unacceptable_projects": ["library"] if i == 0 else [],
                "incompatible_teammates": ["s12"] if i == 0 else [],
                "complete": True,
                "source": "synthetic",
            }
        )
    return market, preferences
