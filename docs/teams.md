# Joint team formation and project assignment

Roth 0.2 adds a separate `roth teams` workflow. Students rank projects and
potential teammates. A mixed-integer linear program chooses team membership
and projects together. Each student receives one assignment; each used project
hosts one team. Repeated projects are not implemented. Humanize preference surveys are available
through `teams field`; see the [collection workflow](collection.md).

The [worked classroom report](teams-example/index.html) shows every input list,
the actual assignments, a project ranking matrix, and a directional teammate
ranking matrix. All example preferences are fictional and hand-built.

## Run the example

From a source checkout:

```bash
python -m pip install -e '.[teams]'
roth teams example classroom
roth teams validate classroom/market.json --preferences classroom/preferences.json
roth teams solve classroom/market.json --preferences classroom/preferences.json \
  --output classroom/report --time-limit 60
```

The first command creates the market and preference files; it does not solve
the assignment. Inspect or edit those files before `solve`. `validate` checks
the schema and prints the derived Borda scores; it does not establish feasibility.
`solve` reads the files, validates every student submission, freezes the inputs
into a new report directory, and exports assignments and solver diagnostics.

This mode is file-based and does not use the one-to-one `.roth` store or the
global `--project` option. It requires only the optional `teams` extra
(SciPy with its bundled HiGHS solver); the existing matching core remains
dependency-free. No model calls, account, or email invitations are involved.

## Inputs

The market file contains `students` and `projects`, each a nonempty array of
objects with distinct `id` and `name` fields. It also contains organizer settings:

```json
{
  "target_size": 3,
  "allow_smaller": true,
  "allow_larger": true,
  "min_size": 2,
  "max_size": 4,
  "social_weight": 0.5
}
```

Place these settings under `config` in `market.json`. Target size defaults to 3.
If smaller or larger teams are allowed and no corresponding bound is supplied,
the bound defaults to one below or above the target. Teams contain at least two
students. If both flags are false, all teams must have exactly the target size.
Bounds outside the permissions are rejected. There is no fixed number of teams:
the solver chooses which projects to use subject to these rules.

The preference file is an array with exactly one completed record per student:

```json
{
  "student_id": "s01",
  "projects": ["climate", "housing", "transit"],
  "teammates": ["s02", "s03", "s05"],
  "unacceptable_projects": ["library"],
  "incompatible_teammates": ["s12"],
  "complete": true,
  "source": "synthetic"
}
```

Use `source: "human"` for real submissions. Both rankings are strict ordered
lists, best first, and may be partial or empty. A completed empty list is a
submission with no ranked options. A missing or unfinished submission blocks
solving. Duplicate IDs, self-ranking, unknown options, and ranking an option
while excluding it in the same record are rejected.

Unlisted options earn zero points and remain recorded as **unranked**. They are
available for assignment unless explicitly excluded. This is a scoring policy,
not a claim that the student evaluated or rejected every omitted option.

An incompatibility listed by either student prevents that pair from sharing any
project, regardless of the other student's preference. These fields represent
organizer-approved hard exclusions. If exclusions conflict with assignment or
size requirements, the solver reports infeasibility and never relaxes them.

## Borda scoring

With M total options, a listed option at rank r receives M − r points. The
bottom of a complete list earns zero. If there is only one option, ranking it
earns one point. M counts all projects or all other students, not just the
submitted list, and does not shrink when the student excludes options.

For the classroom example there are five projects: ranks 1, 2, and 3 earn
4, 3, and 2. There are eleven possible teammates: ranks 1, 2, and 3 earn
10, 9, and 8. Unlisted options earn zero in either category.

To give the organizer's weight a useful scale, Roth divides project points by
max(1, number of projects − 1), and the sum of teammate points by
max(1, number of students − 2) × (target size − 1).

For student i assigned to project p with team T, the score is:

\[
V_i=(1-\lambda)\frac{u_{ip}}{\max(1,|P|-1)}
+\lambda\frac{\sum_{j\in T\setminus\{i\}}s_{ij}}
{\max(1,|S|-2)(t-1)}.
\]

Here u and s are raw Borda points, t is the target size, and lambda is
`social_weight`. Zero weights only projects; one weights only teammates.
Teammate preferences remain directional; the aggregate objective includes
both students' points. The social divisor uses target size, not realized size.
Thus an extra desired teammate adds value and can take the normalized social
score above one in a larger team. These scores are neither a money budget nor
measured interpersonal utility.

## Integer-program formulation

Because each project hosts at most one team, project IDs serve as team labels.
Let binary x_ip indicate student i joins project p, and binary a_p indicate
that project p is used. With lower/upper sizes L and U:

\[
\sum_p x_{ip}=1,\qquad
La_p\leq\sum_i x_{ip}\leq Ua_p.
\]

Project exclusions fix x_ip to zero. An incompatible pair has
x_ip + x_jp <= 1 for every project.

For each scored pair i < j, auxiliary z_ijp represents x_ip × x_jp:

\[
0\leq z_{ijp}\leq1,\quad
z_{ijp}\leq x_{ip},\quad z_{ijp}\leq x_{jp},\quad
z_{ijp}\geq x_{ip}+x_{jp}-1.
\]

These constraints force the product exactly when x is binary, so z can be
continuous. Pairs with zero objective coefficient need no auxiliary variable.
The project term is already linear in x. The social term weights z by the
sum of the two directional Borda scores, with the divisors above.

Nonnegative d_p measures absolute team-size deviation:

\[
d_p\geq\sum_i x_{ip}-ta_p,\qquad
d_p\geq ta_p-\sum_i x_{ip}.
\]

Roth first minimizes sum(d_p). If that stage proves optimal, Roth constrains
the deviation to that minimum and maximizes sum(V_i). This is a lexicographic
objective: a preference gain never justifies extra size deviation. Both stages
optimize over the joint assignment; there is no clustering stage followed by
a separate project assignment.

See the [SciPy MILP documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
for the solver interface and termination statuses.

## Results and limitations

The output directory preserves the original submitted files, normalized market
and preference snapshots, an input hash, Borda scores, `result.json`, an
assignment CSV, and the static HTML report. Existing output directories cannot
be overwritten. Rerun into a new directory after editing preferences or rules.

`solution_status: "optimal"` means both stages proved optimal within solver
numerical tolerances. A time-limited run with a feasible incumbent is exported
as `feasible_limit`, with each phase's status, objective, bound, and relative
gap. If there is no feasible incumbent, the command returns a structured error.
If the size stage times out, the preference stage is not run; if the preference
stage finds no incumbent before its limit, the valid size-stage assignment is
retained and clearly labeled as not proven optimal overall.

Assignments and scores are checked independently of the solver's auxiliary
variables. Tied optima can produce different memberships across solver versions.
The report counts project first choices, top-three assignments, unranked project
assignments, receipt of ranked teammates, and individual scores. It exposes
directional preference matrices rather than hiding the underlying lists.

This is aggregate preference-score optimization. It does not guarantee
strategy-proofness, coalition stability, or individual minimum satisfaction.
The report can expose a student receiving an unranked project in exchange for
the objective's social gains; the organizer should inspect such outcomes.
Skill coverage, fairness constraints, team-specific fielding, and repeated
projects are possible extensions, not features of this release.
