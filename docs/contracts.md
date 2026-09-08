# Data contracts

All IDs are stable strings matching `[A-Za-z0-9][A-Za-z0-9_-]{0,95}`. Left and
right IDs are globally disjoint. Display names need not be unique. Capacity defaults to one and must be a nonnegative integer. Only one side may
have capacities above one; zero means a closed position. Core imports reject malformed input rather than silently repairing it.

## Market JSON

```json
{
  "schema_version": "1.0",
  "name": "Internship placement",
  "side_labels": {"left": "Students", "right": "Internships"},
  "config": {
    "proposing_side": "left",
    "delegation": "delegated",
    "side_policies": {"right": "confirm"},
    "unknown_policy": "exclude",
    "benchmark_policy": "advisory",
    "benchmark_min_accuracy": 0.8,
    "benchmark_min_answers": 5,
    "deadline": null
  },
  "participants": [
    {
      "id": "s001", "side": "left", "name": "Alex",
      "profile": {"skills": "Python", "availability": "June–August"},
      "preferences": "I value mentoring and practical programming experience.",
      "contact": {"respondent_id": "student-1", "email": "alex@example.invalid"}
    },
    {
      "id": "i001", "side": "right", "name": "Research internship",
      "profile": {"work": "Data analysis", "mentoring": "Daily", "location": "Remote"},
      "preferences": "Seek Python skills and interest in research.",
      "contact": {"respondent_id": "employer-1", "email": "employer@example.invalid"}
    }
  ]
}
```

Example addresses above cannot receive real invitations. Keep private instructions
and contact fields outside `profile`; only the public profile is shown to others.
Use one participant ID and one ranking per mentor or program, with `capacity: 3`
for up to three partners. Rankings evaluate individuals independently of other
partners; every ranked candidate is preferred to leaving an available slot empty.
A ranking may be longer than capacity. Capacities are upper bounds, not minimum
fill requirements. Distinct openings with different preferences may still have
separate IDs.

`eligible_pairs`, if supplied, is an explicit list of `[left_id, right_id]` edges;
otherwise all cross-side pairs are eligible. `excluded_pairs` removes explicit
edges. These are organizer constraints, distinct from individual rejection.
The initial release expects organizers to encode confirmed hard filters in these
edge lists; it does not turn ambiguous natural language into automatic hard rules.

Organizer policies:

- `direct`: use human rankings; model application skips this side.
- `delegated`: inferred rankings may be used directly.
- `confirm`: inferred rankings require a participant confirmation response.
- `unknown_policy=exclude`: unresolved edges remain unknown in the record and are
  unavailable in a frozen matching. `require_complete` blocks such a freeze.
- `benchmark_policy=gate`: delegated rows need a passing held-out report for their
  current score bundle, at the specified accuracy and minimum answer count.
  `advisory` records evidence without blocking. With five required answers, build
  at least ten pairwise questions per participant; half are held out.
- `deadline`: optional ISO 8601 time with timezone. Status reports whether it has
  passed; the organizer closes and excludes nonrespondents explicitly. Roth does
  not run a background scheduler or discard late submissions automatically.

`roth configure config.json` records changes to these settings. Existing frozen
snapshots remain unchanged. Prepared fielding and scoring plans are version-bound;
rebuild them after a policy change.

CSV side imports use `id,name,profile,preferences,contact` plus optional integer `capacity`, with JSON strings in
`profile` and `contact`. The CLI supplies `side`. EDSL AgentList imports use the
agent name as fallback ID/name and traits for the remaining fields. Market JSON
supports explicit eligibility edges; two-file import uses full cross-side eligibility.

## Preference records

```json
[
  {
    "participant_id": "s001",
    "ranking": ["i002", "i001"],
    "unacceptable": ["i003"],
    "evaluated": ["i001", "i002", "i003", "i004"],
    "complete": true,
    "source": "human",
    "confirmed": true
  }
]
```

