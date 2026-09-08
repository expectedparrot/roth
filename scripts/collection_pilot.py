"""Offline synthetic pilot: questionnaire -> bound responses -> export -> solve.

No model inference, Humanize publication, or invitations. --native constructs
and reloads EDSL Results for every package using explicit fixture answers.
"""

import argparse
from contextlib import redirect_stdout
import io
from pathlib import Path

from roth.collection import (
    RANK,
    NEUTRAL,
    EXCLUDE,
    assessment,
    build_collection,
    build_rankings,
    collection_status,
    export_preferences,
    import_responses,
    load_collection,
)
from roth.common import write_json
from roth.review_example import review_example
from roth.team_example import classroom_example


def fixture_answers(col, fixture, stage):
    people = {r.get("student_id", r.get("reviewer_id")): r for r in fixture}
    result = []
    context = assessment(col)[2]
    for key, p in col["packages"].items():
        if (
            p["stage"] != stage
            or stage == "ranking"
            and p["assessment_hash"] != context
        ):
            continue
        row = people[p["participant_id"]]
        domain = p["domain"]
        answers = {}
        ranking = row[domain if col["mode"] == "teams" else "ranking"]
        if stage == "ranking":
            q = p["questions"][0]
            answers["ranking"] = sorted(
                q["question_options"],
                key=lambda label: ranking.index(q["mapping"][label]),
            )
        else:
            excluded = row[
                "unacceptable_projects"
                if domain == "projects"
                else "incompatible_teammates"
                if domain == "teammates"
                else "unacceptable"
            ]
            for q in p["questions"]:
                candidate = q.get("mapping", {}).get("candidate")
                answers[q["question_name"]] = (
                    q["question_options"][0]
                    if candidate is None
                    else EXCLUDE
                    if candidate in excluded
                    else RANK
                    if candidate in ranking
                    else NEUTRAL
                )
        result.append(
            {
                "package_id": key,
                "participant_id": p["participant_id"],
                "submission_id": "synthetic-pilot",
                "answers": answers,
            }
        )
    return result


def native_responses(col, rows, root):
    import edsl
    from edsl.results.result import Result
    from roth.edsl_bridge import field_results, load_object

    normalized = []
    root.mkdir()
    for row in rows:
        package = col["packages"][row["package_id"]]
        jobs = load_object("Jobs", Path(package["folder"]) / "jobs.ep")
        assert not jobs.models
        answers = dict(row["answers"])
        for q in package["questions"]:
            if q["kind"] == "rank":
                answers[q["question_name"]] = [
                    q["question_options"].index(x) for x in answers[q["question_name"]]
                ]
        for q in jobs.survey.questions:
            q._validate_answer({"answer": answers[q.question_name]})
        result = Result(
            agent=jobs.agents[0],
            scenario=edsl.Scenario({}),
            model=edsl.Model("test"),
            iteration=0,
            answer=answers,
            survey=jobs.survey,
        )
        results = edsl.Results(survey=jobs.survey, data=[result])
        path = root / (row["package_id"] + ".ep")
        with redirect_stdout(io.StringIO()):
            results.save(str(path))
        normalized.extend(field_results(path, col["packages"]))
    return normalized


def pilot(output, native=False):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    summary = {
        "synthetic": True,
        "native_results_roundtrip": native,
        "model_calls": 0,
        "invitations_sent": 0,
        "modes": {},
    }
    for mode, factory in [("teams", classroom_example), ("reviews", review_example)]:
        market, fixture = factory()
        directory = root / mode
        directory.mkdir()
        write_json(directory / "market.json", market)
        write_json(directory / "fixture-preferences.json", fixture)
        field = directory / "field"
        build_collection(mode, market, field, native=native)
        for stage in ["assessment", "ranking"]:
            if stage == "ranking":
                build_rankings(field)
            _, _, col = load_collection(field)
            rows = fixture_answers(col, fixture, stage)
            write_json(directory / (stage + "-synthetic-responses.json"), rows)
            if native:
                rows = native_responses(col, rows, directory / (stage + "-results"))
            import_responses(field, rows, source="synthetic")
        exported = export_preferences(field, directory / "collected-preferences.json")
        from roth.common import read_json

        prefs = read_json(exported["path"])
        if mode == "teams":
            from roth.teams import solve_teams
            from roth.team_report import export_team_report

            solved = solve_teams(market, prefs)
            export_team_report(market, prefs, solved, directory / "report")
        else:
            from roth.reviews import solve_reviews
            from roth.review_report import export_review_report

            solved = solve_reviews(market, prefs)
            export_review_report(market, prefs, solved, directory / "report")
        status = collection_status(field)
        summary["modes"][mode] = {
            "complete": status["complete"],
            "participants": status["participants"],
            "survey_packages": sum(len(r["packages"]) for r in status["rounds"]),
            "rounds": len(status["rounds"]),
            "solution_status": solved["solution_status"],
            "statistics": solved["statistics"],
            "preferences": exported["path"],
            "report": str(directory / "report/index.html"),
        }
    write_json(root / "summary.json", summary)
    return summary


if __name__ == "__main__":
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--native", action="store_true")
    args = parser.parse_args()
    print(json.dumps(pilot(args.directory, args.native), indent=2))
