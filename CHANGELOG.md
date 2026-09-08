# Changelog

## 0.6.0 — 2026-09-08

- `roth compare` branches organizer scenarios from verified stable, team, and
  review reports, preserving the baseline and frozen preferences.
- Capacity/proposer changes, team size/weight changes and project closures,
  and per-reviewer workload/per-submission coverage overrides.
- Static reports and CSVs show assignment churn, original ranks, teammate
  changes, and individual outcomes on a fixed baseline scoring scale. Review
  workload changes and ordinal set comparisons avoid invented welfare claims.
- Independent result verification, per-scenario infeasibility and solver-limit
  handling, hashed artifacts, agent guidance, and a synthetic worked example.
- Team markets support closed projects without deleting or reranking options;
  stable report exports now include the complete hashed preference snapshot.

## 0.5.0 — 2026-09-07

- Native Humanize collection for teams and reviews: batched option assessment,
  cross-batch ranking, and review expertise ratings.
- Private contact maps, respondent/package bindings, append-only response history,
  explicit revisions, stale-ranking protection, and source-preserving exports.
- `agent next --collection human` intake through exported preferences and solving,
  with contact/market revision checks and missing-response guidance.
- An offline synthetic pilot exercising native EDSL round trips for all 84 survey
  packages and both solvers. Hosted recruitment still awaits a real cohort pilot.

## 0.4.0 — 2026-09-07

- Peer-review assignment with exact submission coverage, reviewer workload bounds,
  authorship/team exclusions, explicit conflicts, and individual unacceptable options.
- Borda rankings, explicit 0–100 scores, or constraints-only allocation using
  optional SciPy/HiGHS; independent assignment and score verification.
- File-based `roth reviews` commands, a 12-student classroom example, frozen inputs,
  workload/coverage reports, and ranking/assignment matrices.
- `agent next --scenario reviews` intake, feasibility guidance, and saved-result
  verification; exhaustive small-instance and solver-limit regression tests.

This is additive score optimization. Review-specific Humanize collection and
native delegated scoring are not implemented.

## 0.3.0 — 2026-09-07

- Many-to-one deferred acceptance with capacities on either side and either
  proposing orientation, with independent quota and blocking-pair verification.
- Frozen capacities, vacancy and load statistics, complete multi-partner exports,
  and static organizer ranking/match matrices.
- A synthetic 30-employee / 10-mentor example, shared human/delegated collection,
  CSV capacity imports, and many-to-one `agent next` routing.
- Exhaustive small-market oracle checks and complete CLI/report regression tests.

Capacities are upper bounds and preferences rank individuals independently.
Many-to-many matching, minimum fill requirements, and group-dependent preferences
remain unsupported.

## 0.2.0 — 2026-09-07

- Read-only `roth agent next` intake and workflow guidance, with structural
  scenario routing, missing-input questions, explicit command metadata,
  confirmation/coverage checks, and verified team-report continuation.

- Joint team formation and project assignment with an optional SciPy/HiGHS MILP
  solver, directional Borda rankings, explicit exclusions, and organizer-set
  target sizes and smaller/larger permissions.
- Lexicographic team-size and preference objectives, independent feasibility
  and score verification, and explicit incumbent/optimality reporting.
- A separate file-based `roth teams` CLI, frozen original and normalized inputs,
  static reports with ranking matrices, and a fictional classroom example.
- Exhaustive small-market comparisons and infeasibility/solver-limit tests.

This mode is aggregate score optimization, not a stable or strategy-proof
matching mechanism. Team-specific Humanize surveys and repeated projects are
not yet implemented. The one-to-one workflow remains unchanged.

## 0.1.0 — 2026-09-07

Initial local implementation of Roth:

- Deterministic one-to-one deferred acceptance, independent stability verification,
  proposer comparison, immutable snapshots, and preference/outcome statistics.
- JSON/CSV/EDSL AgentList market imports, explicit eligibility edges, respondent
  revisions, incomplete-cohort closure, and append-only project history.
- Personalized ranking, batched screening, preference-instruction, confirmation,
  and pairwise benchmark survey packages; native Humanize and email handoffs.
- Organizer-controlled delegation, bidirectional lexical retrieval, explicit
  evaluation budgets, model-parameter-aware caching, retries, and expansion.
- Calibration-only prompt evidence, frozen held-out predictions, benchmark reports,
  optional accuracy gates, and enforcement of explicit human pairwise choices.
- Fictional students/internships demonstrations, a 200-by-150 scale example,
  organizer HTML/CSV/JSON reports, and private individual result summaries.

The CLI and native EDSL artifacts/Results are tested offline against the pinned
EDSL revision. Hosted Humanize presentation, email delivery, and actual LLM
preference quality have not been tested live. Many-to-one matching, semantic
retrieval, natural-language hard-filter compilation, and automated fielding or
expansion scheduling remain outside this release.
