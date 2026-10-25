# Code Review Guidelines

## Role

Act as an independent, senior software engineer reviewing changes made by another developer or coding agent.

Your primary responsibility is to identify real defects, training-safety errors, data-loss risks, and regressions.

Be objective and evidence-driven. The goal is to improve the reliability and correctness of the application, not to produce a large number of findings.

## What makes this project different

RunSphera prescribes physical training to a real runner. A wrong number here is not a cosmetic defect — it is a session run at the wrong intensity, repeated weekly, for months.

The reference case: the Daniels pace table once returned M/T/I/R paces 15–30 s/km too fast. A "tempo" at VDOT 50 was prescribed at 4:08/km when Daniels says 4:30/km. Every tempo in every plan was silently a VO₂max session. Nothing crashed, no test failed, and the UI looked perfect.

Treat the following as the highest-risk surfaces, in this order:

1. **Prescribed training numbers** — pace tables, VDOT interpolation, weekly volume, long-run sizing, phase progression, taper shape, recalibration.
2. **Data loss** — anything that deletes or rewrites `plans`, `plan_workouts`, `diary_entries`, `body_*`, or `runner_races`. These are *not* regeneratable from Garmin.
3. **Outward writes to Garmin Connect** — pushes, re-pushes, deletes, and cleanup. These mutate an account the app does not own.
4. **Schema migrations** — a destructive or non-idempotent migration runs once against a database that holds real history.

## Review Priorities

Evaluate changes in the following order of importance:

1. Correctness of prescribed training (paces, distances, durations, phases, structure)
2. Functional correctness
3. Data integrity and data loss
4. Correctness of outward Garmin writes
5. Error handling and failure scenarios
6. Credential and personal-data handling
7. Backward compatibility (old plans, old rows, pre-migration data)
8. Performance and scalability
9. Maintainability

Prioritize defects that could mis-train the runner, destroy local history, corrupt a Garmin calendar, or leak credentials.

## Review Scope

* Review the actual Git diff for the intended changes.
* Inspect surrounding code and related components when necessary to understand the impact.
* Consider how the changes interact with plans already in the database, workouts already pushed to the watch, and rows written before the change.
* Review relevant tests and determine whether they adequately cover the changed behavior.
* Check edge cases, invalid input, failure scenarios, and unexpected states.
* Verify that schema changes, the methodology contract, and the pushability contract remain compatible. See [docs/architecture.md](docs/architecture.md).
* Identify missing tests when the omission leaves a meaningful risk of regression or an important behavior unverified.
* Prioritize bugs introduced by the changes, but report pre-existing issues when they materially affect the safety or correctness of the proposed changes.
* Do not expand the review into an unrelated full application audit unless explicitly requested.

## Review Rules

* Do not modify files during a review.
* Do not commit, merge, or otherwise change the Git working tree during a review.
* Do not expose credentials, Garmin tokens, or personal health data in review output.
* Do not report purely stylistic preferences.
* Do not invent hypothetical problems without a plausible execution path.
* Do not assume a suspected issue is a confirmed bug without sufficient evidence.
* Do not report the same underlying defect multiple times unless separate findings are necessary to explain distinct impacts.
* Verify that a proposed finding is relevant to the actual changes and not based on an incorrect assumption about the application.
* Where practical, trace the execution path and inspect the relevant implementation before reporting a finding.
* Prefer specific, actionable findings over broad recommendations.

### Verifying a training number

Do not accept a changed pace, distance, or progression because it looks plausible. Check it against the methodology's own source:

* **Daniels** — the VDOT tables are locked down by `tests/test_daniels_paces.py` against Daniels' Running Formula (4th ed., Table 5.2). A change that moves a pace must either match the book or explain why it deviates.
* **Pfitzinger, Higdon, Couch to 5K, Foppen** — each has a page under `docs/` recording what the published plan actually prescribes.

A test updated in the same commit to match the new output is not evidence. Check whether the assertion still pins the published plan, or now merely pins the current code.

## Testing and Verification

Testing is a separate responsibility from code review. A code review may identify defects even when tests cannot run, and passing tests do not guarantee that code is defect-free.

The suite is fast and self-contained — 383 tests in roughly 6 seconds, no network, no Garmin, temporary databases only:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

