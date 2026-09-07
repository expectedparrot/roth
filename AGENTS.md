# Working on Roth

Roth is an agent-friendly CLI for one-to-one matching. Many-to-one is deferred.
Use `roth guide`, `roth next`, and `roth capabilities` to discover the workflow.
Keep the core matching engine independent of EDSL and network access.

Development checks:

```bash
python -m compileall -q src
python -m pytest -q
python -m build --no-isolation
```

Keep CLI parsing in `cli.py` and domain behavior in its owning module. Preserve
one JSON envelope per command and structured nonzero failures. Do not silently
replace preference history, snapshots, model scores, or respondent identities.
Keep unknown, rejected, and nonresponding states distinct. Human pairwise answers
used for calibration must remain separate from held-out benchmark answers.

External execution uses EDSL handoff artifacts and explicit `ep` commands.
Building and testing does not authorize paid model calls or real invitations.
The synthetic internship fixtures must stay visibly labeled as synthetic.
