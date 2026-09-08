# Human surveys for teams and peer review

`roth teams field` and `roth reviews field` turn a roster and organizer rules into
personalized Humanize instruments, import the responses, and export preferences
for the existing optimizers. Humanize publication and invitations remain explicit
external `ep` actions. Roth's build, status, and import commands do not send emails.

## Start with the calling agent

```bash
roth --project classroom agent next --scenario teams --collection human --contacts contacts.json
roth --project classroom-reviews agent next --scenario reviews --collection human --contacts contacts.json
```

The agent reuses prior answers and collects missing roster, rule, and contact
information. Its `data.rerun` preserves custom paths. `--field-dir` defaults to
PROJECT/field. `--collection human` starts or resumes collection even if the
example's synthetic preferences.json exists. Completed exports receive new paths;
they do not overwrite the original fixture or previous human submissions.

Install the `fielding` extra for native EDSL artifacts; install `teams` or `reviews`
for solving. From a checkout:

```bash
python -m pip install -e '.[fielding,teams,reviews]'
```

## Surveys and their meaning

Team respondents assess two domains: projects and potential teammates. Reviewers
see organizer-eligible submissions only; self-review, teammate conflicts, and
explicit organizer exclusions are removed before generating options. Names,
titles, and supplied descriptions appear in instruments. Contacts and other
participants' answers are never inserted into survey text.

For ranked preferences, each option has three choices:

- **Include in my ranking:** select it for the next ranking step.
- **No preference / insufficient information:** retain it as an assignable option
  with zero preference score; the optimizer can still assign it.
- **Exclude (hard constraint):** forbid the assignment. In team formation, an
  exclusion from either student prevents that pair from sharing a team.

The combined neutral/insufficient-information response is retained verbatim in
collection history and export provenance. It is distinct from an exclusion and
from a missing answer. This is the optimization contract, not stable matching's
omitted-edge policy. The survey explains this distinction to respondents.

Assessment is split into batches of at most ten options per domain by default.
Use `--batch-size` to adjust this. Once **all assessment batches** are complete,
respondents rank selected options together across batches, separately for each
domain. A zero- or one-option selection needs no additional ranking response.
All selected options must appear exactly once in the ranking.

`--max-options` defaults to 15 for each final ranking. If too many are selected,
ask respondents to revise their selections or explicitly raise the limit on
`field rank`. Roth never drops selected options automatically. Selections omitted
from a ranking still retain zero-score eligibility unless explicitly excluded.
Each package is a separate Humanize survey; inspect the package count before
recruitment and adjust the batch size to suit the cohort.

For review `scoring: scores`, assessments offer **0, 10, …, 100**, plus the neutral
and exclusion options. A score of zero remains assignable. No second ranking wave
is required. Direct score-file imports continue to accept any finite value in
[0,100]. `scoring: none` deliberately has no human preference survey.

## Private contacts and frozen identities

Keep contacts in a separate file keyed by the market's respondent IDs:

```json
{
  "s01": {"email": "alex@example.invalid", "respondent_id": "class-student-1"},
  "s02": {"email": "blair@example.invalid"}
}
```

These example addresses cannot receive invitations. Real recruitment needs the
actual contacts. Contacts are optional while preparing previews; email delivery
requires a native collection built with the intended contact map. Changing the
contact map or market after building requires a new collection directory.

Every saved Jobs/AgentList binds a `roth_participant_id` and `roth_package_id`.
Native Results imports verify these traits, question text, and option order
against the frozen instrument. Native rank codes are decoded against that exact
order. This detects accidental package/identity mixups; it does not independently
authenticate the author of arbitrary organizer-supplied JSON or forged metadata.
Live hosted identity behavior must be checked in the cohort pilot.

## Explicit CLI workflow

The following shows teams; replace `teams` with `reviews` for review collection.
Use your own market and contact files.

```bash
roth teams field build classroom/market.json --contacts contacts.json --output classroom/field
roth teams field status classroom/field
```

