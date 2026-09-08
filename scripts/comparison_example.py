"""Reproduce organizer comparisons on the synthetic classroom team fixture."""

import argparse
from pathlib import Path

from roth.common import write_json
from roth.comparison import compare_reports
from roth.team_example import classroom_example
from roth.team_report import export_team_report
from roth.teams import solve_teams


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="New directory for baseline and comparison")
    args = parser.parse_args()
    root = Path(args.directory)
    root.mkdir(parents=True, exist_ok=False)
    market, preferences = classroom_example()
    # Start with exact teams of three so allowing four is an actual rule change.
    market["config"].update(
        allow_smaller=False, allow_larger=False, min_size=3, max_size=3
    )
    export_team_report(
        market, preferences, solve_teams(market, preferences), root / "report"
    )
    scenarios = [
        {"name": "allow-four", "config": {"allow_larger": True, "max_size": 4}},
        {
            "name": "target-four",
            "config": {"target_size": 4, "min_size": 4, "max_size": 4},
        },
        {"name": "close-climate", "close_projects": ["climate"]},
        {"name": "project-priority", "config": {"social_weight": 0.25}},
        {
            "name": "too-few-projects",
            "close_projects": ["climate", "housing", "transit"],
        },
    ]
    write_json(root / "scenarios.json", scenarios)
    print(compare_reports(root / "report", scenarios, root / "comparison")["report"])


if __name__ == "__main__":
    main()
