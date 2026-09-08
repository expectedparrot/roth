# Working on Roth

Roth is an agent-friendly CLI for one-to-one and many-to-one stable matching.
Capacities are nonnegative integer upper bounds, default one, with at most one
side above one. Use responsive individual rankings and preserve every assigned
partner in reports; vacancies and unmatched participants are distinct.
Start with `roth agent next` to identify the scenario and elicit missing inputs.
Use `roth --project STUDY agent next` after each action; follow `data.rerun`
when custom paths are supplied. `roth guide` and `roth capabilities` provide
the full workflow and supported features. Reuse existing user answers and
never force an unsupported scenario into another mechanism.
Keep the core matching engine independent of EDSL and network access.

Use `roth compare BASELINE_REPORT --scenarios SCENARIOS.json --output NEW_REPORT`
for organizer what-if analysis across stable, team, and review modes. Keep the
baseline cohort and preference records fixed. Gains/losses use baseline ranks
and score scales; a changed review workload is not a preference gain. Team
closures preserve the option universe and ranks. Show infeasibility and solver
limits explicitly. Never adopt a scenario or deliver assignments automatically.
See docs/comparisons.md for supported changes and interpretation.

The separate `roth teams` mode jointly assigns students to teams and projects
using Borda rankings and optional SciPy/HiGHS integer optimization. It uses
explicit input files and immutable output directories, not the stable-matching
market store. Keep hard exclusions distinct from unranked zero-score options.
Verify assignments and scores independently; report solver limits honestly.
This mode does not claim stability or strategy-proofness.

The file-based `roth reviews` mode optimizes reviewer/submission assignments with
exact review coverage and workload bounds. Authorship, team membership, and
explicit conflicts define hard exclusions. Partial rankings or scores leave
zero-score eligible options assignable; missing records remain incomplete.
Verify assignments and scores independently and preserve original inputs.
Team/review Humanize collection lives in collection.py, with a private append-only
.roth history inside each field directory. Keep batch assessments separate from
cross-batch ranks. Preserve no-preference/unknown, hard exclusions, and missing
responses; never promote synthetic fixture answers to human sources. Assessment
revisions invalidate old ranking rounds. Native delivery remains explicit ep
handoff; delegated team/review scoring is not implemented.

Development checks:

```bash
python -m compileall -q src
python -m pytest -q
python -m build --no-isolation
```

Keep CLI parsing in `cli.py` and domain behavior in its owning module. Preserve
one JSON envelope per command and structured nonzero failures. Do not silently
replace preference history, snapshots, model scores, or respondent identities.
Keep unknown, rejected, and nonresponding states distinct. Human pairwise answers
used for calibration must remain separate from held-out benchmark answers.

External execution uses EDSL handoff artifacts and explicit `ep` commands.
Building and testing does not authorize paid model calls or real invitations.
The synthetic internship fixtures must stay visibly labeled as synthetic.
