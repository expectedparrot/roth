# Peer-review assignment

`roth reviews` assigns several submissions to each reviewer and several reviewers
to each submission. It enforces required review counts, reviewer workload bounds,
and conflicts, then maximizes additive preference or expertise scores. This is a
separate file-based optimization mode with no stability or strategy-proofness claim.

## Try the classroom example

From a checkout, install the optional SciPy/HiGHS solver:

```bash
python -m pip install -e '.[reviews]'
roth reviews example classroom-reviews
roth --project classroom-reviews agent next
roth reviews validate classroom-reviews/market.json --preferences classroom-reviews/preferences.json
roth reviews solve classroom-reviews/market.json --preferences classroom-reviews/preferences.json --output classroom-reviews/report
```

The fixture has **12 students and 12 individually authored essays**. Every student
reviews three essays; every essay receives three reviews. The students also belong
to four existing teams of three: self-review and review of a teammate's essay are
forbidden. There is an additional organizer conflict and one explicit unacceptable
submission. Preferences are labeled synthetic, favor shared topics, and use seeded
shuffling within topic groups. No emails, surveys, or model calls are executed.

`example` writes input files without solving or creating a `.roth` store. The
[worked report](reviews-example/index.html) shows 36 assignments with full coverage,
all workloads equal to three, and 29 assignments in the reviewer's top three.
Equal-score optima may differ. Inspect the [market](reviews-example/submitted-market.json)
and [preferences](reviews-example/submitted-preferences.json) to see exactly what
was supplied.

## Market contract

```json
{
  "schema_version": "1.0",
  "mode": "reviews",
  "name": "Classroom peer review",
  "config": {
    "min_reviews": 3,
    "max_reviews": 3,
    "reviews_per_submission": 3,
    "exclude_teammates": true,
    "scoring": "borda"
  },
  "reviewers": [
    {"id": "s01", "name": "Alex", "team": "team1"},
    {"id": "s02", "name": "Blair", "team": "team1"}
  ],
  "submissions": [
    {"id": "p01", "title": "Alex's essay", "authors": ["s01"]},
    {"id": "p02", "title": "Blair's essay", "authors": ["s02"]}
  ],
  "excluded_pairs": []
}
```

This two-person excerpt illustrates the schema; it is infeasible with three reviews
and teammate exclusions. Use the full classroom fixture for a runnable example.

Reviewer and submission IDs must be globally disjoint stable Roth identifiers.
All author IDs refer to the reviewer roster. An author who does not review can
appear with `min_reviews: 0, max_reviews: 0`; in scored modes provide an empty
completed preference record for that person, with the appropriate source.
Reviewers need not author submissions. Multiple authors are supported, and every
coauthor is excluded from reviewing their own submission.

Each reviewer can override `min_reviews` and `max_reviews`. Each submission can
override `reviews_required`. Counts must be nonnegative integers; zero is valid.
The defaults are three for all counts. With wider workload bounds, the solver
maximizes score within those bounds; it does not promise equal workloads.

Self-review is always forbidden. When `exclude_teammates` is true (the default),
a reviewer cannot review a submission authored by anyone with the same declared
`team`. Omitting a team means no team membership is declared. Roth cannot infer
undeclared relationships. Setting the flag false permits teammate review but
still forbids self-review.

`excluded_pairs` lists additional `[reviewer_id, submission_id]` conflicts.
Optional `eligible_pairs` restricts the initial graph. Neither can re-enable
self-review or teammate exclusions. Conflicts are supplied explicitly; no
organization, email-domain, or coauthorship lookup is performed.

## Rankings and scores

For `scoring: "borda"`, supply one completed record per roster member:

```json
[
  {
    "reviewer_id": "s01",
    "ranking": ["p05", "p08", "p11"],
    "unacceptable": ["p07"],
    "complete": true,
    "source": "human"
  }
]
```

Records must use organizer-eligible submission IDs: omit self, teammate, and
organizer-conflict options. This snippet illustrates a partial record from a
larger roster; all participating roster members still need completed records.
Sources can be `human`, `organizer`, or `synthetic`. Explicit imports trust the
organizer's declared source; they do not authenticate survey responses.

For reviewer r with M organizer-eligible submissions, position k in a ranked
list receives `(M-k) / max(1, M-1)` points. A singleton ranked option receives one
point. M is fixed before individual unacceptable options are removed; it does not
shrink when someone submits a short list. The last entry of a complete list scores
zero. Empty and partial completed lists are allowed.

