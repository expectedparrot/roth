# Roth — working specification

Status: implemented through Roth 0.3.0 on 2026-09-07; the initial design and subsequent extensions are recorded below.
See `README.md`, `roth guide`, and `docs/` for the implemented commands and contracts.
The package name follows the current
directory. One-to-one matching for the initial release, deferring many-to-one
matching, and an optional pairwise preference calibration and benchmark survey
are agreed. The organizer sets delegation and confirmation policy. The survey
separates answers used for refinement from held-out answers used for evaluation.
The canned example matches students with internships. Other details remain
proposed, with open decisions at the end.
The initial implementation includes the deterministic engine, local history,
survey and email handoffs, delegated scoring, optional calibration/benchmarking,
and reports. Native EDSL package/Results round trips are tested offline; hosted
Humanize delivery and real model preference quality still require a live pilot.
Retrieval initially uses lexical matching with participant-specific seeded tie
breaking; eligibility rules are supplied as explicit allowed/excluded edges.

## Purpose and package conventions

Roth helps an organizer define a two-sided market, collect or infer individual
preferences, compute deferred-acceptance matches, and inspect preference and
matching statistics. The initial worked example matches students with internship
openings. Side names remain configurable for other two-sided applications.

Follow the neighboring Bewley, Katz, and Green packages: a local Python package
and agent-friendly CLI, JSON output by default, `guide`, `next`, `status`, and
`capabilities`, durable project history under `.roth/`, and portable artifacts.
Keep the deterministic matching engine usable through Python without EDSL or
network access. Use EDSL for human survey and model execution handoffs.

## Market definition

Import the two sides from CSV, JSON, or EDSL AgentLists. Each participant has a
stable ID, side, display name, candidate-facing profile, and optional structured
attributes. Contact information and private preference instructions are stored
separately from the profile shown to potential partners.

An organizer defines eligibility rules, an outside option (remaining unmatched),
the proposing side, deadlines, delegation and confirmation policy, and the policy
for incomplete participation.
Distinguish organizer eligibility constraints from individual acceptability.
Unequal side sizes and participants with no acceptable partners are valid.

Agreed initial matching scope: one-to-one. Proposed preference support includes
incomplete strict rankings. Many-to-one matching is deferred to a later release.
The proposed later extension uses a fixed capacity on one side and responsive
preferences: the institution selects its highest-ranked acceptable applicants
up to capacity, without complementarities among them.
Couples, group composition constraints, and many-to-many matching require
separate designs.

## Canned example: students and internships

Agreed application: a fictional internship placement program. Each student can
receive one internship, and each internship opening can accept one student. An
employer representative supplies preferences on behalf of an opening. Keep the
opening's identity separate from its respondent/contact identity.

Proposed small example: 12 students and 10 distinct, single-slot openings, with
fictional profiles and no deliverable email addresses. Include competing demand,
different acceptable sets, and unequal side sizes so unmatched outcomes are part
of the walkthrough. This example does not require capacity handling.

- Student profiles: skills, relevant coursework, project experience, interests,
  availability, and location or remote-work constraints.
- Internship profiles: work description, required and preferred skills, dates,
  location or remote arrangements, hours, compensation, and mentoring offered.
- Student preference instructions: desired work and learning opportunities,
  tradeoffs among mentoring, compensation, and location, and dealbreakers.
- Employer preference instructions: role-specific skills, project experience,
  learning potential, and confirmed availability requirements.

Use the same profiles for a direct-ranking walkthrough and a delegated-preference
walkthrough, including optional A-versus-B calibration. For example, a student
compares stronger mentoring with higher compensation, while an employer compares
relevant coursework with practical project experience. Hypothetical benchmark
variants are labeled and cannot become actual matching candidates.

Ship explicit fictional rankings and benchmark answers for a reproducible local
demo. Keep those fixtures distinct from fresh model-generated predictions. Show
survey previews without sending invitations; real fielding uses organizer-supplied
contacts. Proposed example configuration: students propose, with the reverse
orientation available for comparison. Internship terms are fixed inputs.

