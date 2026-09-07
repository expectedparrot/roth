# Delegated matching and preference benchmarking

The organizer controls delegation for the market, optionally with a per-side
override. Participants provide preference descriptions and follow the configured
confirmation and benchmark workflow.

## Prepare a market

```bash
roth example create delegated-demo
```

The fictional example already contains natural-language instructions and enables
delegation. For real participants, configure delegation in market JSON or through
`roth configure`, then collect instructions:

```bash
roth --project study field build --kind instructions \
  --name instructions --output study/instructions
# Field externally with Humanize, then import the returned answers.
```

Import all instruction responses before building dependent scoring or benchmark
plans. Candidate profiles describe what a person or opening offers; private
instructions describe what they want.

## Retrieve and score

```bash
roth --project delegated-demo score plan --name baseline \
  --model YOUR_MODEL --k 4 --budget 200 --output delegated-demo/baseline
```

Each participant's instructions query a lexical profile index. The planner takes
the union of both sides' retrieved edges and requests both directional evaluations
for every retained edge. `--audit N` adds random omitted candidates per participant.
When a side uses direct human rankings, Roth skips LLM evaluations on that side;
the corresponding human preferences are collected separately before matching.
The declared budget bounds total directed evaluations, including cached work;
reported pending evaluations identify new work. Lexical retrieval is a baseline,
not semantic understanding, and the implementation does not claim subquadratic
end-to-end runtime: eligibility and complete-market diagnostics can be quadratic.

Inspect `plan.json`, prompts, `edsl/jobs.ep`, and `handoff.json`. Externally estimate
cost and run the selected model using the generated commands. No model is selected
or executed implicitly by Roth. Import EDSL Results:

```bash
roth --project delegated-demo score import delegated-demo/results.ep \
  --name baseline --edsl
roth --project delegated-demo score status --name baseline
```

`score retry --name baseline --output RETRY_DIRECTORY` builds only missing tasks.
Imports preserve raw Results records and validate task IDs, model name, finite
scores, acceptability, and explanations. Equal scores use a saved seed and candidate
hash to form a reproducible strict order. Explicit generation settings can be supplied
with `score plan --parameters parameters.json`; they participate in cache keys and
are checked against native Results. The handoff builds a ModelList with those settings.
The initial cost estimate uses the model defaults, so review output-token settings
when estimating a parameterized run. Scores are compared only within a person.

For an entirely offline demonstration, substitute explicit fixtures for inference:

```bash
roth --project delegated-demo example scores --name baseline \
  --output delegated-demo/baseline-scores.json
roth --project delegated-demo score import delegated-demo/baseline-scores.json \
  --name baseline --source synthetic
```

These fixture answers come from the canned rankings; they are not model predictions.

## Optional calibration and held-out benchmark

```bash
roth --project delegated-demo benchmark build --name check \
  --scores baseline --pairs 6 --output delegated-demo/check
```

This saves baseline predictions and builds separate calibration and evaluation
survey packages. Each pair displays real candidates, randomly assigned to A/B,
with preference strength, separate acceptability questions, and an explanation.
Pairs mix representative selections with small score gaps. Synthetic example
answers can exercise either stage without fielding:

```bash
roth --project delegated-demo example benchmark --name check --split calibration \
  --output delegated-demo/calibration-answers.json
roth --project delegated-demo benchmark import delegated-demo/calibration-answers.json \
  --name check --source synthetic
```

Use only calibration responses to prepare revised scoring instructions:

```bash
roth --project delegated-demo score plan --name revised --model YOUR_MODEL \
  --k 4 --budget 200 --expand baseline --calibration check \
  --output delegated-demo/revised
```

Roth attaches calibration choices and explanations to the participant's scoring
prompt; it does not train model weights. Calibration evidence participates in the
cache key. After externally executing and importing revised scores (or generating
and importing revised synthetic score fixtures), freeze their predictions:

```bash
roth --project delegated-demo benchmark predict --name check \
  --scores revised --label revised
```

Only then collect and import held-out answers. For the offline example:

```bash
roth --project delegated-demo example benchmark --name check --split evaluation \
  --output delegated-demo/evaluation-answers.json
roth --project delegated-demo benchmark import delegated-demo/evaluation-answers.json \
  --name check --source synthetic
roth --project delegated-demo benchmark report --name check
```

For real fielding, `benchmark import RESULTS.ep --name check --edsl` verifies the
participant/package identities and maps the native question answers.

New predictions are rejected once any held-out answers have arrived. To evaluate
another revision after that point, create a new benchmark. `benchmark retire`
marks the old evidence as ineligible for a current accuracy gate; its explicit
human choices still constrain inferred rankings. Calibration extraction never
includes held-out answers, even from retired benchmarks.

The report gives baseline and revised held-out directional agreement, response
counts, ties, insufficient-information responses, and acceptability errors per
participant. Accuracy is limited to sampled pairs in the retrieved pool. A small
survey is evidence about preference modeling, not certification of full-market
stability or successful candidate discovery. Synthetic fixtures will often agree
perfectly by construction and provide no evidence of LLM quality.

## Apply, confirm, and match

```bash
roth --project delegated-demo score apply --name revised
```

Application requires complete scores, preserves existing human rankings, honors
explicit pairwise rejections, and constrains inferred order with human comparisons.
Conflicting acceptability judgments or pairwise cycles require clarification;
provide an explicit human ranking to resolve them. Original evidence is retained.
If pairwise answers arrive after score application, reapply scores before freezing
so the new explicit choices are incorporated. Benchmark accuracy describes the
frozen model predictions, not the rankings subsequently constrained by those answers.

If the organizer requires confirmation, build a confirmation survey for the
relevant participant IDs and ingest the answers. A confirmation is bound to the
exact ranking version; a later change requires a fresh confirmation. A request
for revision does not count as confirmation.

```bash
roth --project delegated-demo field build --kind confirmation \
  --name confirm --participant s001 --output delegated-demo/confirm
```

The canned fixture path has source `synthetic`, so it is not presented as a real
participant's delegated or confirmed decision. Confirmation surveys apply to
actual delegated preference records.

```bash
roth --project delegated-demo preferences freeze --name inferred
roth --project delegated-demo match --snapshot inferred --name inferred
roth --project delegated-demo report --run inferred --output delegated-demo/report
```

Expand a shortlist using `score plan --expand revised --k LARGER`, optionally adding
an omitted-candidate audit. Import new scores, explicitly revise preferences with
`score apply --replace`, freeze a new snapshot, and rerun matching. Cached work is
reused when instructions, candidate profile, model, rubric, and calibration agree.
The final certificate covers the frozen evaluated graph, not unsampled edges.
