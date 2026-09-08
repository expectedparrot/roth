# Organizer what-if comparisons

Use a saved report as the baseline, describe named organizer changes, and compare
who receives different assignments and how their preference outcomes change.
Supported modes are one-to-one/many-to-one stable matching, teams, and reviews.
Every scenario starts from the same baseline; scenarios do not accumulate changes.

```bash
roth compare classroom/report --scenarios scenarios.json --output classroom/comparison
```

Open `classroom/comparison/index.html`. This is a static organizer report with
before/after assignments, original ranks, individual score changes, teammate
changes, workload/capacity changes, scenario statuses, and a participant CSV.
The report links the exact inputs, results, and requested changes. It contains
private preferences. [Inspect the synthetic team example](comparisons-example/index.html).
That worked example starts with exact teams of three. Reproduce it with
`PYTHONPATH=src python scripts/comparison_example.py NEW_DIRECTORY` from a checkout
with the team solver installed.

## Team sizes, project closures, and preference weights

For the canned classroom example, `scenarios.json` can contain:

```json
[
  {"name": "allow-four", "config": {"allow_larger": true, "max_size": 4}},
  {"name": "target-four", "config": {"target_size": 4, "min_size": 4, "max_size": 4}},
  {"name": "close-climate", "close_projects": ["climate"]},
  {"name": "project-priority", "config": {"social_weight": 0.25}}
]
```

`config` updates explicit, normalized baseline settings. Unspecified settings
retain their baseline values; changing a flag does not reset a bound. Supply
`max_size` along with `allow_larger`, and adjust bounds when changing the target.
Smaller teams similarly require `allow_smaller` and `min_size`. Existing hard
exclusions remain in force. One team may use each open project.

Allowing teams of four does not force teams of four: Roth first minimizes
size deviation from the target, then maximizes preference scores. If teams of
three remain feasible and the target remains three, the larger bound might have
no effect. `target-four` asks a different question.
The standard `teams example` fixture already allows sizes two through four;
`allow-four` is an unchanged policy for that fixture.

`close_projects` makes listed projects unavailable for assignment. It records
`closed_projects` in the scenario market and retains the project roster and all
preference records. A closed project keeps its original rank and place in the
Borda universe; closing it never turns a second choice into a first choice.
Closures can also be supplied directly as `closed_projects` in a team market.

Each student's comparison score uses the **baseline** project and teammate
Borda tables, normalization divisors, target size, and social weight. Both
project and social components are shown. A scenario can use a new target/weight
for optimization, but its objective score is reported separately. Objective
totals under different policies are not directly comparable. More teammates can
yield a social score above one under the original divisor; that is intentional.
Scores are allocation indices, not measured welfare or truthful cardinal utility.

## Stable matching: add seats or close a position

Export the desired saved matching run with `roth report`, then use that report:

```json
[
  {"name": "extra-seat", "capacities": {"m001": 4}},
  {"name": "close-position", "capacities": {"m001": 0}},
  {"name": "other-proposers", "proposing_side": "right"}
]
```

Use IDs from your market. Capacity values are **absolute**, not increments; the
example raises a mentor from three seats to four only if the baseline has three.
Only active participants may have their capacities changed. At most one side
can have capacity above one. Zero closes a participant's slots while preserving
their identity and rankings. Omitted/unknown candidates stay unavailable edges;
Roth does not create rankings or rerun delegated models to fill new capacity.

All partners, original submitted ranks, capacities, and vacancies are shown.
For multiple partners, Roth sorts their ranks and pads the shorter list with
unmatched slots below every acceptable partner. It labels a vector better or
worse only if it improves or worsens without any opposing rank change. For
example, `[1, 4]` versus `[2, 3]` is **mixed**, because the individual rankings do
not tell us how to trade those changes off. No additive set utilities are assumed.
These comparisons concern partner ranks; changed capacity can change duties too.

The active cohort and candidate graph remain fixed. Stability is relative to
those preferences. New stable reports include the complete hashed snapshot;
older reports are checked against their exported preferences, capacities, and
matching but cannot have their original snapshot hash verified without that file.

## Reviews: coverage and workloads

Use per-person and per-submission overrides, which also work when the original
market used global defaults:

```json
[
  {
    "name": "extra-review",
    "reviewer_bounds": {"s01": {"max_reviews": 4}, "s02": {"max_reviews": 4}},
    "reviews_required": {"essay03": 4}
  }
]
```

Use the actual reviewer/submission IDs from your report. These are absolute
bounds/counts. Minimum loads retain their existing values unless explicitly
changed; lowering coverage may require lowering some minimum loads as well.
Authorship, team exclusions, individual rejections, eligibility, and scoring
mode stay fixed. Reviewer constraints and exact coverage are independently checked.

A larger total review score can simply mean more work. The report classifies a
reviewer as receiving a higher/lower score only at equal workload. Otherwise it
shows **workload changed**, along with the actual assignments, ranks, load, and
score delta. Constraints-only allocations show **unscored**, never invented
preference gains. Submission coverage is shown without inferring author utility.

## Reproducibility and limits

- `--output` must be a new directory. The baseline report, market store, survey
  responses, preference sources, and original assignments are preserved.
- The scenario file must be a nonempty array of unique names. Names use Roth IDs
  (letters/digits, underscores/hyphens); `baseline` is reserved. Unknown fields,
  unknown IDs, invalid bounds, and unsupported capacity structures are errors.
  All scenario schemas are checked before any optimization or output creation.
- Unchanged inputs reuse the saved baseline assignment. Other runs can select
  different equal-score optima; reported churn is not necessarily unavoidable.
- `--time-limit 60` sets seconds per optimization scenario. An infeasible scenario
  is retained in the report with its explanation, and other scenarios continue.
  A solver limit without an incumbent is distinct from proven infeasibility.
  Feasible incumbents are compared with their limited status visible.
- Assignments and outcome calculations are independently verified. Solver status
  records the solver's optimality claim; importing a baseline does not re-prove
  it. Input/result hashes support inspection and reproducibility, not signatures.
- These are conditional predictions with preferences held fixed. Changing the
  available options or team structure could change real preferences. Re-eliciting
  them would be a separate study, not an equivalent preference comparison.
- This command does not adopt a scenario, publish assignments, send invitations,
  or execute models. Roster additions, new preference responses, and changes to
  declared conflicts require their own validated workflow.

`roth agent next` includes optional comparison guidance after a completed report.
Choose the baseline and organizer changes, create the scenario file, and run
`roth compare` into a new folder. Explain individual compromises and failed
scenarios before the organizer chooses whether to use any result.