A separate generated synthetic scale example can exercise retrieval, evaluation
budgets, and shortlist expansion; the small example alone does not demonstrate
large-market efficiency.

## Shared preference representation

Both collection modes produce versioned individual preference records. Preserve
the underlying human answers or model outputs, candidate exposure, profile
versions, source, and any transformation into an ordered list.

Represent acceptable, unacceptable, and unevaluated candidates separately.
An omitted candidate is not automatically a rejection. A final preference
snapshot must explain how every unresolved omission is handled: collect more
information, infer it under an explicit delegation policy, or exclude that edge
from this matching run while retaining its unknown status in the source data.

Store the outside option explicitly. Never match a pair that either side has
rejected. Human-confirmed preferences take precedence over model suggestions;
inference cannot silently overwrite an explicit choice.

## Mode 1: direct preference collection

1. Generate a personalized survey showing eligible opposite-side profiles.
2. Let the participant reject unacceptable candidates and rank the acceptable
   ones. Support an explicit preference for remaining unmatched over any partner.
3. Build native EDSL artifacts and a preview, preserving participant and
   candidate IDs independently of their display names and question order.
4. Use Humanize to host the surveys and send participant-specific email
   invitations. Track the returned survey/respondent identifiers and available
   delivery and completion status. Retries must avoid duplicate invitations.
5. Import responses incrementally. Detect unknown IDs, repeated candidates,
   incomplete responses, and revisions. Preserve previous submissions and make
   the active submission rule explicit.
6. Freeze the active cohort and preference snapshot before final matching.
   Default: require completed preferences for all active participants; allow an
   organizer to close with an explicitly reduced cohort. Nonresponse is not
   rejection, and partial-cohort runs are labeled accordingly.

Email wording and recipient mappings should be reviewable before sending.
Preference collection and result notification are separate operations. Hosted
identity binding, ranking presentation, and delivery behavior need an integration
pilot before using real participants. Local EDSL source exposes Humanize Jobs,
AgentLists, delivery maps, respondent email routes, and response retrieval; this
draft does not assume the hosted end-to-end workflow has been tested.

### Too many candidates

Plan around respondent burden, not simply market size. Start with configurable
budgets for profiles reviewed and ranking/comparison tasks. An initial UI
hypothesis is direct ranking for roughly 10–15 eligible candidates, subject to
pilot evidence rather than treating that number as a validated threshold.

For larger sets, apply explicit eligibility filters, then review profiles in
batches and build a shortlist. Batch-local rankings alone do not establish a
global order: finish with a cross-batch ranking or targeted comparisons. Offer
candidate search and an expansion round when a participant exhausts their list.
Record candidates shown, reviewed, selected, rejected, and never seen.

If reviewing everyone exceeds the budget, offer either a deliberately restricted
market or delegated candidate discovery. Explain the resulting coverage. An
adaptive follow-up round can expand lists for unmatched participants and their
prospective partners; each round creates a new frozen snapshot and matching run.

## Mode 2: delegated preferences for large markets

Agreed: the organizer selects the preference collection mode and whether inferred
rankings are used directly or require participant confirmation. Participants do
not independently choose the delegation mode. Explain the configured workflow in
their survey instructions. Proposed configuration supports a market-wide policy
with optional overrides by side; benchmark requirements and any review triggered
by benchmark results are also organizer settings.

Participants describe what they seek in natural language, including must-haves,
tradeoffs, dealbreakers, and when they prefer no match. Keep this separate from
their description of what they offer. A structured interpretation can be shown
for correction; ambiguous language must not silently become an exclusion rule.

Proposed pipeline:

1. Apply confirmed hard constraints using structured attributes where possible.
   Missing evidence is unknown, not proof that a requirement is met or violated.
