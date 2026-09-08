# roth — matching, teams, and peer-review assignment
<!-- id: roth/roth -->

<p align="center">
  <img src="docs/assets/roth-package.png" width="760" alt="Roth package artwork: two green parrots in wedding attire inside expectation brackets">
</p>

Roth collects preferences on two sides of a market and computes auditable,
one-to-one or many-to-one stable matches. The internship example assigns students to individual
internship openings. An organizer controls direct ranking, delegated LLM
preferences, and whether participants must confirm inferred rankings.

The Python matching engine and local example need no network or third-party
runtime dependencies. Human fielding and model scoring use optional native EDSL
artifacts, with execution through `ep`.

Roth also forms student teams and assigns their projects jointly, using ranked
teammate and project preferences converted to Borda scores. This separate mode
uses integer programming with an optional local solver. A separate peer-review
mode assigns submissions to reviewers with required coverage, workload limits,
and authorship/team conflicts.

Roth can:

- collect strict rankings and unacceptable options from both sides through
  personalized Humanize surveys;
- prepare LLM scoring jobs from natural-language preference descriptions,
  with optional participant confirmation;
- benchmark inferred preferences against an optional A-versus-B survey;
- compute deferred-acceptance matches from a frozen set of preferences; and
- report realized ranks, unmatched participants, coverage, and stability checks.

