"""Portable organizer reports and participant-safe individual exports."""

import csv
import html
import json
from pathlib import Path

from .common import require, write_json
from .market import participants, public_profile


def export_report(state, run_name, output):
    require(run_name in state["runs"], "Unknown matching run")
    run = state["runs"][run_name]
    snapshot = state["snapshots"][run["snapshot"]]
    people = participants(snapshot["market"])
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / "matches.json", run)
    write_json(directory / "preferences.json", snapshot["preferences"])
    with (directory / "matches.csv").open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["left_id", "left_name", "right_id", "right_name"])
        for a, b in run["matches"]:
            writer.writerow([a, people[a]["name"], b, people[b]["name"]])
    esc = lambda value: html.escape(str(value))
    rows = "".join(
        f"<tr><td>{esc(people[a]['name'])}</td><td>{esc(people[b]['name'])}</td></tr>"
        for a, b in run["matches"]
    )
    bars = []
    for side, info in run["statistics"]["by_side"].items():
        matched = info["match_rate"]
        bars.append(
            f"<p>{esc(side)}: {matched['numerator']} / {matched['denominator']} matched</p><meter min='0' max='{max(1, matched['denominator'])}' value='{matched['numerator']}'></meter>"
        )
    content = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Roth — internship matching report</title><style>body{{font:17px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#173239;background:#fafcfb}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ccd}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef4f3;padding:16px}}meter{{width:100%;height:28px}}h1,h2{{color:#12675e}}</style>
<h1>{esc(snapshot["market"].get("name", "Matching report"))}</h1>
<p>Run {esc(run_name)} · Proposing side: {esc(run["proposing_side"])} · Verified stable within the frozen candidate graph.</p>
<p>Coverage: {esc(run["scope"]["coverage"])}; cohort: {esc(run["scope"]["cohort_scope"])}; preference sources: {esc(", ".join(run["scope"]["preference_sources"]))}.</p>
<p>Stability is relative to these submitted or inferred preferences. Shortlist ranks are not full-market ranks.</p>
{"".join(bars)}<h2>Matches</h2><table><thead><tr><th>Left side</th><th>Right side</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Unmatched participants</h2><pre>{esc(json.dumps(run["unmatched"], indent=2))}</pre>
<h2>Preference and outcome statistics</h2><pre>{esc(json.dumps(run["statistics"], indent=2))}</pre>
<h2>Proposer comparison</h2><pre>{esc(json.dumps(run.get("comparison", {}), indent=2))}</pre>
<h2>Preference benchmarks</h2><pre>{esc(json.dumps(run.get("benchmarks", {}), indent=2))}</pre>
<p>Organizer report: includes aggregate preference information. Individual files contain only the assigned partner's public profile.</p></html>"""
    (directory / "index.html").write_text(content)
    partners = {a: b for edge in run["matches"] for a, b in (edge, edge[::-1])}
    for pid in snapshot["active"]:
        write_json(
            directory / "individual" / f"{pid}.json",
            {
                "participant_id": pid,
                "partner": public_profile(people[partners[pid]])
                if pid in partners
                else None,
                "run": run_name,
                "reason": run["unmatched"].get(pid),
            },
        )
    return {
        "report": str((directory / "index.html").resolve()),
        "directory": str(directory.resolve()),
    }
