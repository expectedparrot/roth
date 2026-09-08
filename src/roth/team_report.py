"""Static, readable team reports built from frozen inputs and actual solutions."""

import csv
import html
from pathlib import Path

from .common import digest, require, write_json
from .teams import evaluate_assignment, score_tables, validate_team_inputs


def export_team_report(market, preferences, result, output):
    market, preferences = validate_team_inputs(market, preferences)
    require(
        result["input_hash"] == digest({"market": market, "preferences": preferences}),
        "Report input hash does not match the solved inputs",
    )
    checked = evaluate_assignment(market, preferences, result["assignments"])
    require(
        checked["teams"] == result["teams"]
        and abs(checked["total_score"] - result["total_score"]) < 1e-8,
        "Report result disagrees with assignment",
    )
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "market.json", market)
    write_json(root / "preferences.json", preferences)
    write_json(root / "result.json", result)
    scores = score_tables(market, preferences)
    write_json(root / "scores.json", scores)
    people = {
        p["id"]: p["name"] for side in ("students", "projects") for p in market[side]
    }
    rows = {r["student_id"]: r for r in preferences}

    def esc(value):
        return html.escape(str(value))

    def names(ids):
        return ", ".join(esc(people[i]) for i in ids) or "None"

    with (root / "assignments.csv").open("x", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "student_id",
                "student",
                "project_id",
                "project",
                "project_rank",
                "project_borda",
                "teammate_borda",
                "combined_score",
            ]
        )
        for row in result["students"]:
            writer.writerow(
                [
                    row["student_id"],
                    people[row["student_id"]],
                    row["project_id"],
                    people[row["project_id"]],
                    row["project_rank"],
                    row["project_borda"],
                    row["teammate_borda"],
                    row["combined_score"],
                ]
            )
    config = market["config"]
    team_cards = "".join(
        f'<div class="card"><h3>{esc(people[t["project_id"]])}</h3><p>{names(t["students"])}</p><small>{len(t["students"])} students</small></div>'
        for t in result["teams"]
    )
    preference_rows = "".join(
        f'<tr><th scope="row">{esc(people[r["student_id"]])}</th><td>{" → ".join(esc(people[p]) for p in r["projects"]) or "No ranked projects"}</td><td>{" → ".join(esc(people[i]) for i in r["teammates"]) or "No ranked teammates"}</td></tr>'
        for r in preferences
    )
    exclusions = "".join(
        f"<li>{esc(people[r['student_id']])}: excluded projects: {names(r['unacceptable_projects'])}; incompatible teammates: {names(r['incompatible_teammates'])}.</li>"
        for r in preferences
        if r["unacceptable_projects"] or r["incompatible_teammates"]
    )
    matrices = []
    for category, opposite, title in [
        ("projects", market["projects"], "Project rankings and assignments"),
        ("teammates", market["students"], "Teammate rankings and realized teams"),
    ]:
        cells = []
        for student in market["students"]:
            i = student["id"]
            cells.append(f'<tr><th scope="row">{esc(student["name"])}</th>')
            for option in opposite:
                j = option["id"]
                if category == "teammates" and i == j:
                    cells.append('<td class="self">—</td>')
                    continue
                ranked = j in rows[i][category]
                value = str(rows[i][category].index(j) + 1) if ranked else "·"
                rejected = (
                    j
                    in rows[i][
                        "unacceptable_projects"
                        if category == "projects"
                        else "incompatible_teammates"
                    ]
                )
                if category == "teammates":
                    rejected = rejected or i in rows[j]["incompatible_teammates"]
                if rejected:
                    value = "×"
                selected = result["assignments"][i] == (
                    j if category == "projects" else result["assignments"][j]
                )
                label = "ASSIGNED" if category == "projects" else "TEAM"
                badge = f"<small>{label}</small>" if selected else ""
                description = f"{people[i]} → {people[j]}: rank {value}; Borda {scores[i][category].get(j, 0)}"
                cells.append(
                    f'<td class="{"selected" if selected else "ordinary"}" data-student="{i}" data-option="{j}" title="{esc(description)}"><span>{value}</span>{badge}</td>'
                )
            cells.append("</tr>")
        headers = "".join(f'<th scope="col">{esc(p["name"])}</th>' for p in opposite)
        matrices.append(
            f'<h2>{title}</h2><div class="scroll" tabindex="0" role="region" aria-label="{title}"><table class="matrix" data-kind="{category}"><thead><tr><th scope="col">Student ↓</th>{headers}</tr></thead><tbody>{"".join(cells)}</tbody></table></div>'
        )
    outcomes = "".join(
        f'<tr><th scope="row">{esc(people[r["student_id"]])}</th><td>{esc(people[r["project_id"]])}</td><td>{r["project_rank"] if r["project_rank"] is not None else "Unranked"}</td><td>{r["project_borda"]}</td><td>{r["teammate_borda"]}</td><td>{r["combined_score"]:.3f}</td></tr>'
        for r in result["students"]
    )
    stats = result["statistics"]
    sources = ", ".join(result["preference_sources"])
    phase_rows = "".join(
        f"<tr><th>{esc(phase)}</th><td>{'Optimal' if info['optimal'] else 'Limit reached'}</td><td>{esc(info['relative_gap'])}</td></tr>"
        for phase, info in result["solver"]["phases"].items()
    )
    warning = (
        "The complete lexicographic optimum was found."
        if result["solution_status"] == "optimal"
        else "Time limit reached. This is a verified feasible assignment; optimality is not established for both stages."
    )
    content = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Roth · {esc(market.get("name", "Team assignment"))}</title>
