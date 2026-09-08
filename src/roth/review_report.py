"""Immutable peer-review reports with inspectable inputs and assignment matrices."""

import csv
import html
from pathlib import Path

from .common import digest, require, write_json
from .reviews import (
    evaluate_reviews,
    review_edges,
    review_scores,
    validate_review_inputs,
)


def verify_review_result(market, preferences, result):
    market, preferences = validate_review_inputs(market, preferences)
    require(
        isinstance(result, dict)
        and result.get("input_hash")
        == digest({"market": market, "preferences": preferences}),
        "Review result belongs to different inputs",
        "INVALID_SOLUTION",
    )
    require(
        result.get("mode") == "reviews"
        and result.get("scoring") == market["config"]["scoring"],
        "Incorrect review result mode or scoring",
        "INVALID_SOLUTION",
    )
    checked = evaluate_reviews(market, preferences, result.get("assignments"))
    require(
        all(result.get(k) == v for k, v in checked.items()),
        "Saved review outcomes or scores disagree with independent verification",
        "INVALID_SOLUTION",
    )
    require(
        result.get("solution_status") in ("optimal", "feasible_limit")
        and isinstance(result.get("solver"), dict)
        and result["solver"].get("optimal") is (result["solution_status"] == "optimal"),
        "Inconsistent solver status",
        "INVALID_SOLUTION",
    )
    return checked


def export_review_report(raw_market, raw_preferences, result, output):
    market, preferences = validate_review_inputs(raw_market, raw_preferences)
    verify_review_result(market, preferences, result)
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    for filename, value in (
        ("submitted-market.json", raw_market),
        ("submitted-preferences.json", raw_preferences),
        ("market.json", market),
        ("preferences.json", preferences),
        ("result.json", result),
        ("scores.json", review_scores(market, preferences)),
    ):
        write_json(directory / filename, value)
    reviewers = {r["id"]: r for r in market["reviewers"]}
    papers = {p["id"]: p for p in market["submissions"]}
    with (directory / "assignments.csv").open("x", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "reviewer_id",
                "reviewer_name",
                "submission_id",
                "submission_title",
                "rank",
                "score",
            ]
        )
        for o in result["outcomes"]:
            writer.writerow(
                [
                    o["reviewer_id"],
                    reviewers[o["reviewer_id"]]["name"],
                    o["submission_id"],
                    papers[o["submission_id"]]["title"],
                    o["rank"],
                    o["score"],
                ]
            )

    def esc(value):
        return html.escape(str(value))

    workloads = "".join(
        f"<tr><th>{esc(r['name'])}</th><td>{r['min_reviews']}–{r['max_reviews']}</td><td>{len(result['reviewers'][rid])}</td><td>{', '.join(esc(papers[p]['title']) for p in result['reviewers'][rid]) or 'None'}</td></tr>"
        for rid, r in reviewers.items()
    )
    coverage = "".join(
        f"<tr><th>{esc(p['title'])}</th><td>{p['reviews_required']}</td><td>{len(result['submissions'][pid])}</td><td>{', '.join(esc(reviewers[r]['name']) for r in result['submissions'][pid]) or 'None'}</td></tr>"
        for pid, p in papers.items()
    )
    edges, reasons = review_edges(market, preferences)
    assigned = set(map(tuple, result["assignments"]))
    rows = {r["reviewer_id"]: r for r in preferences}
    mode = market["config"]["scoring"]
    if len(reviewers) * len(papers) <= 2500:
        matrix_rows = []
        for rid, r in reviewers.items():
            cells = []
            for pid in papers:
                why = reasons.get((rid, pid), [])
                row = rows.get(rid, {})
                value = (
                    "×"
                    if why
                    else str(row["ranking"].index(pid) + 1)
                    if pid in row.get("ranking", [])
                    else str(row["scores"][pid])
                    if pid in row.get("scores", {})
                    else "—"
                )
                chosen = (rid, pid) in assigned
                cells.append(
                    f'<td class="{"assigned" if chosen else "excluded" if why else ""}" title="{esc(", ".join(why))}">{esc(value)}{" ✓" if chosen else ""}</td>'
                )
            matrix_rows.append(
                f'<tr><th scope="row">{esc(r["name"])} [{esc(rid)}]</th>{"".join(cells)}</tr>'
            )
        columns = "".join(
            f'<th scope="col">{esc(pid)}<br>{esc(p["title"])}</th>'
            for pid, p in papers.items()
        )
        matrix = f'<div class="scroll"><table class="matrix"><thead><tr><th>Reviewer / submission</th>{columns}</tr></thead><tbody>{"".join(matrix_rows)}</tbody></table></div>'
    else:
        matrix = "<p>The matrix exceeds 2,500 cells; inspect the complete inputs and assignments CSV instead.</p>"
    explanation = {
        "borda": "Cells show the reviewer’s submitted rank (1 is best). The objective uses normalized Borda points over that reviewer’s organizer-eligible options; unranked options score zero.",
        "scores": "Cells show the supplied expertise/preference score (0–100). The objective divides these scores by 100; unscored options score zero.",
        "none": "No preference scores were used; this is a feasible allocation within the requested bounds.",
    }[mode]
    stats = result["statistics"]
    verdict = (
        "Optimal assignment found."
        if result["solution_status"] == "optimal"
        else "Feasible assignment found; the time limit prevented proof of optimality."
    )
    content = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Roth — peer review</title>
