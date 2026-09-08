"""Read-only guidance for the file-based review assignment workflow."""

import importlib.util
from pathlib import Path
import sys

from .common import RothError, digest, read_json
from .reviews import review_feasibility, validate_review_inputs, validate_review_market


def review_guidance(market, market_path, preferences_path, output, collection):
    from .agent import _response, action, fresh_path, question

    def response(phase, instruction, **details):
        return _response("reviews", phase, instruction, **details)

    if market is None:
        return response(
            "define_market",
            "Gather the reviewer roster, submissions and authorship, workload bounds, review counts, and conflicts. Resolve only missing decisions, then write market.json.",
            questions=[
                question(
                    "identities",
                    "Who reviews, which submissions need reviews, who authored each one, and which reviewers share a team?",
                ),
                question(
                    "counts",
                    "How many reviews does each submission require, and what are each reviewer's minimum and maximum workloads?",
                ),
                question(
                    "preferences",
                    "Should assignment quality use ranked choices (Borda), explicit expertise/preference scores from 0–100, or no preference objective?",
                ),
            ],
            input_contract={
                "market_file": str(market_path),
                "fields": [
                    "mode: reviews",
                    "reviewers: [{id, name, team?, min_reviews?, max_reviews?}]",
                    "submissions: [{id, title, authors: [reviewer IDs], reviews_required?}]",
                    "config: {min_reviews, max_reviews, reviews_per_submission, scoring: borda|scores|none, exclude_teammates}",
                    "excluded_pairs: [[reviewer_id, submission_id]]",
                ],
                "reference": "https://github.com/expectedparrot/roth/blob/main/docs/reviews.md",
            },
            explanation="Self-review is always forbidden. Teammate exclusions default on; declare teams/authors explicitly. Counts and conflicts are hard constraints. Authors who do not review can have min_reviews=max_reviews=0. This is score optimization, with no stability or strategy-proofness guarantee.",
        )
    try:
        market = validate_review_market(market)
    except RothError as error:
        return response(
            "repair_market",
            "Correct the review roster and organizer rules before solving.",
            issues=[str(error)],
        )
    if collection == "delegated":
        return response(
            "unsupported_collection",
            "Native delegated review scoring is not implemented. Collect explicit reviewer rankings or organizer-supplied scores; do not send review inputs through the two-sided score workflow.",
        )
    if not preferences_path.is_file() and market["config"]["scoring"] != "none":
        return response(
            "collect_preferences",
            "Collect one completed record per roster member and convert responses to the review preference contract. Reuse actual responses; never invent missing rankings or expertise scores.",
            input_contract={
                "preferences_file": str(preferences_path),
                "fields": [
                    "reviewer_id",
                    "ranking: [submission IDs] (borda mode) OR scores: {submission_id: 0..100} (scores mode)",
                    "unacceptable: [submission IDs]",
                    "complete: true",
                    "source: human|organizer|synthetic",
                ],
            },
            collection="Collect through a suitable survey or direct import. Use agent next --collection human for native review assessment/ranking or expertise surveys. Exclude self, teammate, and organizer-conflict options before collecting preferences.",
            scoring="Partial or empty completed records are valid: unranked/unscored eligible edges score zero and remain assignable. Explicit unacceptable options are forbidden. scoring=none accepts an empty array, deliberately omitting preference optimization.",
        )
    try:
        market, prefs = validate_review_inputs(
            market, read_json(preferences_path) if preferences_path.is_file() else []
        )
    except (RothError, ValueError) as error:
        return response(
            "repair_preferences",
            "Correct incomplete or invalid review preferences without changing declared conflicts.",
            issues=[str(error)],
        )
    checks = review_feasibility(market, prefs)
    if not checks["necessary_checks_pass"]:
        return response(
            "resolve_feasibility",
            "The requested counts cannot be satisfied under these rules. Explain the specific bottleneck and ask the organizer which input to revise; do not silently relax a count or conflict.",
            checks=checks,
        )
    input_hash = digest({"market": market, "preferences": prefs})
    if (output / "result.json").is_file():
        try:
            from .review_report import verify_review_result

            result = read_json(output / "result.json")
            if not isinstance(result, dict):
                raise RothError("Saved result is not an object")
            if result.get("input_hash") == input_hash:
                checked = verify_review_result(market, prefs, result)
                frozen_market, frozen_prefs = validate_review_inputs(
                    read_json(output / "market.json"),
                    read_json(output / "preferences.json"),
                )
                if (
                    digest({"market": frozen_market, "preferences": frozen_prefs})
                    != input_hash
                ):
                    raise RothError("Saved report inputs do not match the result")
                if (output / "index.html").is_file():
                    data = response(
                        "review_results",
                        "Explain the review assignments, submission coverage, workload bounds, conflicts, and assignments without an expressed preference. Discuss scores and any solver limit; do not claim stability or strategy-proofness.",
                        report=str(output / "index.html"),
                        statistics=checked["statistics"],
                        solution_status=result["solution_status"],
                        input_hash=input_hash,
                    )
                    data["complete"] = result["solution_status"] == "optimal"
                    if not data["complete"]:
                        data["questions"] = [
                            question(
                                "solver_limit",
                                "The saved allocation is feasible but not proven optimal. Accept it or rerun with more solver time into a new output directory?",
                            )
                        ]
                    return data
        except (RothError, ValueError, KeyError, TypeError, OSError) as error:
            return response(
                "inspect_result",
                "The saved review report failed verification. Preserve it and investigate before presenting it as valid.",
                issues=[str(error)],
            )
    destination = fresh_path(output)
    if importlib.util.find_spec("scipy") is None:
        checkout = Path(__file__).resolve().parents[2]
        install = [sys.executable, "-m", "pip", "install"] + (
            ["-e", f"{checkout}[reviews]"]
            if (checkout / "pyproject.toml").is_file()
            else ["roth[reviews] @ git+https://github.com/expectedparrot/roth.git@main"]
        )
        return response(
            "install_solver",
            "Install the optional review solver in Roth's environment, then rerun guidance.",
            actions=[
                action(
                    install,
                    "Install SciPy/HiGHS review solver",
                    mutates=True,
                    network=True,
                )
            ],
        )
    argv = ["roth", "reviews", "solve", market_path]
    if preferences_path.is_file():
        argv += ["--preferences", preferences_path]
    argv += ["--output", destination]
    return response(
        "solve",
        "Solve the review allocation and export frozen inputs, assignments, and a report. Necessary count checks pass; only solving can establish joint feasibility. No constraints will be relaxed.",
        config=market["config"],
        checks=checks,
        input_hash=input_hash,
        next_output=str(destination),
        actions=[
            action(argv, "Solve peer-review assignment and export report", mutates=True)
        ],
    )