**[Read the illustrated internship walkthrough](https://expectedparrot.github.io/roth/)**
to see the actual preference inputs, import commands, and a matrix of both sides'
rankings with the resulting matches. [HTML source](docs/index.html).

## Install and try the example

Requires Python 3.11+.

```bash
python -m pip install "roth @ git+https://github.com/expectedparrot/roth.git@main"
roth demo internship-demo
```

Open `internship-demo/report/index.html` for the organizer report, and
`internship-demo/surveys/preview.html` for survey previews. The demo uses **explicit
fictional rankings**, makes no model calls, and sends no emails. It includes 12
students, 10 single-slot internship openings, unacceptable partners, and unmatched
participants. A generated [example report](examples/internships/report/index.html)
and [survey preview](examples/internships/surveys/preview.html) are included here.

For human surveys and delegated scoring, install the optional fielding dependency:

```bash
python -m pip install "roth[fielding] @ git+https://github.com/expectedparrot/roth.git@main"
```

For development from a checkout, use `python -m pip install -e '.[test,fielding]'`.

## Copy and paste into a coding agent

```text
Set up Roth and help me with my matching or team-assignment problem.

Install Roth in an isolated Python 3.11+ tool environment. If uv is missing,
install it with `python -m pip install --upgrade uv` first:

uv tool install --python 3.11 --with-executables-from edsl \
  "roth[fielding,teams,reviews] @ git+https://github.com/expectedparrot/roth.git@main"

Check the available interfaces:

roth version
roth capabilities
roth agent next
ep --help

Use the intake questions to identify the structure of my problem, reusing
answers already in our conversation. Do not pick a method just because I
mention students, internships, or mentors.

For two distinct sides with at most one partner each, use:
roth --project STUDY agent next --scenario one-to-one

For one side accepting several partners under fixed capacities, use:
roth --project STUDY agent next --scenario many-to-one

For forming student teams and assigning each team a distinct project, use:
roth --project STUDY agent next --scenario teams

For assigning several reviews per person and several reviewers per submission:
roth --project STUDY agent next --scenario reviews

Help me define the participant lists, preferences, and organizer rules. Ask
only for missing decisions. Follow the guidance's applicable next_steps within
my authorization, then run its returned data.rerun command. For existing
files or projects, let agent next inspect progress before proposing new work.

If I need stable many-to-many matching, roommate matching, repeated projects, or another
unsupported structure, explain the limitation rather than silently converting
it into a different problem. Use synthetic examples only as labeled demos;
never substitute them for missing real preferences.

Finish by showing me the inputs, assignments, preference statistics, and any
unmatched participants, unfilled slots, or assignment compromises. Explain stability scope
for deferred acceptance and solver optimality/limits for team optimization.
Preserve previous submissions, snapshots, and reports.

Review generated surveys and scoring plans with me before sending real
invitations or making paid model calls. Let ep manage authentication.
```

## When to use this

Use the stable matching workflow when two sides rank one another: students and
internships, employees and mentors, or students and faculty advisers. Each person
on one side gets at most one partner; participants on the other side may accept
several. Either side may propose. Participants can reject options and slots can
remain vacant. Capacity is an upper bound, not a required fill level.

Many-to-one matching assumes **responsive preferences**: a mentor ranks individual
mentees independently of who else is assigned. Couples, minimum staffing levels,
and preferences over combinations need a different formulation.

The organizer supplies stable participant IDs, public profiles, eligibility
rules, and either explicit rankings or natural-language preference instructions.
Contact information is needed only for human recruitment. Each mentor or program
has one ID, one ranking, and a `capacity`; omitted capacity defaults to one.

## Many-to-one example: employees and mentors

The fictional example has **30 employees and 10 mentors, each with capacity 3**.
Both sides supply explicit synthetic rankings. Inspect the input files, then
import and freeze them before matching:

```bash
roth example mentorship mentorship-demo
roth --project mentorship-demo agent next
roth --project mentorship-demo preferences import mentorship-demo/preferences.json
roth --project mentorship-demo preferences freeze --name main
roth --project mentorship-demo match --snapshot main --name main
roth --project mentorship-demo report --run main --output mentorship-demo/report
```

`example mentorship` only creates the study and input files. It does not import
preferences or run matching. Use `--employees`, `--mentors`, and `--capacity` to
change the example sizes. No solver dependency or network is needed.

[Open the worked mentorship report](docs/mentorship-example/index.html) for the
rankings/matches matrix, all assigned partners, and capacity utilization.
See the [many-to-one guide](docs/many-to-one.md) for the Python API and assumptions.

## Peer-review example

Give each of 12 fictional students three essays to review, and each essay three
reviewers. Self-review, review of a teammate's essay, and declared conflicts are
forbidden. Rank submissions or supply expertise scores; the optimizer maximizes
assignment quality within the hard coverage and workload rules.

```bash
python -m pip install -e '.[reviews]'
roth reviews example classroom-reviews
roth --project classroom-reviews agent next
roth reviews solve classroom-reviews/market.json --preferences classroom-reviews/preferences.json --output classroom-reviews/report
```

The install command is for a local checkout; the `reviews` extra uses the same
SciPy/HiGHS dependency as `teams`. `reviews example` writes synthetic inputs without
solving. The worked example makes 36 assignments, with 29 in the reviewer's top
three. [Open the ranking/assignment matrix](docs/reviews-example/index.html) or
read the [review-assignment contract and formulation](docs/reviews.md).

Unranked or unscored eligible submissions receive zero objective score and may
still be assigned; explicit conflicts remain forbidden. Wider workload bounds
permit unequal loads. This mode does not claim stability or strategy-proofness.
Humanize surveys are available through `reviews field`; delegated review scoring remains future work.

## Agent workflow

```bash
roth agent next
roth --project classroom agent next --scenario teams
roth --project classroom-reviews agent next --scenario reviews
roth --project mentorship-demo agent next --scenario many-to-one
roth --project internship-demo agent next
roth guide
```

`agent next` is a read-only guide for the calling agent. In a new directory it
provides scenario-selection questions; with a market or saved project it
identifies the next stage and returns an explanation, missing decisions, and
executable command arguments. It distinguishes existing rankings, human surveys,
delegated scoring, required confirmations, team optimization, and review assignment. It never
executes its recommended actions. See the [agent guidance contract](docs/agent.md).

For custom paths, pass `--market`, `--preferences`, and (for teams/reviews) `--output`
after `agent next`. Use `--collection rankings`, `human`, or `delegated` to
record how remaining preferences will be supplied. `data.rerun` preserves those
choices and follows any newly selected report directory.

Commands emit one versioned JSON envelope with `status`, `data`, `errors`, and
`next_steps`. Failures exit nonzero. `--human` opts into indented data. Global
options, including `--project`, precede the command. Artifact paths are relative
to the current working directory, independently of the project directory.

Roth builds reviewable execution packages. It never automatically runs inference,
publishes a survey, or sends invitations. `handoff.json` contains explicit `ep`
argument arrays; inspect the instrument, recipients, and cost before external
execution. Let EDSL manage authentication.

## Form teams and assign projects together

**[Open the worked team-assignment report](https://expectedparrot.github.io/roth/teams-example/)**
to see all input rankings, Borda scores, the realized teams, and both preference
matrices. The fictional example has 12 students and five projects; the joint
optimum forms four teams of three and leaves one project unused.

From a source checkout:

```bash
python -m pip install -e '.[teams]'
roth teams example classroom
roth teams validate classroom/market.json --preferences classroom/preferences.json
roth teams solve classroom/market.json --preferences classroom/preferences.json \
  --output classroom/report --time-limit 60
```

`teams example` writes inputs without solving. Students may provide partial,
strict rankings of projects and teammates. Unlisted options earn zero points;
explicit exclusions remain hard constraints. Every student needs a completed
submission. The organizer sets target size, permission and bounds for smaller
or larger teams, and the weight on teammate preferences.

The SciPy/HiGHS integer program minimizes deviation from target team size, then
maximizes the combined normalized Borda score. Each project takes at most one
team. The report preserves the inputs and records optimality or solver limits.
This mode uses explicit files and new output directories, independently of
`--project` and the stable-matching store. Use `teams field` for Humanize assessment and ranking surveys. See the [formulation and data contract](docs/teams.md).

## Direct preferences and matching

```bash
roth example create study
roth --project study preferences import study/preferences.json
roth --project study preferences freeze --name main
roth --project study match --snapshot main --name main
roth --project study report --run main --output study/report
```

`example create` initializes the project and writes synthetic fixtures; it does
not import them until requested. For real data, use `roth init market.json`, or
`roth init --left students.csv --right internships.csv`. Side files may also be
JSON participant lists or EDSL AgentLists. See [data contracts](docs/contracts.md).

Deferred acceptance uses strict rankings, allows unequal side sizes and empty
acceptable lists, and never pairs participants without mutual acceptability.
The organizer sets the proposing side; `match` also computes the reverse
orientation by default. Each run saves a proposal trace and independently checks
feasibility and blocking pairs. Many-to-one matching is deferred.

Nonresponse is distinct from rejection. Freeze requires preferences from every
active participant. `preferences freeze --exclude ID` explicitly removes a
nonrespondent from that snapshot. Unknown candidates remain unknown in stored
preferences; they are excluded from the matching graph unless the organizer
requires complete evaluation. Reports state the cohort, coverage, and preference
source. Stability refers to this frozen graph and its submitted or inferred
preferences, not unobserved human preferences.

## Human surveys for teams and peer review

Both optimization modes can collect preferences through personalized Humanize
surveys, with assessment batches followed by a cross-batch ranking of selected
options. Review expertise mode instead collects 0–100 ratings in increments of 10.
Private contact maps stay separate from the solver inputs.

```bash
roth --project classroom agent next --scenario teams --collection human --contacts contacts.json
roth --project classroom-reviews agent next --scenario reviews --collection human --contacts contacts.json
```

The agent guides survey construction, response tracking, ranking, preference
export, and solving. `--collection human` prioritizes collection over any canned
synthetic preference file. A completed export gets a new filename; prior inputs
and responses are preserved.

[Read the collection workflow](docs/collection.md) and [inspect the synthetic
pilot previews](docs/collection-example/index.html). The offline pilot exercises
native EDSL survey/Results round trips and both solvers; it sends no invitations.
Live Humanize delivery and participant usability still need a real cohort pilot.

## Humanize surveys and invitations

```bash
roth --project study field build --name rankings --output study/rankings
```

Each participant gets a distinct `survey.ep`, `agent_list.ep`, `jobs.ep`, question
map, and Humanize schema. Student surveys show internship profiles; internship
surveys show student profiles. An opening's ID is distinct from its employer
representative's contact. Candidate profiles omit private instructions and
contact information.

Participants rank candidates and **Remain unmatched**, then identify candidates
they could not assess. Assessed candidates below the outside option are rejected;
unassessed candidates remain unknown. No ties are accepted in direct rankings.

Review `preview.html` and `handoff.json`. Execute the generated Humanize creation
command externally, then record its returned UUID:

```bash
roth --project study field register --field rankings \
  --package rankings_s001_1 --uuid HUMAN_SURVEY_UUID
```

Registration returns commands to inspect status, create an invitation delivery,
and retrieve responses. Invitation routes select never-contacted respondents.
Review existing deliveries before retrying; register returned delivery IDs with
`--delivery UUID`, and preserve downloaded status JSON with `--status-json FILE`.
The canned example has no email addresses; real recruitment requires contact
emails supplied by the organizer.

```bash
ep humanize responses HUMAN_SURVEY_UUID --output student-results.ep
roth --project study field import student-results.ep --name rankings --edsl
roth --project study field status --name rankings
```

Imports validate the respondent/package mapping and all required answers. Use
`--replace` for an explicit revised submission; prior records remain in history.
Native EDSL package and Results round trips are tested locally. Hosted ranking
presentation, participant binding, and email delivery require a service pilot
before real recruitment; no live invitations were sent during development.
The optional fielding dependency is pinned to the EDSL revision used for these checks.

## Handling long lists

The direct-ranking budget defaults to 15 candidates. Roth blocks oversized
rankings and offers explicit alternatives:

```bash
roth --project study field build --name screening --kind screening \
  --batch-size 10 --output study/screening
# Import completed screening batches, then build a cross-batch ranking:
roth --project study field build --name final-ranking --output study/final-ranking
```

Screening collects acceptability without inventing a global order from separate
batches. After screening, final ranking includes accepted candidates; rejected
and unknown candidates retain their respective states. If many acceptable options
remain, explicitly raise `--max-options`, or use `--plan PLAN_NAME` to restrict
fielding to a retrieved shortlist. Follow-up rounds and larger retrieval plans
produce new preference revisions and matching snapshots.

## Delegated preferences and the optional benchmark

See the complete [delegation walkthrough](docs/delegation.md) for:

- collecting natural-language instructions through Humanize;
- bidirectional lexical retrieval, audited expansion, and cached directional scores;
- external EDSL inference and validation of partial Results;
- optional A-versus-B calibration and held-out prediction evaluation;
- participant confirmation when required by the organizer; and
- synthetic fixtures for exercising the whole pipeline without paid inference.

The [200-student / 150-opening scale example](examples/scale-summary.json) compares
shortlists and an expansion round with the full fictional preference market.
Run `python scripts/scale_demo.py --output new-scale-summary.json` to reproduce it.
Retrieval ties use a participant-specific seed to avoid always showing the same
low-ID candidates when lexical relevance is equal.

## Provenance and reports

`.roth/` contains locked, append-only events referencing immutable hashed state
objects. Preference revisions preserve previous submissions. Snapshots and runs
are immutable; policy changes require new fielding/scoring plans. `validate`
checks the history chain, snapshot hashes, and saved matching stability.

Organizer exports include HTML, matches CSV/JSON, preference JSON, and separate
individual JSON summaries containing only the assigned partner's public profile.
Statistics cover completion and evaluation coverage, demand concentration, mutual
top-three interest, assigned-partner ranks, unmatched reasons, and proposer
sensitivity. Scores and rank sums are not presented as cardinal welfare.

Run checks with:

```bash
python -m compileall -q src
python -m pytest -q
python -m build --no-isolation
```

## License

MIT. See [LICENSE](LICENSE). The bundled internship participants and preferences
are fictional.