<style>body{{font:17px system-ui;max-width:1100px;margin:40px auto;padding:0 24px;background:#fafcfb;color:#173239}}h1,h2{{color:#12675e}}table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;border-bottom:1px solid #ccd;text-align:left}}.scroll{{overflow:auto}}.matrix td{{text-align:center;white-space:nowrap}}.assigned{{background:#d5eee2;outline:2px solid #12675e;outline-offset:-2px;font-weight:bold}}.excluded{{color:#777;background:#eee}}.callout{{padding:18px;background:#edf4ef;border-left:4px solid #12675e}}a{{color:#12675e}}</style></head><body>
<h1>{esc(market.get("name", "Peer-review assignments"))}</h1>
<p class="callout">{verdict} Coverage, workloads, and exclusions were independently verified. No stability or strategy-proofness guarantee.</p>
<p>{stats["assignments"]} assignments · {stats["reviewers"]} roster members · {stats["submissions"]} submissions · {stats["min_reviewer_load"]}–{stats["max_reviewer_load"]} reviews per person</p>
<p>Sources: {esc(", ".join(result["sources"]) or "organizer constraints only")}. This report contains organizer-visible preferences and authorship.</p>
<h2>Where the inputs came from</h2><p><a href="submitted-market.json">Submitted roster, authors, and rules</a> · <a href="submitted-preferences.json">Submitted preferences</a> · <a href="market.json">Normalized market</a> · <a href="preferences.json">Normalized preferences</a> · <a href="scores.json">Objective scores</a></p>
<p>Scoring mode: {esc(mode)}. {explanation} Omission is not rejection: unranked or unscored eligible submissions may be assigned. Hard exclusions cannot be assigned.</p>
<h2>Preferences and realized assignments</h2><p>✓ and green mark assignments. × marks a hard exclusion (hover for its reason). — means no expressed preference. Each row is a reviewer; each column is a submission.</p>{matrix}
<h2>Reviewer workloads and tasks</h2><table><thead><tr><th>Reviewer</th><th>Allowed workload</th><th>Assigned</th><th>Submissions to review</th></tr></thead><tbody>{workloads}</tbody></table>
<h2>Submission coverage</h2><table><thead><tr><th>Submission</th><th>Required</th><th>Assigned</th><th>Reviewers</th></tr></thead><tbody>{coverage}</tbody></table>
<h2>Preference outcomes</h2><p>Total normalized score: {result["total_score"]:.4f}. Assignments in a reviewer’s top three: {esc(stats["top_three_assignments"] if mode == "borda" else "not applicable")}. Assignments without an expressed preference: {esc(stats["assignments_without_expressed_preference"] if mode != "none" else "not applicable")}.</p>
<p>These counts use assignments as the denominator ({stats["assignments"]}), not people. Borda ranks are ordinal; total score is an allocation objective, not measured welfare. Workload bounds constrain load; wider bounds do not imply equal loads.</p>
<h2>Solver and reproducibility</h2><p>{esc(result["solver"].get("message", ""))} Score upper bound: {esc(result["solver"].get("score_upper_bound"))}; relative gap: {esc(result["solver"].get("relative_gap"))}.</p><p>Equal-score optima can differ. Frozen input hash: <code>{esc(result["input_hash"])}</code>.</p><p><a href="result.json">Full verified result</a> · <a href="assignments.csv">Assignments CSV</a></p></body></html>"""
    (directory / "index.html").write_text(content)
    return {
        "report": str((directory / "index.html").resolve()),
        "directory": str(directory.resolve()),
    }
