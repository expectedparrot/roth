# Changelog

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