2. Retrieve candidates in both directions using structured filters and optionally
   semantic search. Take the union of both sides' suggestions so an edge need not
   appear on both independently generated shortlists to receive consideration.
3. Score retained edges in both directions against the respective participant's
   instructions. Return acceptability, criterion-level evidence, a within-person
   score, and an explanation. Distinguish missing evidence from a negative score.
4. Resolve consequential near-ties with targeted comparisons or participant
   review. Produce one frozen, consistent order per participant before matching;
   fresh LLM comparisons during DA must not change the underlying preference order.
5. Expand retrieval for exhausted lists and audit a sample of omitted edges for
   missed opportunities. Stop at declared budget or convergence criteria, then
   freeze the evaluated graph and preferences for the final run.

Cache by participant instructions, candidate profile, rubric, prompt, and model
configuration, and preference-calibration version. Batch independent evaluations,
preserve outputs, and retry only
missing or invalid work. Scores rank candidates for one participant; they are
not automatically comparable across participants or a measure of social welfare.

For side sizes n and m, exhaustive two-direction scoring requires 2*n*m directed
evaluations. Retrieving at most k candidates per participant yields at most
k*(n+m) distinct initial edges before deduplication and expansion, each requiring
two directional evaluations. Report evaluation counts separately from API call
counts, retrieval cost, tokens, and subsequent expansion cost. Do not promise
full-market stability or subquadratic worst-case work from heuristic retrieval.

Hybrid use should share this representation: the organizer can require humans to
approve or edit inferred shortlists and can configure different collection methods
for the two sides. Synthetic respondents used for demonstrations must be labeled
separately from real participants whose preferences are inferred under the
organizer's delegation policy.

### Optional pairwise preference benchmark

Before relying on delegated rankings, offer each participant a short personalized
survey of A-versus-B choices. Its purpose is to check and optionally improve the
model's interpretation of that participant's natural-language preferences without
requiring a complete ranking. Use the same Humanize invitation and response
workflow as direct elicitation. Record a skipped benchmark as unassessed.

Show two candidate profiles with a proposed response scale: strongly prefer A,
somewhat prefer A, indifferent, somewhat prefer B, strongly prefer B. Provide
separate ways to mark either candidate unacceptable or report insufficient
information. Relative preference does not establish willingness to match; a
participant can prefer A to B while rejecting both. An optional explanation can
clarify the tradeoff. Randomize display order and hide model predictions until
the participant answers.

Use real eligible candidates by default. Hypothetical profiles may help isolate
tradeoffs, but must be labeled and kept separate from actual candidate rankings.
Propose a configurable mix of representative candidate pairs and diagnostic pairs
where the model is uncertain or important stated preferences conflict. Preserve
the selection method and candidate pool; report representative and targeted
results separately. A benchmark restricted to retrieved candidates does not
validate candidate discovery across the whole market.

Assign calibration and held-out evaluation questions before inspecting answers.
Calibration answers and explanations may update the preference instructions or
scoring rubric; this need not involve training model weights. Freeze the revised
model configuration and its predictions before revealing held-out answers to it.
Report initial and revised agreement on the same held-out questions, with counts,
ties, abstentions, and acceptability errors shown explicitly. A short survey is
limited evidence, not certification of the participant's full preference order.

Once held-out answers inform a further revision, retire them as a fresh benchmark
and use new questions for further evaluation. For matching, preserve all explicit
human choices as evidence, including retired benchmark answers. Detect cycles or
conflicting answers and seek clarification before claiming a confirmed strict
ranking; pairwise answers need not determine a complete order.

Show the participant a summary of disagreements and any proposed interpretation
changes. Under the organizer's configured workflow, offer further comparisons,
editing the preference description, or direct ranking. Whether benchmark
performance gates delegation remains an organizer policy setting whose default
is open; do not silently convert low agreement into successful validation.

## Matching and guarantees

