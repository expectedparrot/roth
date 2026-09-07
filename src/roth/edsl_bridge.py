"""Optional, offline EDSL packaging. Execution is an explicit external ep action."""

from contextlib import redirect_stdout
import io
from pathlib import Path

from .common import RothError, require, write_json


def edsl_module():
    try:
        import edsl
    except ImportError as error:
        raise RothError(
            "Install roth[fielding] to build native EDSL artifacts",
            "MISSING_DEPENDENCY",
        ) from error
    return edsl


def load_object(kind, path):
    module = edsl_module()
    with redirect_stdout(io.StringIO()):
        return getattr(module, kind).load(str(path))


def build_survey_package(directory, questions, participant=None, package_id=None):
    module = edsl_module()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    native = []
    for question in questions:
        options = {k: v for k, v in question.items() if k not in {"kind", "mapping"}}
        kind = question["kind"]
        cls = {
            "rank": module.QuestionRank,
            "multiple_choice": module.QuestionMultipleChoice,
            "free_text": module.QuestionFreeText,
            "dict": module.QuestionDict,
        }[kind]
        native.append(cls(**options))
    survey = module.Survey(native)
    objects = {"survey": survey}
    if participant:
        traits = {
            "roth_participant_id": participant["id"],
            "roth_package_id": package_id,
        }
        email = participant.get("contact", {}).get("email")
        if email:
            traits["email"] = email
        agents = module.AgentList([module.Agent(name=participant["id"], traits=traits)])
        objects["agent_list"] = agents
        objects["jobs"] = module.Jobs(survey=survey, agents=agents)
    else:
        objects["jobs"] = module.Jobs(survey=survey)
    for name, obj in objects.items():
        with redirect_stdout(io.StringIO()):
            obj.save(str(directory / f"{name}.ep"))
    schema = {"questions": {q["question_name"]: {"optional": False} for q in questions}}
    write_json(directory / "humanize-schema.json", schema)
    if participant and participant.get("contact", {}).get("email"):
        write_json(directory / "delivery-map.json", {"email": {"col_name": "email"}})
    write_json(
        directory / "invitation-routes.json",
        [
            {
                "channel": "email",
                "subtype": "respondent",
                "delivery_template": {
                    "source": "expected_parrot",
                    "name": "respondent_invitation",
                },
                "respondent_filter": {
                    "type": "group",
                    "operator": "and",
                    "conditions": [{"type": "condition", "never_contacted": True}],
                },
            }
        ],
    )
    return {"edsl_version": module.__version__}


def build_score_jobs(directory, tasks, plan_id):
    module = edsl_module()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    question = module.QuestionDict(
        question_name="evaluation",
        question_text="{{ task }}",
        answer_keys=["acceptability", "score", "evidence", "explanation"],
        value_types=["str", "float", "list[str]", "str"],
        value_descriptions=[
            "acceptable, unacceptable, or unknown",
            "Within-person desirability from 0 to 100",
            "Criterion and profile evidence; identify missing facts",
            "Concise reason",
        ],
    )
    survey = module.Survey([question])
    scenarios = module.ScenarioList(
        [
            module.Scenario(
                {"task_id": t["task_id"], "plan_id": plan_id, "task": t["prompt"]}
            )
            for t in tasks
        ]
    )
    jobs = module.Jobs(survey=survey, scenarios=scenarios)
    with redirect_stdout(io.StringIO()):
        survey.save(str(directory / "survey.ep"))
        scenarios.save(str(directory / "scenarios.ep"))
        jobs.save(str(directory / "jobs.ep"))
    return {
        "edsl_version": module.__version__,
        "jobs": str((directory / "jobs.ep").resolve()),
    }


def field_results(path, packages):
    results = load_object("Results", path)
    rows = []
    for result in results:
        data = result.to_dict()
        traits = data.get("agent", {}).get("traits", {})
        package_id = traits.get("roth_package_id")
        require(package_id in packages, "Results missing a registered roth_package_id")
        require(
            traits.get("roth_participant_id") == packages[package_id]["participant_id"],
            "Respondent identity mismatch",
        )
        actual_questions = {q.question_name: q for q in results.survey.questions}
        expected_questions = packages[package_id]["questions"]
        require(
            set(actual_questions) == {q["question_name"] for q in expected_questions},
            "Results survey question set differs from registered package",
        )
        for expected in expected_questions:
            actual = actual_questions[expected["question_name"]]
            require(
                actual.question_text == expected["question_text"],
                "Results survey text differs from registered package",
            )
            if "question_options" in expected:
                require(
                    actual.question_options == expected["question_options"],
                    "Results survey option order differs from registered package",
                )
        answers = dict(data.get("answer", {}))
        require(isinstance(answers, dict), "Invalid EDSL answers")
        # Native rank responses may use zero-based option codes. Resolve only
        # against the frozen package order; JSON imports use exact labels.
        for question in packages[package_id]["questions"]:
            key = question["question_name"]
            value = answers.get(key)
            if (
                question["kind"] == "rank"
                and isinstance(value, list)
                and value
                and all(type(x) is int for x in value)
            ):
                options = question["question_options"]
                require(
                    all(0 <= x < len(options) for x in value),
                    "Out-of-range native ranking code",
                )
                answers[key] = [options[x] for x in value]
        from .common import digest

        rows.append(
            {
                "package_id": package_id,
                "participant_id": traits["roth_participant_id"],
                "submission_id": digest(data),
                "answers": answers,
                "raw_result": data,
            }
        )
    return rows


def score_results(path, plan):
    rows = []
    tasks = {t["task_id"]: t for t in plan["tasks"]}
    for result in load_object("Results", path):
        data = result.to_dict()
        scenario = data.get("scenario", {})
        require(
            scenario.get("plan_id") == plan["id"],
            "Model Results belong to a different plan",
        )
        require(scenario.get("task_id") in tasks, "Unknown scoring task")
        require(
            scenario.get("task") == tasks[scenario["task_id"]]["prompt"],
            "Scoring prompt differs from the frozen plan",
        )
        evaluation = data.get("answer", {}).get("evaluation")
        require(isinstance(evaluation, dict), "Missing or invalid model evaluation")
        rows.append(
            {
                "task_id": scenario.get("task_id"),
                **evaluation,
                "model": data.get("model"),
                "raw_result": data,
            }
        )
    return rows
