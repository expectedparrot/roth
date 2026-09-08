# Guidance for the agent using Roth

After a completed report, `agent next` includes optional `what_if` guidance.
Identify the organizer's baseline and named rule changes, write a scenarios JSON
array, and use `roth compare BASELINE_REPORT --scenarios FILE --output NEW_REPORT`.
Explain individual assignment changes, baseline-scale scores/ranks, review
workloads, and infeasible scenarios. Preserve the baseline and do not adopt or
deliver a scenario automatically. See [the comparison guide](comparisons.md).

Start with:

```bash
roth agent next
```

The command is read-only and works before any project exists. It gives the
calling agent questions to resolve with the organizer, an explanation of the
next stage, and applicable command arguments. It does not launch an LLM,
classify free text, ask questions directly, or execute suggested commands.
The calling agent interprets the conversation and reuses decisions already made.

## Identify the problem by structure

| Scenario | When it applies | Roth mechanism |
|---|---|---|
| `one-to-one` | Two distinct sides rank one another; each participant receives at most one partner | Deferred acceptance |
| `reviews` | Multiple reviews per person and multiple reviewers per submission, with coverage and conflicts | Binary assignment score optimization |
| `teams` | Form teams from one roster and assign each team its own project; students rank projects and teammates | Joint Borda integer optimization |
| `many-to-one` | One side can accept several partners under fixed capacities; the other gets at most one | Deferred acceptance with responsive preferences |
| `roommates` | Pair people from a single pool, without a distinct second side | Unsupported |
| `other` | For example, teams without projects or multiple teams per project | Clarify scope; unsupported |

The names of the participants are not enough to select a mechanism. Students
and internships can describe either one-to-one placement or a problem with
capacities. Do not duplicate capacity slots or invent projects to imply that an
unsupported mechanism has been implemented.

After identifying the scenario, continue with one of:

```bash
roth --project study agent next --scenario one-to-one
roth --project mentorship agent next --scenario many-to-one
roth --project classroom agent next --scenario teams
roth --project classroom-reviews agent next --scenario reviews
```

The default `--scenario auto` reads an existing market definition or the
stable-matching project's saved state. Explicit market files take precedence over
auto-discovery. A requested scenario that conflicts with the detected structure
produces guidance to resolve the conflict, rather than running another method.

## Resolve inputs and organizer decisions

For one-to-one and many-to-one matching, gather the two rosters, profiles, eligibility and
unacceptable options, proposing side, and organizer-controlled delegation or
confirmation policies. For many-to-one matching, also obtain each capacity and
check that preferences rank individuals independently of who else is assigned.
Capacities default to one, accept zero for closed positions, and can exceed one
on at most one side. Ask about any minimum fill requirements or group-dependent
preferences; those require another formulation. Rank all acceptable options,
even if the list is longer than capacity. The guidance includes a
`matching_contract` for these assumptions and the output denominators.
Determine how preferences will arrive:

```bash
roth --project study agent next --collection rankings
roth --project study agent next --collection human
roth --project study agent next --collection delegated
```

Explicit completed ranking files can be imported directly. Human collection
uses personalized ranking surveys; oversized lists route to screening. Model
delegation requires the organizer's policy, preference instructions, a model
and budget, and optional A-versus-B calibration/benchmark decisions. Permission
to delegate does not mean that inference has already happened. Human rankings
are still supported when the organizer permits delegation.

Existing fields and score plans route to their status and response-import
workflow. Required participant confirmations are collected before freezing.
The guide checks whether the freeze operation would pass, including complete
coverage, current evidence, and any mandatory benchmark. It performs that check
on an in-memory copy; it does not create a snapshot.

For teams, gather student and project rosters, target size, smaller/larger
permissions and bounds, the social weight, and hard exclusions. Collect each
student's project and teammate rankings in the [team input format](teams.md).
Unlisted options earn zero Borda points under that mode's declared policy;
they are not automatic exclusions. Missing submissions remain missing.
Team Humanize collection uses `teams field` with `--collection human`; delegated
team scoring remains unimplemented. Team inputs are not sent into one-to-one fielding.

## Use existing files and results

By default, `agent next` looks for `market.json` and `preferences.json` under
the global `--project` directory. For teams, it checks `report/result.json`
and `report/index.html` there. Override those paths explicitly when needed:

