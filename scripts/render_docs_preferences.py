"""Render the static guide's preference lists and matrix from bundled inputs.

Run from a checkout with Roth installed: python scripts/render_docs_preferences.py
No browser JavaScript, inference, or external services are involved.
"""

import html
import json
from pathlib import Path

from roth.matching import deferred_acceptance, verify_matching


def render():
    root = Path(__file__).resolve().parents[1]
    source = root / "examples" / "internships"
    market = json.loads((source / "market.json").read_text())
    rows = json.loads((source / "preferences.json").read_text())
    people = {p["id"]: p for p in market["participants"]}
    prefs = {r["participant_id"]: r for r in rows}
    sides = {
        side: {
            pid: prefs[pid]["ranking"] for pid, p in people.items() if p["side"] == side
        }
        for side in ("left", "right")
    }
    result = deferred_acceptance(sides["left"], sides["right"])
    assert verify_matching(sides["left"], sides["right"], result["matches"])["stable"]
    matched = dict(result["matches"])

    def name(pid):
        return html.escape(people[pid]["name"])

    def rank(pid, other):
        row = prefs[pid]
        if other in row["ranking"]:
            return str(row["ranking"].index(other) + 1)
        return "×" if other in row["unacceptable"] else "?"

    parts = [
        '<h3 id="preference-inputs">The actual input: two ordered lists</h3>',
        "<p>Each participant supplies a list from best to worst, plus explicit unacceptable options. Here are two of the 22 records used in this run. Lab numbers identify distinct single-slot openings.</p>",
        '<div class="two-col">',
    ]
    for pid, title, other in (
        ("s001", "Alex 1 ranks internships", "i003"),
        ("i003", "Lab 3 ranks students", "s001"),
    ):
        parts.append(
            f'<div class="card"><span class="tag">{pid} · Synthetic input</span><h3>{title}</h3><ol class="preference-list">'
        )
        for candidate in prefs[pid]["ranking"]:
            chosen = candidate == other
            label = name(candidate)
            if people[candidate]["side"] == "right":
                label = f"Lab {int(candidate[1:])} · {html.escape(people[candidate]['profile']['work'])}"
            parts.append(
                f'<li class="{"chosen" if chosen else "option"}">{label}{" ← realized match" if chosen else ""}</li>'
            )
        rejected = ", ".join(name(c) for c in prefs[pid]["unacceptable"])
        parts.append(
            f'</ol><p class="small"><strong>Would rather remain unmatched than accept:</strong> {rejected}.</p></div>'
        )
    parts.extend(
        [
            "</div>",
            "<p>Alex ranks Lab 3 seventh; Lab 3 ranks Alex second. Those two positions become <strong>7 / 2</strong> in the matrix. The lists are the inputs; the highlighted assignment is the computed outcome.</p>",
            "<details><summary>See the exact JSON for these two participants</summary>",
            '<p>This excerpt contains two complete records from <a href="assets/internship-preferences.json" download>the full 22-record preference file</a>. IDs refer to participants in <a href="assets/internship-market.json">market.json</a>.</p>',
        ]
    )
    # Keep each field on one line so the input is easy to scan.
    records = []
    for pid in ("s001", "i003"):
        fields = [
            f"    {json.dumps(k)}: {json.dumps(v)}" for k, v in prefs[pid].items()
        ]
        records.append("  {\n" + ",\n".join(fields) + "\n  }")
    parts.append(
        "<pre><code>"
        + html.escape("[\n" + ",\n".join(records) + "\n]")
        + "</code></pre>"
    )
    parts.extend(
        [
            "<p><code>ranking</code> contains acceptable options in order. <code>unacceptable</code> lists explicit rejections. <code>evaluated</code> records which candidates were reviewed; <code>complete</code> marks a finished submission, which can have an empty ranking. The source is labeled <code>synthetic</code>.</p></details>",
            '<h3 id="ranking-matrix">All rankings, with realized matches</h3>',
            "<p>Read a row to see a student’s preferences across openings. Read a column to see how an employer ranks each student. Each cell is <strong>student rank / employer rank</strong>; 1 is best on either side.</p>",
            '<div class="matrix-legend" id="matrix-legend"><span><span class="match-key">7 / 2 · MATCH</span> Realized assignment</span><span><strong>×</strong> Unacceptable to that side</span><span><strong>?</strong> Unresolved (none in this example)</span></div>',
            '<div class="table-wrap matrix-scroll" tabindex="0" role="region" aria-label="Student and internship ranking matrix; scroll horizontally on small screens" aria-describedby="matrix-legend"><table class="rank-matrix">',
            "<caption>All 120 possible pairs from the bundled synthetic preferences. Students propose. Only mutually acceptable pairs can match. Scroll horizontally on a narrow screen; student names stay visible.</caption>",
            '<thead><tr><th scope="col">Student ↓<br>Opening →</th>',
        ]
    )
    for pid in sides["right"]:
        role = html.escape(people[pid]["profile"]["work"])
        parts.append(
            f'<th scope="col" title="{name(pid)}">Lab {int(pid[1:])}<span class="col-role">{role}</span></th>'
        )
    parts.append('<th scope="col">Outcome</th></tr></thead><tbody>')
    for student in sides["left"]:
        parts.append(f'<tr><th scope="row">{name(student)}</th>')
        for opening in sides["right"]:
            a, b = rank(student, opening), rank(opening, student)
            is_match = matched.get(student) == opening
            style = (
                "matched" if is_match else "unacceptable" if "×" in (a, b) else "ranked"
            )
            label = f"{name(student)} / {name(opening)}: student rank {a}; employer rank {b}"
            label += "; realized match" if is_match else "; not matched"
            badge = '<span class="match-label">MATCH</span>' if is_match else ""
            parts.append(
                f'<td class="{style}" data-student="{student}" data-opening="{opening}" aria-label="{label}" title="{label}"><span class="rank-pair">{a} / {b}</span>{badge}</td>'
            )
        outcome = (
            f"Lab {int(matched[student][1:])}" if student in matched else "Unmatched"
        )
        parts.append(f'<td class="outcome">{outcome}</td></tr>')
    parts.extend(
        [
            "</tbody></table></div>",
            "<p><strong>Why doesn’t Alex get Lab 8, their first choice?</strong> Lab 8 ranks Alex eighth and Blair first. The stable outcome assigns Blair to Lab 8 and Alex to Lab 3. A high ranking from one side alone does not secure a match.</p>",
            "<details><summary>Follow Alex’s proposals through this run</summary><p>Alex approaches Labs 8, 4, 1, 6, 2, 10, and 3 in that order. Labs 8 and 1 initially hold Alex, then replace Alex with applicants they prefer. Labs 4, 6, 2, and 10 reject Alex when approached. Lab 3 holds Alex through the end, producing the 7 / 2 match.</p></details>",
            "<p><strong>Two students remain unmatched.</strong> Finley 6 exhausts their acceptable options during matching. Lane 12 explicitly rejects all ten openings—the × entries across Lane’s row are submitted choices, not missing answers.</p>",
            '<p class="small muted">This matrix is computed from the downloadable preference file using student-proposing deferred acceptance. The <a href="#start">commands below</a> reproduce it without model calls or survey invitations.</p>',
        ]
    )
    page = root / "docs" / "index.html"
    start, end = (
        "<!-- BEGIN GENERATED PREFERENCES -->",
        "<!-- END GENERATED PREFERENCES -->",
    )
    before, rest = page.read_text().split(start)
    _, after = rest.split(end)
    page.write_text(
        before + start + "\n    " + "\n    ".join(parts) + "\n    " + end + after
    )
    assets = root / "docs" / "assets"
    assets.mkdir(exist_ok=True)
    for filename in ("market.json", "preferences.json"):
        (assets / f"internship-{filename}").write_bytes(
            (source / filename).read_bytes()
        )
    print(
        f"Rendered {len(sides['left'])} × {len(sides['right'])} matrix, {len(matched)} matches."
    )


if __name__ == "__main__":
    render()