<style>
:root{{--green:#214d35;--light:#edf7f1;--ink:#17251d;--line:#dce6df}}*{{box-sizing:border-box}}body{{margin:0;background:#f5f7f5;color:var(--ink);font:16px/1.7 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:48px 44px 80px;background:white}}h1,h2,h3{{font-family:Georgia,serif;color:var(--green);line-height:1.25}}h1{{font-size:42px}}h2{{margin-top:42px;border-top:1px solid var(--line);padding-top:24px}}h3{{margin-top:0}}a{{color:#2e7549}}.eyebrow{{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--green)}}.callout{{padding:18px 22px;background:var(--light);border-left:3px solid var(--green)}}.cards{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}.card{{padding:22px;border:1px solid var(--line);border-radius:6px}}.scroll{{overflow-x:auto;margin:22px 0}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:11px 10px;border-bottom:1px solid var(--line);text-align:left}}thead{{background:var(--light)}}.matrix{{min-width:800px;font-size:12px}}.matrix th,.matrix td{{text-align:center;vertical-align:middle}}.matrix th:first-child{{position:sticky;left:0;background:#f0f5f1;text-align:left;min-width:80px}}.matrix .selected{{background:var(--green);color:white;box-shadow:inset 0 0 0 2px white}}.matrix small{{display:block;font-size:8px;font-weight:bold}}.matrix .self{{background:#f3f3f3;color:#888}}pre{{background:#19271f;color:#e3eee6;padding:20px;overflow:auto;font-size:13px}}code{{overflow-wrap:anywhere}}.hash{{font-size:12px;overflow-wrap:anywhere}}small{{color:inherit}}@media(max-width:650px){{main{{padding:24px 18px 50px}}h1{{font-size:32px}}.cards{{grid-template-columns:1fr}}}}@media print{{main{{max-width:none;padding:0}}.scroll{{overflow:visible}}.matrix{{min-width:0}}}}
</style></head><body><main>
<p class="eyebrow">Roth · Joint team and project optimization</p>
<h1>{esc(market.get("name", "Team assignment"))}</h1>
<p>{len(market["students"])} students · {len(market["projects"])} available projects · {len(result["teams"])} teams · Preference source: <strong>{esc(sources)}</strong></p>
<p class="callout">{warning} Each student belongs to one team, and each used project has exactly one team. This is Borda-score optimization, with no claim of stability or strategy-proofness.</p>
<p><a href="#inputs">See the preference inputs</a> · <a href="#results">See assignments</a> · <a href="market.json">Market JSON</a> · <a href="preferences.json">Preference JSON</a> · <a href="scores.json">Borda scores</a> · <a href="result.json">Solver result</a> · <a href="assignments.csv">Assignment CSV</a></p>
<h2 id="inputs">The preferences we imported</h2>
<p>These are ordered lists, best first. They are inputs to the optimization, not inferred from its outcome. The bundled classroom example uses hand-built fictional rankings; no people, surveys, or model calls generated them.</p>
<div class="scroll"><table><thead><tr><th>Student</th><th>Projects, best first</th><th>Teammates, best first</th></tr></thead><tbody>{preference_rows}</tbody></table></div>
<p>Unlisted options earn zero Borda points and remain unranked; they are available unless explicitly excluded. A submitted empty list is different from a missing submission, which blocks solving.</p>
<p>Explicit hard exclusions (a teammate exclusion from either side prevents the pair):</p><ul>{exclusions or "<li>None.</li>"}</ul>
<h2>How rankings become the objective</h2>
<p>For M available options, rank r earns M − r Borda points. A sole option earns 1. The option count is the full project list or every other student, so submitting a shorter list does not change the points assigned to its first choice.</p>
<p>Project points are divided by {result["scoring"]["project_divisor"]}. The sum of each student's teammate points is divided by {result["scoring"]["social_divisor"]}: the highest peer Borda score times target size minus one. This uses the target size as a fixed reference; it does not average over realized team size, and a larger team can earn more social points.</p>
<p><strong>Student score = {1 - config["social_weight"]:g} × normalized project score + {config["social_weight"]:g} × normalized teammate score.</strong> Both directions of a teammate preference contribute. Scores are declared preference measures, not interpersonal cardinal welfare.</p>
<p>The organizer requests teams of {config["target_size"]}, allowing {config["min_size"]}–{config["max_size"]}. First the integer program minimizes total absolute deviation from the target among used teams. It then maximizes total student score while preserving that minimum deviation. Every stage assigns students and projects jointly.</p>
<h2 id="results">Realized teams and projects</h2><div class="cards">{team_cards}</div>
<p>Unused projects: {names(result["unused_projects"])}. Total size deviation: {result["size_deviation"]}. Total weighted score: {result["total_score"]:.3f}.</p>
<p><strong>{stats["project_first_choices"]}/{stats["students"]}</strong> students get their first-choice project; <strong>{stats["project_top_three"]}/{stats["students"]}</strong> get a top-three project; <strong>{stats["students_with_ranked_teammate"]}/{stats["students"]}</strong> receive at least one ranked teammate. {stats["unranked_project_assignments"]} students receive an unranked project.</p>
<p>Matrix cells show ranks (1 is best). Green cells labeled ASSIGNED or TEAM show realized outcomes. A dot means unranked; × means excluded; — is the diagonal. Read teammate rows directionally: Alex's rank of Blair may differ from Blair's rank of Alex.</p>
{"".join(matrices)}
<h2>Each student's score</h2><div class="scroll"><table><thead><tr><th>Student</th><th>Project</th><th>Project rank</th><th>Project Borda</th><th>Teammate Borda</th><th>Combined</th></tr></thead><tbody>{outcomes}</tbody></table></div>
<h2>Reproduce this result</h2><p>From this report directory, solve its frozen input files into a new output directory:</p>
<pre>roth teams solve market.json --preferences preferences.json --output rerun</pre>
<p>From a source checkout, install the optional solver with <code>python -m pip install -e '.[teams]'</code>. Solver: {esc(result["solver"]["name"])} · SciPy {esc(result["solver"]["scipy_version"])}.</p>
<div class="scroll"><table><thead><tr><th>Phase</th><th>Status</th><th>Relative MIP gap</th></tr></thead><tbody>{phase_rows}</tbody></table></div>
<p>The input snapshot, scores, assignments, solver bounds, and statuses are saved alongside this page. Existing output directories are never overwritten. Equal-score assignments may differ across solver versions.</p>
<p class="hash">Input SHA-256: {esc(result["input_hash"])}</p><p>Organizer report: contains everyone's private preference rankings.</p>
</main></body></html>"""
    (root / "index.html").write_text(content)
    return {
        "report": str((root / "index.html").resolve()),
        "directory": str(root.resolve()),
    }
