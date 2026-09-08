# Many-to-one matching

Use this mode for employees and mentors, students and advisers, or applicants and
programs. One side receives at most one partner per person. Participants on the
other side may accept several partners, each under a fixed upper capacity.

## Try the mentorship example

From a local checkout, install with `python -m pip install -e .`. The matching
engine needs no optional dependencies, solver, or network.

```bash
roth example mentorship mentorship-demo
roth --project mentorship-demo agent next
roth --project mentorship-demo preferences import mentorship-demo/preferences.json
roth --project mentorship-demo preferences freeze --name main
roth --project mentorship-demo match --snapshot main --name main
roth --project mentorship-demo validate
roth --project mentorship-demo report --run main --output mentorship-demo/report
```

This creates 30 fictional employees and 10 fictional mentors with capacity three.
`example mentorship` writes explicit synthetic inputs and initializes a study;
it does not import rankings, solve, send surveys, or generate model preferences.
The seeded rankings favor shared topics and use shuffled orders within those
categories. All candidates are acceptable in this particular example. Change
sizes with `--employees`, `--mentors`, and `--capacity`.

[Inspect the submitted market](../examples/mentorship/market.json),
[the preference records](../examples/mentorship/preferences.json), and
[the worked report](mentorship-example/index.html). The default fixture fills all
30 slots; changing capacities or acceptable lists can leave vacancies or people
unmatched.

## Define real inputs

Use the existing [market and preference contracts](contracts.md). Each mentor
has one ID and one ranking, even with several slots. For example:

```json
{
  "id": "m001",
  "side": "right",
  "name": "Mentor Alex",
  "capacity": 3,
  "profile": {"topic": "Data science"}
}
```

Capacity defaults to one. It must be a nonnegative integer; zero closes a
position. Only one side can contain participants with capacity above one.
Capacities may instead be on the left; the labels do not determine the algorithm.
They are frozen with the market and cannot be silently changed in old snapshots.
Use a separate study for a revised roster or capacity scenario.

A mentor ranks **all acceptable individuals**, not just their top three. An
acceptable fourth choice can fill a vacancy if earlier choices go elsewhere.
The existing unknown/unacceptable distinction applies: unknown edges remain
recorded but are unavailable under the default restricted matching policy.

The organizer sets which side proposes before collecting preferences. By default,
the left side proposes, and Roth also computes the opposite orientation for
comparison. Use `match --proposing-side right` for an explicit alternative run.

## What preferences mean

Preferences are **responsive**: a mentor prefers a higher-ranked individual to a
lower-ranked individual regardless of the other mentees assigned, and prefers
any acceptable individual to leaving a slot empty. This makes a single ranked
list sufficient. It does not encode “take these two together,” “at least two or
none,” or “exactly one person with each skill.” Such requirements need another
formulation.

With employee proposals, a mentor tentatively retains their best acceptable
applicants up to capacity. A better new applicant can displace the lowest-ranked
incumbent, who then continues down their own list. This is the same vacancy and
replacement logic illustrated by [NRMP's algorithm explanation](https://www.nrmp.org/intro-to-the-match/how-matching-algorithm-works/).
Roth's implementation also permits the capacity side to propose until its slots
are filled or its list is exhausted.

A blocking pair consists of an acceptable employee and mentor who are not
matched to each other, where the employee would prefer that mentor and the mentor
has a vacancy or would prefer that employee to an incumbent. The independent
verifier checks this condition, quotas, duplicate pairs, and mutual acceptability.
Stability is relative to the frozen rankings and eligible candidate graph;
restricted shortlists do not establish full-market stability.

## Collect preferences

Direct ranking, batched screening, delegated scoring, confirmation, and A/B
benchmarking use the same commands as one-to-one matching. Mentor survey text
explains capacity, independent rankings, and leaving additional slots empty.
The existing `Remain unmatched` marker is the acceptability cutoff for each slot.

The default example's mentors each have 30 candidates, above the default ranking
budget of 15. For real human collection, `agent next --collection human` routes
long lists to screening; then collect one ranking across the retained candidates.
Screening can reveal acceptability without shortening a list: if too many remain,
explicitly raise `--max-options` or choose a shortlist with disclosed coverage.
Do not truncate rankings to capacity.

Delegated scoring evaluates individual candidates independently. Organizer
permission, confirmation policies, and benchmark gates still apply. A capacity
increase does not itself expand a shortlist: review candidate coverage and
vacancies, and explicitly expand a scoring plan if needed.

## Python API

```python
from roth import deferred_acceptance, verify_matching

employees = {"a": ["x"], "b": ["x"], "c": ["x"]}
mentors = {"x": ["c", "b", "a"]}
capacities = {"x": 2}  # omitted participant capacities default to one

result = deferred_acceptance(employees, mentors, capacities=capacities)
assert result["matches"] == [["b", "x"], ["c", "x"]]
assert result["vacancies"]["a"] == 1
assert verify_matching(
    employees, mentors, result["matches"], capacities=capacities
)["stable"]
```

Existing calls without `capacities` retain one-to-one behavior. Both functions
accept the same flat ID-to-capacity map, and reject unknown IDs or many-to-many
capacities.

## Read the results

The HTML organizer report shows every match, capacities and vacancies, and a
matrix of both sides' ranks with realized matches highlighted. For markets above
2,500 cells, use the complete JSON and CSV exports instead of an oversized matrix.

`unmatched` lists participants with no assignment. A mentor with one of three
slots filled is matched and has two vacancies. Participant match rates and slot
fill rates therefore have different denominators. Assigned rank lists retain
all partners; averages count each assignment, while top-1/top-3 assignment rates
count participants with at least one qualifying partner.

Individual JSON exports use a `partners` list of assigned public profiles. For
unit-capacity participants the legacy scalar `partner` field is also retained.
No rankings, contact details, or private instructions are included in these
individual files. The organizer report contains private rankings.
