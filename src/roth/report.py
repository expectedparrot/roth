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
    write_json(directory / "market.json", snapshot["market"])
    with (directory / "matches.csv").open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["left_id", "left_name", "right_id", "right_name"])
        for a, b in run["matches"]:
            writer.writerow([a, people[a]["name"], b, people[b]["name"]])

    def esc(value):
        return html.escape(str(value))

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
    partners = {p: [] for p in snapshot["active"]}
    for a, b in run["matches"]:
        partners[a].append(b)
        partners[b].append(a)
    loads = "".join(
        f"<tr><td>{esc(people[p]['name'])}</td><td>{people[p].get('capacity', 1)}</td><td>{len(partners[p])}</td><td>{people[p].get('capacity', 1) - len(partners[p])}</td></tr>"
        for p in snapshot["active"]
    )
    matrix = ranking_matrix(snapshot, run["matches"])
    content = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Roth — matching report</title><style>body{{font:17px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#173239;background:#fafcfb}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:12px;border-bottom:1px solid #ccd}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef4f3;padding:16px}}meter{{width:100%;height:28px}}h1,h2{{color:#12675e}}.scroll{{overflow-x:auto}}.matched{{background:#d5eee2;font-weight:bold;outline:2px solid #12675e;outline-offset:-2px}}.matrix td{{white-space:nowrap}}</style>
<h1>{esc(snapshot["market"].get("name", "Matching report"))}</h1>
<p>Run {esc(run_name)} · Proposing side: {esc(run["proposing_side"])} · Verified stable within the frozen candidate graph.</p>
<p>Coverage: {esc(run["scope"]["coverage"])}; cohort: {esc(run["scope"]["cohort_scope"])}; preference sources: {esc(", ".join(run["scope"]["preference_sources"]))}.</p>
<p>Stability is relative to these submitted or inferred preferences. Shortlist ranks are not full-market ranks.</p>
<p>Capacities are upper bounds. Rankings evaluate individual partners independently; acceptable partners are preferred to leaving a slot empty.</p>
<p>Frozen inputs: <a href="market.json">market and capacities</a> · <a href="preferences.json">preferences</a> · <a href="matches.csv">matches CSV</a>.</p>
{"".join(bars)}<h2>Matches</h2><table><thead><tr><th>Left side</th><th>Right side</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Capacity and vacancies</h2><table><thead><tr><th>Participant</th><th>Capacity</th><th>Assigned</th><th>Unfilled</th></tr></thead><tbody>{loads}</tbody></table>
{matrix}
<h2>Unmatched participants</h2><pre>{esc(json.dumps(run["unmatched"], indent=2))}</pre>
<h2>Preference and outcome statistics</h2><pre>{esc(json.dumps(run["statistics"], indent=2))}</pre>
<h2>Proposer comparison</h2><pre>{esc(json.dumps(run.get("comparison", {}), indent=2))}</pre>
<h2>Preference benchmarks</h2><pre>{esc(json.dumps(run.get("benchmarks", {}), indent=2))}</pre>
<p>Organizer report: includes private rankings. Individual files contain only assigned partners' public profiles, with no rankings or contact details.</p></html>"""
    (directory / "index.html").write_text(content)
    for pid in snapshot["active"]:
        assigned = [public_profile(people[c]) for c in sorted(partners[pid])]
        record = {
            "participant_id": pid,
            "partners": assigned,
            "capacity": people[pid].get("capacity", 1),
            "unfilled_slots": people[pid].get("capacity", 1) - len(assigned),
            "run": run_name,
            "reason": run["unmatched"].get(pid),
        }
        if record["capacity"] <= 1:
            record["partner"] = assigned[0] if assigned else None
        write_json(
            directory / "individual" / f"{pid}.json",
            record,
        )
    return {
        "report": str((directory / "index.html").resolve()),
        "directory": str(directory.resolve()),
    }


def ranking_matrix(snapshot, matches):
    """Display both directional ranks and matches for modest-sized markets."""
    people = participants(snapshot["market"])
    left, right = (
        [p for p in snapshot["active"] if people[p]["side"] == side]
        for side in ("left", "right")
    )
    if len(left) * len(right) > 2500:
        return "<p>Ranking matrix omitted above 2,500 cells; the full preferences and matches are available in the linked files.</p>"

    def esc(value):
        return html.escape(str(value))

    ranks = {
        p: {c: i + 1 for i, c in enumerate(row["ranking"]) if c in snapshot["active"]}
        for p, row in snapshot["preferences"].items()
    }
    edges = set(map(tuple, matches))

    def label(p, c):
        if c in ranks[p]:
            return str(ranks[p][c])
        if c in snapshot["preferences"][p]["unacceptable"]:
            return "×"
        return "—"

    header = "".join(
        f'<th scope="col">{esc(people[p]["name"])}<br>capacity {people[p].get("capacity", 1)}</th>'
        for p in right
    )
    rows = []
    for a in left:
        cells = "".join(
            f'<td class="{"matched" if (a, b) in edges else ""}">{label(a, b)} / {label(b, a)}{" ✓" if (a, b) in edges else ""}</td>'
            for b in right
        )
        rows.append(f'<tr><th scope="row">{esc(people[a]["name"])}</th>{cells}</tr>')
    return f'<h2>Rankings and realized matches</h2><p>Each cell: row participant’s rank / column participant’s rank. Lower is better. ✓ and green mark a match; × means explicitly unacceptable; — means unranked or ineligible. Ranks use the frozen submitted lists.</p><div class="scroll"><table class="matrix"><thead><tr><th></th>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
