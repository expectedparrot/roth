"""Read-only next steps for collected team/review preferences."""

import importlib.util
from pathlib import Path
import sys

from .common import RothError, digest, read_json


def collection_guidance(
    mode, market, market_path, preferences_path, directory, contacts
):
    from .agent import _response, action, question
    from .collection import collection_status, load_collection, validate_market

    def response(phase, instruction, **details):
        return _response(mode, phase, instruction, **details)

    try:
        market = validate_market(mode, market)
    except RothError as error:
        return response(
            "repair_market",
            "Correct the market before collecting human preferences.",
            issues=[str(error)],
        ), preferences_path
    prefix = ["roth", mode, "field"]
    if not (directory / ".roth").is_dir():
        if directory.exists():
            return response(
                "inspect_collection",
                "The collection path is occupied without a saved collection. Inspect it or select a new --field-dir; do not overwrite its artifacts.",
            ), preferences_path
        if importlib.util.find_spec("edsl") is None:
            checkout = Path(__file__).resolve().parents[2]
            install = [sys.executable, "-m", "pip", "install"] + (
                ["-e", f"{checkout}[fielding]"]
                if (checkout / "pyproject.toml").is_file()
                else [
                    "roth[fielding] @ git+https://github.com/expectedparrot/roth.git@main"
                ]
            )
            return response(
                "install_fielding",
                "Install the optional EDSL fielding dependency to build native Humanize artifacts.",
                actions=[
                    action(
                        install,
                        "Install native fielding extra",
                        mutates=True,
                        network=True,
                    )
                ],
            ), preferences_path
        argv = prefix + ["build", market_path, "--output", directory]
        if contacts:
            argv += ["--contacts", contacts]
        return response(
            "build_surveys",
            "Build private respondent-bound Humanize packages and previews. Assess options in batches, then rank the selected options across batches. No preference gives zero score and remains assignable; exclusions are hard constraints.",
            questions=[]
            if contacts
            else [
                question(
                    "contacts",
                    "Where is the respondent-ID contact map for email invitations? It can be omitted while preparing previews; build a new collection with contacts before email recruitment.",
                )
            ],
            actions=[
                action(
                    argv,
                    "Build survey previews and native Humanize handoffs",
                    mutates=True,
                )
            ],
            field_dir=str(directory),
        ), preferences_path
    _, _, col = load_collection(directory, mode)
    if contacts:
        supplied = read_json(contacts)
        if (
            not isinstance(supplied, dict)
            or set(supplied) - set(col["people"])
            or any(
                p["contact"] != supplied.get(pid, {})
                for pid, p in col["people"].items()
            )
        ):
            return response(
                "resolve_contact_revision",
                "The contact map differs from the frozen survey recipients. Preserve this collection and build a new --field-dir with the intended contacts before recruitment.",
            ), preferences_path
    if col["market_hash"] != digest(market):
        return response(
            "resolve_collection_revision",
            "This collection belongs to a different market. Preserve it and build a new --field-dir for the revised roster or rules.",
        ), preferences_path
    status = collection_status(directory)
    if status["complete"]:
        for exported in reversed(status["exports"]):
            path = Path(exported["path"])
            if (
                exported["preferences_hash"] == status["preferences_hash"]
                and exported["assessment_hash"] == status["assessment_hash"]
            ):
                if (
                    not path.is_file()
                    or digest(read_json(path)) != exported["preferences_hash"]
                ):
                    return response(
                        "inspect_collected_preferences",
                        "A previously exported preference file is missing or changed. Preserve the record and investigate before solving.",
                    ), preferences_path
                return None, path
        destination = preferences_path
        count = 2
        while (
            destination.exists()
            or destination.with_name(destination.name + ".collection.json").exists()
        ):
            destination = preferences_path.with_name(
                f"{preferences_path.stem}-{count}{preferences_path.suffix}"
            )
            count += 1
        return response(
            "export_preferences",
            "All required human responses are complete. Export a new preference file with provenance, preserving any prior inputs.",
            actions=[
                action(
                    prefix + ["export", directory, "--output", destination],
                    "Export collected preference records",
                    mutates=True,
                )
            ],
            next_preferences=str(destination),
            progress=status,
        ), preferences_path
    if status["missing_assessment_packages"]:
        phase = "collect_assessments"
        explanation = "Review the assessment preview and Humanize handoff. Within organizer authorization, create and register each survey, deliver invitations, retrieve responses, and import Results with field import --edsl. Track missing participants; never substitute synthetic answers for nonresponses."
        actions = []
    elif any(r["package_id"] is None for r in status["ranking_needed"]):
        over = [
            r
            for r in status["ranking_needed"]
            if len(r["selected"]) > col["max_options"]
        ]
        if over:
            return response(
                "resolve_ranking_budget",
                "Selected options exceed the ranking budget. Ask respondents to revise selections or explicitly raise --max-options for field rank. Do not truncate selections or treat unselected options as exclusions.",
                progress=status,
                questions=[
                    question(
                        "ranking_budget",
                        "Should the ranking budget be raised, or should respondents revise their selected options?",
                    )
                ],
            ), preferences_path
        phase = "build_rankings"
        explanation = "Assessments are complete. Build a cross-batch ranking round for each domain with more than one selected option."
        actions = [
            action(
                prefix + ["rank", directory],
                "Build cross-batch rank surveys",
                mutates=True,
            )
        ]
    else:
        phase = "collect_rankings"
        explanation = "Collect and import the current cross-batch ranking Results using the saved Humanize handoffs. Older rounds are invalid after assessment revisions."
        actions = []
    if not status["native"]:
        explanation += " This collection is a JSON-only preview: import explicit JSON responses for an offline dry run, or build a new native collection before Humanize recruitment. Its handoff does not contain usable native Jobs artifacts."
    return response(
        phase,
        explanation,
        actions=actions,
        progress=status,
        handoff_files=[r["handoff"] for r in status["rounds"]],
        status_command=[str(x) for x in prefix + ["status", directory]],
        import_template=[
            str(x) for x in prefix + ["import", directory, "<results.ep>", "--edsl"]
        ],
    ), preferences_path