Run deferred acceptance on a frozen, mutually acceptable candidate graph with
strict rankings and a declared proposing side. Save the proposal trace, matched
pairs, unmatched participants and algorithmic reasons, configuration, and input
hashes. Verify feasibility and absence of blocking pairs within that graph.

Allow comparison of runs with either side proposing. Under the standard strict
one-to-one model, the proposing side obtains its best stable outcome. This is a
substantive market-design choice, not an incidental implementation default.

If ties are introduced, preserve them and document a reproducible tie-breaking
rule. DA on the resulting strict refinement provides weak stability for the
original tied preferences; it need not maximize the number of matches. Defer
strong/super-stability and optimization among tied stable outcomes.

Every output identifies the active cohort, preference source, coverage, and
stability scope. Full elicitation can support a full-market claim relative to
submitted preferences. A shortlist run certifies the restricted graph. Delegated
rankings support claims relative to those inferred preferences, not unobserved
human preferences. An audit of omitted edges is a diagnostic, not a certificate.

## Analysis and outputs

- Collection: response/completion rates by side, candidate exposure, list lengths,
  explicit rejections, unresolved candidates, and directional evaluation coverage.
- Preferences: first-choice and top-k demand concentration, overlap between
  participants' rankings on common evaluated candidates, and mutual top-k interest.
- Delegation benchmark: held-out choice agreement per participant and by side,
  before/after calibration, response counts, ties, insufficient-information rates,
  and acceptability errors. Separate representative from diagnostic questions and
  identify participants whose delegated preferences remain unassessed.
- Outcomes: match/fill rates, unmatched reasons, assigned-partner rank distributions
  by side, top-k assignment rates, and blocking-pair checks within the stated scope.
- Sensitivity: changes when the proposing side, shortlist size, inferred rankings,
  or tie-breaking seed changes. Quantify differences without calling rank sums
  cardinal welfare or treating model self-confidence as calibrated uncertainty.
- Exports: machine-readable matches and preferences, an organizer HTML report,
  and optional individual result summaries. Individual summaries do not expose
  the other side's private rankings or preference instructions.

Give every rate an explicit denominator. Shortlist rank is not full-market rank.
Account for exposure when reporting popularity; unshown candidates did not receive
a chance to be selected. Keep human, delegated, and synthetic evidence distinct.

## Proposed implementation sequence

1. Market import, preference validation, deterministic one-to-one DA, verifier,
   statistics, and the canned students/internships example with unequal sides and
   rejected pairs.
2. Humanize survey artifacts, personalized invitation workflow, response ingestion,
   revisions, cohort closure, and direct-ranking reports.
3. Batched human elicitation and shortlist expansion with explicit coverage.
4. Natural-language preference collection, EDSL scoring jobs, bidirectional
   retrieval, caching, expansion, optional pairwise calibration and benchmarking,
   and human review of delegated preferences.

Later release: many-to-one matching with capacities; excluded from initial-release
requirements.

Acceptance examples should exercise a known blocking pair, nonresponse, an empty
acceptable list, interrupted fielding, a shortlist that misses a desirable pair,
and a changed preference snapshot. Benchmark examples should cover held-out answer
leakage, conflicting pairwise choices, and preferring A while rejecting both A and B.
Integration pilots must demonstrate that each
respondent sees their intended candidates and their answers return to the correct ID.

## Decisions to discuss

1. Realistic human review budgets and the size of the synthetic scale example.
2. Defaults for the organizer's delegation settings: use inferred rankings directly
   or require participant confirmation; whether the optional pairwise benchmark
   is advisory or gates delegation; and how much survey burden is acceptable.
3. Default proposing side and whether both orientations are always reported; the
   organizer controls the choice.
4. Whether restricted-market stability is sufficient, or exhaustive coverage is
   required for a particular application.

## Joint team/project extension — implemented in 0.2

Students may rank both projects and potential teammates. The organizer sets a
target team size and whether smaller/larger teams are allowed, with explicit
bounds. Each student is assigned once and each project hosts at most one team.
This is a separate optimization workflow, not many-to-one deferred acceptance.