Ranking is best first, all ranked candidates are acceptable, and the implicit
outside option follows them. An evaluated candidate absent from both decision
lists is unresolved; an eligible candidate absent from `evaluated` was not
assessed. Omission never means rejection. `evaluated` defaults to the union of
ranking and unacceptable lists when omitted.

`complete` means the participant submitted this instrument, not that all eligible
candidates were assessed. Accepted source labels are `human`, `delegated`, and
`synthetic`. Explicit JSON imports trust the importing organizer's declared source;
Roth cannot authenticate an arbitrary file's author. Native field imports additionally
verify their saved participant/package mappings. Prior human ranking records cannot
be replaced with model or synthetic records. Explicit revisions use `--replace`.

## Field response JSON

The generated `responses-template.json` describes one row per personalized package:

```json
[
  {
    "package_id": "ranking_s001_1",
    "participant_id": "s001",
    "submission_id": "submission-1",
    "answers": {
      "ranking": ["Research internship [i001]", "Remain unmatched"],
      "known_0": "Assessed"
    }
  }
]
```

Use the exact labels and question names from the saved package. Native EDSL imports
normalize zero-based ranking codes using that same saved order. Required unanswered
questions block preference ingestion; preserve the external Results and import a
completed response later. Re-importing the same submission is idempotent; changing
its content under the same submission ID is an error. A different submission ID
requires `--replace` when replacing an existing response. Import order only changes
active preferences when that revision is explicitly authorized by the flag.

Screening uses `Acceptable`, `Unacceptable`, or `Insufficient information` per
candidate. It does not create a complete preference ranking. A later ranking survey
combines accepted options across batches and retains prior screening decisions.

## Score and benchmark records

`score-template.json` binds each directional score to an immutable task ID. Fields
are `acceptability` (`acceptable`, `unacceptable`, `unknown`), finite `score` from
0 to 100, a string list of `evidence`, and a nonempty `explanation`. Partial score
imports are allowed; application requires every planned task. Conflicting scores
for one cache key are rejected. Use a changed model or calibration plan for a
new evaluation, not an overwrite.

Pairwise benchmark records use `question_id`, `choice`, `a_acceptable`,
`b_acceptable`, and an optional `explanation`. Choice options are the five-point
A/B preference scale plus insufficient information; acceptability is separate for
each candidate. Survey artifacts separate calibration and held-out questionnaires.
Model predictions are kept out of participant instruments.

Reports compare directional choices, not a model's uncalibrated confidence or
ordinal strength score. Ties are evaluated as ties; insufficient-information
answers are excluded from the directional denominator and counted separately.
Representatively sampled pairs and targeted near-tie pairs are reported separately.

## Local history

`.roth/events/00000001.json` and subsequent files form a hash chain. Each references
an immutable state object under `.roth/objects/`. All mutations occur under an
exclusive file lock; an event appears only after its state object is durable.
CLI failures do not commit partial state. Generated artifacts remain reviewable
outside `.roth/`; incomplete failed builds may leave unregistered output directories,
which Roth does not overwrite or silently clean up.

## Capacity-aware matching outputs

`matches` remains a list of `[left_id, right_id]` pairs. An ID on the capacity
side may appear in several distinct pairs. Runs also include `capacities` and
`vacancies` for every active participant. `unmatched` contains only participants
with zero assignments; a partly filled mentor appears in vacancies instead.

Individual exports use `partners`, a list of assigned public profiles. The old
`partner` scalar is retained only for capacity-zero/one participants; it is not
present for multi-slot participants. No partner ranking, private instructions,
or contact details are included.

Statistics distinguish participant `match_rate` (at least one partner) from
`slot_fill_rate` (assignments divided by capacity). `assigned_partner_rank_lists`
contains all ranks per matched respondent. Legacy `assigned_partner_ranks`
contains scalar ranks only for unit-capacity respondents. Mean assigned rank
weights each assignment equally; top-1/top-3 assignment rates count participants
with at least one such partner. Ranks remain ordinal and list-relative.