**Unranked options score zero and remain assignable.** They are distinct from
explicitly unacceptable options, which are hard exclusions. A missing record is
incomplete input, not an empty ranking. This allocation contract differs from the
stable-matching workflow, where unresolved edges are unavailable when frozen.

For `scoring: "scores"`, replace `ranking` with a score map:

```json
{
  "reviewer_id": "s01",
  "scores": {"p05": 90, "p08": 65},
  "unacceptable": ["p07"],
  "complete": true,
  "source": "organizer"
}
```

Scores must be finite numbers in [0,100]; the objective divides them by 100.
Unscored eligible options score zero. Organizers should use a consistent scoring
rubric if aggregate score comparisons are intended. Mixed `ranking` and `scores`
fields are rejected rather than silently choosing one.

For `scoring: "none"`, omit `--preferences` or supply `[]`. This finds any feasible
allocation without a preference objective. Nonempty preference input is rejected
so supplied preferences cannot accidentally be discarded. Put all hard conflicts
in the market in this mode.

Native Humanize surveys are available through `reviews field`. They remove
organizer-ineligible options, assess preferences or expertise in batches, and
collect a cross-batch ranking when Borda choices need ordering. Expertise surveys
use 0–100 in increments of 10; direct score files still support any finite value
in that range. See the [collection workflow](collection.md). Delegated review
scoring remains unimplemented.

## Optimization problem

Let E be the allowed reviewer/submission edges after all exclusions, d_p the
required reviews for submission p, and L_r,U_r the workload bounds for reviewer r.
The variable x_rp is binary: one means r reviews p. Maximize:

\[
\max \sum_{(r,p)\in E} s_{rp} x_{rp}
\]

subject to:

\[
\sum_{r:(r,p)\in E} x_{rp} = d_p \quad\text{for each submission }p,
\qquad
L_r \le \sum_{p:(r,p)\in E} x_{rp} \le U_r \quad\text{for each reviewer }r.
\]

This uses one binary variable per allowed edge. Assigning the same reviewer to the
same submission twice cannot count as two reviews. The independent verifier
rechecks the discrete assignment and recomputes every score, workload, and coverage
count without using the solver's constraint matrix.

`reviews validate` checks the schema, calculates scores, and reports necessary
feasibility checks. Its `valid: true` refers to schema validity. Inspect
`checks.necessary_checks_pass`; even passing that does not prove feasibility.
Several submissions may compete for the same limited pool of reviewers. Only the
joint solve resolves those bottlenecks.

The solver raises `INFEASIBLE` if hard requirements cannot all be met. It never
relaxes them automatically. With `--time-limit SECONDS`, a verified incumbent is
reported as `feasible_limit` if optimality was not proved. If no incumbent exists,
the command returns `SOLVER_LIMIT`, which is not a proof of infeasibility. The
report includes the score upper bound and relative gap when supplied by HiGHS.

## Reports and agent guidance

Every successful solve writes into a new directory and freezes both original and
normalized inputs, computed scores, result JSON, assignments CSV, and a static
HTML report. Existing output directories are never overwritten. The report shows
reviewer tasks, coverage counts, workload bounds, and a ranking/score matrix with
assigned and forbidden edges marked. Matrices larger than 2,500 cells are omitted;
complete machine-readable outputs remain available.

The report is for the organizer and includes preferences and authorship. It does
not promise anonymous or double-blind delivery. No assignments are emailed.

```bash
roth --project classroom-reviews agent next --scenario reviews
```

Guidance identifies the schema automatically, checks inputs, flags obvious
infeasibility, offers the solver action, and verifies saved outcomes before review.
Changed inputs select a fresh output directory. Tampered results require inspection.
A feasible time-limited result prompts a decision about accepting it or allowing
more solver time, rather than claiming an optimum or automatically rerunning.

## Python API

```python
from roth.review_example import review_example
from roth.reviews import solve_reviews, evaluate_reviews

market, preferences = review_example()
result = solve_reviews(market, preferences, time_limit=60)
checked = evaluate_reviews(market, preferences, result["assignments"])
assert checked["valid"]
assert checked["statistics"]["assignments"] == 36
```

Only solving imports SciPy. Input validation, score tables, and independent
verification work without optional dependencies.