The agreed first mechanism converts strict, possibly partial rankings to Borda
scores and solves team formation and project assignment jointly as a MILP.
Project IDs label teams, eliminating anonymous group-slot symmetry. Pairwise
co-membership products are linearized exactly. The mechanism first minimizes
absolute deviation from the target team size, then maximizes the weighted sum
of normalized project and teammate Borda scores. Directed teammate scores are
retained and both directions contribute to the aggregate objective.

Unlisted candidates earn zero points under the declared scoring policy, while
remaining distinct from explicit project exclusions and teammate incompatibilities.
Every student needs a completed submission; hard constraints are never relaxed
silently. Optional SciPy/HiGHS execution reports bounds, solver limits, and whether
optimality was established. Each export freezes the input files, scoring rules,
assignments, and a human-readable matrix report. A fictional classroom example
and exhaustive small-market verification accompany the implementation.

Strategy-proofness, HZ-style prices or lotteries, point budgets, fairness floors,
skill coverage, repeated projects, and team-specific Humanize fielding are not
part of this first extension. See [the full formulation](docs/teams.md).

## Agent intake and next-step guidance

`roth agent next` is the shared, read-only entry point for a calling agent.
Before a project exists it provides structural routing rules and questions:
two-sided one-to-one or many-to-one matching versus joint team/project optimization.
Many-to-many, roommate, and other unsupported structures are not silently transformed into
supported ones. The agent uses the user's description and prior answers, then
records the selected scenario and collection method through flags and input files.

For existing inputs, guidance validates schemas and resumes the applicable
workflow: ranking imports, human surveys and screening, delegated scoring,
required confirmations, freeze/match/report, or the team solver. It returns
explanations, unresolved questions, and exact command arrays with mutation and
network/authorization metadata. It never executes commands, sends questions,
launches inference, or changes files. Each response can include a rerun command
that preserves the intended inputs and newly selected report path.

Team reports are checked against normalized input hashes and independently
recomputed assignments/scores; solver limits remain explicit. One-to-one
guidance checks freeze prerequisites on an in-memory state copy. Existing
reports, submissions, and organizer policy decisions remain authoritative until
an explicit revision is made. See [the interface contract](docs/agent.md).

## Background sources

- [Roth's Nobel lecture](https://www.nobelprize.org/uploads/2018/06/roth-lecture.pdf)
  describes deferred acceptance, stability, and the significance of the proposing side.
- [Manlove et al., Hard Variants of Stable Marriage](https://www.dcs.gla.ac.uk/~davidm/pubs/TR-1999-43.pdf)
  discusses ties, incomplete lists, and the complexity of optimizing matching size.
- Local integration references inspected: `../green/green/docs_content/codegen.md`,
  `../edsl/edsl/jobs/jobs.py`, `../edsl/edsl/cli_commands/humanize.py`, and
  `../edsl/edsl/coop/coop_humanize_notifications.py`.

## Many-to-one extension (0.3.0)

The previously deferred capacity extension is implemented. Participant capacity
is a nonnegative integer, default one; at most one side may have capacities
above one. Zero closes a position. Deferred acceptance works in either proposing
orientation without synthetic slot IDs. Preferences are strict individual
rankings interpreted responsively, with unacceptable/unknown edges retained
under the existing contracts. No minimum fill, group complementarities, couples,
or many-to-many behavior is implied.

Frozen snapshots include capacities. Independent verification checks quotas,
mutual acceptability, duplicate edges, and blocking pairs against a vacancy or a
lower-ranked incumbent. Reports retain every partner, expose vacancies separately
from unmatched participants, and show both directional ranks in a matches matrix.
The mentorship example has 30 fictional employees and 10 mentors with capacity
three. Existing human/delegated collection and agent guidance share this mode.
See [the guide](docs/many-to-one.md) for commands and API details.