```bash
roth agent next --market examples/teams/market.json \
  --preferences examples/teams/preferences.json --output docs/teams-example
```

Explicit paths are relative to the current working directory. Auto-discovered
paths are relative to `--project`. Returned command arrays use absolute paths.

The stable-matching store is authoritative once initialized. An explicit market
file that differs from it triggers revision guidance. A default example file
is not allowed to silently override a later organizer policy change. Supplying
an explicit preference file lets the guide detect intended revisions even
after a project has a completed report. Conflicting records require an explicit
revision decision; previous preference history is preserved.

For team outputs, the guide compares normalized input hashes and independently
checks the saved assignment and score. If the inputs changed or a destination
is already occupied, the next solve uses a fresh directory such as `report-2`.
The returned `data.rerun` points at that new destination. A saved feasible but
time-limited assignment produces review guidance without claiming optimality
or endlessly launching retries.

## Response contract

The normal versioned JSON envelope includes:

- `data.scenario`: the selected structure, or null during intake.
- `data.phase`: the current stage, such as `identify_scenario`,
  `collect_preferences`, `solve`, or `review_results`.
- `data.instruction`: what the calling agent should do and explain.
- `data.questions`: unresolved questions, to ask only when the conversation
  and existing inputs do not already answer them.
- `data.actions` and top-level `next_steps`: applicable commands as `argv`
  arrays, with purpose and `mutates`, `network`, and `requires_authorization` flags.
- `data.rerun`: the guidance command to execute after an action or input edit.
- `data.complete`: computation and report are complete; the calling agent
  should still present and explain the outcome to the user.

Intake and scope-limit responses can have no executable next step. They are
successful guidance responses, not CLI failures. Invalid JSON, corrupted saved
history, and ordinary CLI errors still return structured nonzero errors.

Follow command metadata within the user's existing authorization. Building
local artifacts does not publish surveys, send invitations, or run inference.
Installing a missing optional solver is identified as a network/mutation step;
the guide does not perform the installation.

The older `roth next` remains available for stable-matching project progression.
Outside an initialized store it now returns the intake/file-based guidance.
Use `roth agent next` as the consistent entry point across both modes.

## Finish by explaining the outcome

For stable matching, show assignments, unmatched reasons, realized ranks,
proposer sensitivity, preference sources, and candidate coverage. Stability
is relative to the saved submitted or inferred preferences.

For team optimization, show team membership, project ranks, received teammate
preferences, unranked project assignments, and solver status. Explain the
organizer's size-first Borda objective and who bears its compromises. This
mechanism has no stability or strategy-proofness guarantee.

## Review assignment guidance

`--scenario reviews` gathers reviewers, submissions and their author IDs, declared
teams, coverage requirements, workload bounds, and the scoring choice. It detects
review inputs from `reviewers`/`submissions` or `mode: reviews`. All authors use
the roster's ID namespace; nonreviewing authors can have zero workload bounds.

Use completed rankings (`scoring: borda`), explicit scores (`scores`), or deliberate
constraints-only allocation (`none`). Unranked/unscored options score zero and
remain assignable. Conflicts and explicit unacceptable options are forbidden.
Native reviewer surveys use `reviews field` through `--collection human`.
Delegated review scoring remains unimplemented.

Guidance runs necessary feasibility checks and asks for organizer revisions if
counts cannot fit. After a solve it independently checks assignments, scores,
loads, coverage, and saved input hashes. Changed inputs select a fresh directory.
A feasible result without proof of optimality is left for an explicit accept/retry
decision. See [the review guide](reviews.md) for the full contract.

## Human collection for optimization modes

With `--collection human`, `agent next` prepares native team/review surveys even
when a canned preferences.json exists. It resumes a collection under PROJECT/field
(or `--field-dir`), checks the frozen market and contact map, tracks missing
assessments, requests cross-batch ranks, and exports solver-ready preferences
with provenance. Reuse `data.rerun`; it preserves the field and contact paths.

Completed exported preferences take precedence over old fixture inputs. Revisions
select fresh files and invalidate obsolete rankings. No-preference/insufficient
information maps to zero score, while hard exclusions remain forbidden. Overlong
selected lists require respondent revision or an explicit larger ranking budget.
`--collection rankings` explicitly bypasses collection to use supplied files.
JSON-only previews cannot be published to Humanize without a new native build.
See [collection.md](collection.md) for identity, source, and response contracts.