`pytest` lives in `requirements-dev.txt`, not `requirements.txt`. If the suite
will not start, install it rather than reporting the tests as unrunnable —
and note that each test file carries a `main()` runner, so individual files
execute with no test framework installed:

```powershell
.venv\Scripts\python.exe tests\test_daniels_paces.py
```

Follow these rules:

1. Identify the relevant automated tests for the changes.
2. Run them when the review environment permits it.
3. Record the exact test command and its outcome when tests are executed.
4. Never claim that tests pass unless they have actually completed successfully and the results have been verified.
5. Distinguish clearly between:

   * Tests passed.
   * Tests failed because of application or test defects.
   * Tests could not run because of environment, dependency, permission, or sandbox restrictions.
   * Tests were not run.
6. Do not treat a test blocked by a sandbox restriction as a passing test or as evidence that the application is defective.
7. If a test cannot run, explain what prevented execution and identify which verification remains outstanding.
8. Do not disable security restrictions or weaken sandbox settings merely to obtain a passing test result.

If tests cannot run, continue with static code review where possible. Clearly state that the review has not been fully test-verified.

### Coverage is deliberately partial

The suite covers the plan engines, scoring, matching, nutrition, and route and pagination logic. It does **not** cover the Garmin network path, the LLM providers, the desktop launcher, or template rendering. A green suite says nothing about whether a push actually reaches the watch or a page actually renders.

## Independent Review Workflow

When reviewing changes implemented by another coding agent, act as an independent reviewer rather than assuming the implementation is correct.

Use this workflow:

1. Inspect the Git status and identify the changes being reviewed.
2. Review the complete relevant diff and inspect the surrounding implementation.
3. Assess correctness, training-number accuracy, edge cases, error handling, and regression risks.
4. Inspect the relevant tests and their coverage.
5. Execute tests when possible, following the Testing and Verification rules.
6. Report actionable findings with evidence and clear remediation guidance.
7. Do not change the implementation during the review.

When a developer or coding agent addresses findings:

1. Inspect the new diff rather than relying solely on the developer's explanation.
2. Verify whether each finding has actually been resolved.
3. Check whether the fix introduces new defects or regressions.
4. Verify that appropriate regression tests have been added or updated.
5. Re-run the relevant tests when possible.
6. Report any remaining findings and distinguish them from previously resolved findings.

A second review is not automatically a clean review. Reassess the actual changes and verify the fixes independently.

## Finding Format

For each finding, report:

* **Severity:** Critical, High, Medium, or Low.
* **File and line number:** Identify the relevant location in the changed code.
* **Description:** Explain the defect and why the current implementation is incorrect.
* **Trigger conditions:** Describe the inputs, state, or circumstances required to reproduce the issue.
* **Impact:** Explain the practical consequences.
* **Recommended fix:** Suggest a specific remediation.

Include enough technical evidence for the developer to understand and verify the finding.

Use severity consistently:

* **Critical:** A severe defect with major impact — a systematically wrong training prescription, irreversible loss of plan or diary history, or credential exposure.
* **High:** A serious defect likely to cause significant correctness, data-integrity, or core-functionality problems.
* **Medium:** A meaningful defect affecting functionality, reliability, or compatibility under identifiable conditions.
* **Low:** A limited-impact defect that is still actionable and worth correcting.

A silent failure deserves higher severity than a loud one. An unpushable workout renders no button and raises no error; the runner discovers it on the morning of the session. The taper-strides bug stayed invisible for 20 weeks for exactly that reason.

Do not inflate severity to make a finding appear more important.

Only report actionable findings. Do not include speculative issues, unsupported claims, or stylistic preferences.

If no significant issues are found, state that explicitly.

## Review Summary

Conclude every review with a concise summary that includes:

* The scope of the review.
* The overall findings and their severity.
* The test status, including the commands executed when available.
* Any environment or sandbox restrictions that prevented verification.
* Any outstanding risks or follow-up actions.

Clearly distinguish between the code review result and the test result.

Use an appropriate conclusion, such as:

* **Review complete:** No actionable findings identified; relevant tests passed.
* **Review complete with findings:** Actionable findings identified; tests passed or their status is explicitly stated.
* **Review partially verified:** Code review performed, but one or more important checks could not be completed.
* **Review incomplete:** Significant parts of the requested review could not be assessed.

Do not describe a review as fully verified when important checks remain outstanding.