Inspect `classroom/field/assessment/preview.html` and `handoff.json`. Each package
has a native survey, Jobs, AgentList, required-answer schema, and a question map.
The handoff includes exact `ep humanize create` arguments and the corresponding
Roth registration command. Execute creation only within the organizer's scope.

Register each returned Humanize UUID with its package:

```bash
roth teams field register classroom/field --package PACKAGE_ID --uuid HUMAN_SURVEY_UUID
```

Registration returns status, delivery-history, invitation, and response-retrieval
commands. An invitation command is supplied only when an email contact is present.
Inspect existing deliveries before retries. `--delivery DELIVERY_UUID` records a
known delivery. No network action is executed by registration itself.

After authorized delivery, retrieve each package's Results and import it:

```bash
roth teams field import classroom/field assessment-results.ep --edsl
roth teams field status classroom/field
```

Repeat imports for all assessment packages. Status lists missing respondents and
packages. There is no automatic deadline exclusion or invented completion record.
Then build the ranking wave, if status reports outstanding rankings:

```bash
roth teams field rank classroom/field
```

Inspect the new ranking round's preview and handoff, create/register/deliver those
surveys, and import their Results. Finally export preferences and solve:

```bash
roth teams field import classroom/field ranking-results.ep --edsl
roth teams field export classroom/field --output classroom/human-preferences.json
roth teams solve classroom/market.json --preferences classroom/human-preferences.json --output classroom/human-report
```

The export validates the complete preference cohort using the solver's input
contract. It writes a new JSON file and a `.collection.json` companion with market,
assessment, and preference hashes, sources, and assessment decisions. The original
market, questionnaires, answers, and history stay inside the private field
folder. Source labels remain `human` or `synthetic`; mixed-source respondent
records are conservatively labeled synthetic.

## Offline JSON imports, revisions, and integrity

`field build --json-only` produces previews and response templates without EDSL.
It cannot provide runnable Humanize Jobs. For a manual import, fill the saved
`responses-template.json` using exact labels and question names:

```json
[
  {
    "package_id": "COPY_FROM_TEMPLATE",
    "participant_id": "s01",
    "submission_id": "stable-submission-id",
    "answers": {"assess_0": "Include in my ranking"}
  }
]
```

All questions displayed in the package require answers; this is only an excerpt.
Use `field import FIELD_DIR responses.json` without `--edsl`. Direct imports trust
the importing organizer's declared identity and source. JSON rank responses use
exact option labels, while native Results may use zero-based codes.

A new response for a previously answered package requires `--replace`. A reused
submission ID with different content is rejected. Replaying an older unchanged
submission does not roll back a later revision. Import validation is atomic with
respect to saved collection state: an invalid row prevents the entire import from
being committed. Assessments and rankings must be imported in separate calls.

Assessment revisions conservatively invalidate **all existing ranking rounds**
in the collection. Their artifacts and responses remain in history; build and
collect a new ranking round for the revised selections. Existing exports remain
unchanged, and guidance creates a new preference file before solving again.

Each field directory owns a hash-chained `.roth` event history with immutable
state objects. It is separate from the stable-matching market store. Keep the
entire field directory private: it contains contacts and individual answers.
A failed artifact build can leave an unregistered folder; inspect it and select
a fresh output path rather than silently overwriting it.

## Synthetic pilot and live-pilot boundary

Run the reproducible offline pilot from a checkout:

```bash
PYTHONPATH=src python scripts/collection_pilot.py /tmp/roth-collection-pilot --native
```

Use a new output directory. The script uses explicit fictional preferences,
constructs/reloads EDSL Results for every package, imports them with
`--source synthetic` semantics, exports preferences, and runs both solvers.
There are 60 team packages and 24 review packages across two waves per mode.
It makes zero inference calls and sends zero invitations. Synthetic response
imports are accepted only when the frozen market declares `synthetic: true`, and
cannot replace a human response.

[Inspect the dry-run previews and outcomes](collection-example/index.html).
Native survey construction, rank decoding, binding checks, response completion,
and downstream solving pass locally. Hosted presentation, email delivery,
respondent identity behavior, and usability still require the actual cohort,
its contact map, and authorized invitations. No live classroom pilot is claimed.
