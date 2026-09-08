"""Reproduce the classroom example's tradeoff at three social weights."""

import argparse
from copy import deepcopy

from roth.common import write_json
from roth.team_example import classroom_example
from roth.teams import solve_teams


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New JSON output file")
    args = parser.parse_args()
    market, preferences = classroom_example()
    runs = []
    for weight in (0, 0.25, 0.5):
        variant = deepcopy(market)
        variant["config"]["social_weight"] = weight
        result = solve_teams(variant, preferences)
        runs.append({"social_weight": weight, "result": result})
    write_json(
        args.output,
        {
            "synthetic": True,
            "market": market,
            "preferences": preferences,
            "runs": runs,
            "note": "These are selected optimal assignments; ties may change individual memberships across solver versions.",
        },
    )
    print(args.output)


if __name__ == "__main__":
    main()
