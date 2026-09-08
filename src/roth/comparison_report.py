"""Static comparison tables with inspectable inputs and participant-level CSV."""

import csv
import html
import json


def export_comparison_report(root, baseline, manifest):
    mode, market = baseline["mode"], baseline["market"]
    fields = {
        "stable": ("participants",),
        "teams": ("students", "projects"),
        "reviews": ("reviewers", "submissions"),
    }[mode]
    names = {
        p["id"]: p.get("name", p.get("title", p["id"]))
        for field in fields
        for p in market[field]
    }

    def esc(value):
        return html.escape(str(value))

    def labels(ids):
        return ", ".join(f"{names[i]} [{i}]" for i in ids) or "None"

    def display(row):
        value = labels(row["assigned"])
        if "teammates" in row:
            value += "; teammates: " + labels(row["teammates"])
        return value

    def metric(row):
        ranks = (
            ", ".join(str(r) if r is not None else "unranked" for r in row["ranks"])
            or "none"
        )
        text = f"Ranks: {ranks}"
        if row.get("score") is not None:
            text += f"; baseline score: {row['score']:.4f}"
        if "project_score" in row:
            text += f" (project {row['project_score']:.4f}, social {row['social_score']:.4f})"
        if "capacity" in row:
            text += f"; capacity {row['capacity']}; vacancies {row['vacancies']}"
        if mode == "reviews":
            text += f"; workload {row['load']}"
        return text

    summary, sections = [], []
    csv_fields = [
        "scenario",
        "participant_id",
        "name",
        "side",
        "changed",
        "preference_change",
        "score_delta",
        "before_assigned",
        "after_assigned",
        "before_teammates",
        "after_teammates",
        "before_ranks",
        "after_ranks",
        "before_load",
        "after_load",
        "before_score",
        "after_score",
        "before_capacity",
        "after_capacity",
    ]
    with (root / "participants.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields, lineterminator="\n")
        writer.writeheader()
        for run in manifest["scenarios"]:
            name = run["name"]
            comp = run.get("comparison")
            counts = (
                ", ".join(
                    f"{k.replace('_', ' ')}: {v}"
                    for k, v in (comp or {}).get("counts", {}).items()
                )
                or "No allocation to compare"
            )
            summary.append(
                f'<tr><th><a href="#{name}">{esc(name)}</a></th><td>{esc(run["status"])}</td><td>{comp["changed_participants"] if comp else "—"}</td><td>{esc(counts)}</td></tr>'
            )
            rows = []
            for row in (comp or {}).get("participants", []):
                record = {k: row.get(k) for k in csv_fields if k in row}
                record["scenario"] = name
                for prefix in ("before", "after"):
                    for key in (
                        "assigned",
                        "teammates",
                        "ranks",
                        "load",
                        "score",
                        "capacity",
                    ):
                        value = row[prefix].get(key)
                        record[f"{prefix}_{key}"] = (
                            json.dumps(value, ensure_ascii=False)
                            if isinstance(value, list)
                            else value
                        )
                writer.writerow(record)
                delta = (
                    f"{row['score_delta']:+.4f}"
                    if row["score_delta"] is not None
                    else "—"
                )
                rows.append(
                    f'<tr class="{"changed" if row["changed"] else ""}"><th scope="row">{esc(row["name"])} [{esc(row["participant_id"])}]<small>{esc(row.get("side") or "")}</small></th><td>{esc(display(row["before"]))}<small>{esc(metric(row["before"]))}</small></td><td>{esc(display(row["after"]))}<small>{esc(metric(row["after"]))}</small></td><td>{esc(row["preference_change"].replace("_", " "))}<small>Score change: {delta}</small></td></tr>'
                )
            table = (
                '<div class="scroll"><table><thead><tr><th>Participant</th><th>Baseline assignment</th><th>Scenario assignment</th><th>Preference outcome</th></tr></thead><tbody>'
                + "".join(rows)
                + "</tbody></table></div>"
                if rows
                else f"<p>{esc(run['error']['message'])}</p>"
            )
            result_link = (
                f' · <a href="{name}/result.json">Verified result and solver details</a>'
                if comp
                else ""
            )
            stats = run.get("statistics") or run.get("vacancies")
            aggregate = (
                f"<details><summary>Scenario statistics / vacancies</summary><pre>{esc(json.dumps(stats, indent=2))}</pre></details>"
                if stats is not None
                else ""
            )
            sections.append(
                f'<section id="{name}"><h2>{esc(name)}</h2><p>Status: {esc(run["status"])}. Scenario objective score: {esc(run["objective_score"] if run["objective_score"] is not None else "not applicable")}. {"Unchanged inputs; saved baseline reused." if run.get("reused_baseline") else ""}</p><p>Declared organizer changes:</p><pre>{esc(json.dumps(run["changes"], indent=2))}</pre><p><a href="{name}/market.json">Scenario market</a> · <a href="{name}/preferences.json">Frozen preferences</a>{result_link}</p>{table}{aggregate}</section>'
            )
    explanations = {
        "stable": "All partner ranks are shown against the original submitted lists. Unmatched slots rank below every acceptable partner. Better/worse ranks means the sorted rank vector improves/worsens without any opposing change; mixed vectors are left incomparable. This is an ordinal comparison, not a sum of invented utilities. Capacity changes also change responsibilities. Stability is checked within the same frozen candidate graph; unknown preferences remain unknown.",
        "teams": "Each row compares project and teammate assignments using the baseline project universe, target-size divisor, and social weight. Higher/lower score refers to that fixed Borda index, not measured satisfaction. The project and social components are shown separately. Closed projects stay in the option universe and keep their original ranks. The solver minimizes size deviation before maximizing each scenario's own score; allowing larger teams does not force them to be used. A new target or weight changes the solver objective, so objective totals across policies are not directly comparable.",
        "reviews": "Each reviewer retains the baseline ranking/score scale. Higher/lower score is reported only at equal workload. A changed number of reviews is labeled workload changed; the score delta does not determine whether the person benefits. In constraints-only mode preference outcomes are unscored. Submission coverage and reviewer workloads are in the scenario statistics. No preferences are inferred for submission authors.",
    }
    synthetic = (
        "Market labeled synthetic; inspect the preference sources below."
        if manifest["synthetic"]
        else "Organizer report; includes private preferences and assignments."
    )
    scope = ""
    if mode == "stable":
        scope = f"<p>Baseline scope: {esc(json.dumps(manifest.get('baseline_scope')))}. Original snapshot hash: {'verified' if manifest['baseline_verification']['snapshot_hash_verified'] else 'unavailable in this older report; exported assignments and inputs were checked'}.</p>"
    content = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Roth — organizer what-if comparisons</title>
<style>body{{font:17px/1.6 system-ui;max-width:1200px;margin:40px auto;padding:0 24px;background:#fafcfb;color:#173239}}h1,h2,a{{color:#12675e}}table{{border-collapse:collapse;width:100%}}th,td{{padding:12px;border-bottom:1px solid #ccd;text-align:left;vertical-align:top}}small{{display:block;color:#52635c;font-size:12px}}.scroll{{overflow:auto}}.changed{{background:#e6f3e9}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf4ef;padding:16px}}section{{margin-top:48px}}.callout{{padding:18px;background:#edf4ef;border-left:4px solid #12675e}}</style></head><body>
<h1>Organizer what-if comparisons</h1><p>{esc(market.get("name", mode))} · {esc(mode)} · {synthetic}</p>
<p class="callout">Every scenario branches from the same saved baseline. Preferences are held fixed; no re-elicitation or model calls occur. The baseline remains unchanged.</p>
<p>Baseline status: {esc(manifest["baseline_status"])}. Assignments and scores/ordinal ranks were independently checked. Solver optimality statuses describe the saved solver's claims; verification does not re-prove optimality.</p>
<p>Preference sources: {esc(", ".join(manifest["preference_sources"]) or "organizer constraints only")}.</p>{scope}
<p><a href="baseline/market.json">Baseline market</a> · <a href="baseline/preferences.json">Baseline preferences</a> · <a href="baseline/result.json">Baseline result</a> · <a href="scenarios.json">Requested changes</a> · <a href="comparison.json">Full comparison JSON</a> · <a href="participants.csv">Participant changes CSV</a></p>
<h2>How to read the comparison</h2><p>{explanations[mode]}</p><p>Green rows have different assignments, including teammate changes. Equal-score optima can give different assignments; churn is not necessarily required by the policy change. Feasible-limit results are valid allocations without proof of optimality. Infeasible scenarios have no gain/loss comparison; solver-limit without an allocation is distinct from proven infeasibility. These are conditional comparisons assuming preferences remain unchanged under the new rules.</p>
<h2>Scenarios</h2><table><thead><tr><th>Scenario</th><th>Status</th><th>People reassigned</th><th>Preference outcomes</th></tr></thead><tbody>{"".join(summary)}</tbody></table>{"".join(sections)}
<p>Baseline artifact hash: <code>{esc(manifest["baseline_hash"])}</code>. All exported inputs and assignments are local to this report.</p></body></html>"""
    (root / "index.html").write_text(content)
