# Async tool-hook review coverage

Status: locally verified; awaiting upstream CI and review. Follow-up to
`db937ea16aadbed1c076f6922b5975fd97613d81`
for [Agno PR #9163](https://github.com/agno-agi/agno/pull/9163).

## Failure and contract

The reviewer reproduced the original bug and confirmed the fix, but requested
coverage beyond one sync hook wrapping one async tool. The existing test file
passes all 55 cases on the PR head. Before the fix, a hook returning its
continuation can leave a coroutine in a successful execution result without
running the tool, including tools that would raise. The defect is in Agno's
nested async execution chain, not application code. Source history traces the
direct hook-return pattern to `8d71248f5a` (Add execution hooks for agents and
teams, #2920); the immediate parent `a1aad6e5a` is the unfixed control. No
additional runtime change is needed.

Invariant: each hook's returned continuation resolves within
`FunctionCall.aexecute()` before success is reported; tool exceptions reach the
existing failure result. Non-awaitable values retain their type and identity.
The FunctionCall owns each invocation; hooks run in declared order, with one
tool invocation per completed continuation. Reusing the same call must execute
fresh continuations. Async generators remain lazy and iterable.

## Scope and verification

Add tests beside the existing regression in
`libs/agno/tests/unit/tools/test_functions.py`:

| Sequence | Observable proof |
| --- | --- |
| Sync tool, sync or async hook, same call twice | Correct fresh result and hook/tool counts |
| Sync/async tool with `[async, sync]`, `[sync, async]`, `[sync, sync, sync]` | Ordered hook effects, resolved value, exactly one tool call |
| Async generator behind sync hook | Async-generator type, lazy execution, yielded values |
| Raising sync/async tool behind sync hook | Failure status and original error message |
| Async hook returning an unawaited continuation | Concrete result and tool effect |
| Sync hook returning a dict | Same dict object, no tool invocation |

Run the expanded file on the fixed candidate and on the parent implementation
in an isolated control. Run affected function/decorator suites and repository
format/validation scripts. Record baseline or environment failures separately.
Review the cumulative diff, commit this plan with the tests, and update the PR
description to include sync tools with async hooks and swallowed errors.

This is deterministic tool-dispatch coverage: no production model-call graph,
provider/model configuration, persistence, approval, or external tool effects
change. Live model evaluation is unnecessary for these return-value contracts.
Keeping the existing source fix is the smallest solution; retracting it restores
the defect, while application wrappers cannot repair a framework-level contract
for all callers. Upstream acceptance of #9163 is the removal path for the fork's
equivalent patch.

## Evidence

- Initial candidate: `db937ea16aadbed1c076f6922b5975fd97613d81`.
- Initial environment: Python 3.12.13, pytest 9.0.3, pytest-asyncio 1.4.0,
  Pydantic 2.11.7; source selected explicitly with `PYTHONPATH=libs/agno`.
- Baseline command: `python -m pytest libs/agno/tests/unit/tools/test_functions.py -q --tb=short`.
- Baseline result: 55 passed in 3.55 seconds.
- Final clean environment: Python 3.12.13, pytest 9.1.1, pytest-asyncio 1.4.0,
  Ruff 0.15.20, mypy 2.1.0, Pydantic 2.13.5. Installed the checkout's
  `libs/agnoctl` and `libs/agno[dev]` in an isolated `.venv`.
- Added 15 parameterized cases across the six requested groups. The final
  function test file contains 70 cases. Mixed stacks also reuse the same call
  twice and check ordered hook/tool effects after each execution.
- Final affected-suite command:
  `python -m pytest libs/agno/tests/unit/tools/test_functions.py libs/agno/tests/unit/tools/test_decorator.py libs/agno/tests/unit/tools/test_toolkit.py -q -o log_cli=false --tb=short -W error::RuntimeWarning`.
  Result: 138 passed in 3.25 seconds, without warnings.
- Differential control: copied the final test file into an isolated checkout
  of `a1aad6e5a`, using the same clean environment and
  `PYTHONPATH=libs/agno`. Result: 13 failed, 57 passed in 3.12 seconds. Failures
  include the original regression and 12 added cases. The awaited async-hook
  case and both dict short-circuit cases remain passing compatibility controls.
  Failures show unresolved coroutines, non-iterable generator results, and
  erroneous success for raising tools.
- `./scripts/format.sh`: passed with no formatting changes.
- `./scripts/validate.sh`: passed; Ruff checks, mypy on 946 Agno and 21 agnoctl
  source files, and cookbook pattern checks all passed.
- `git diff --check`: passed. Reviewed the complete PR diff; the original
  runtime patch remains sufficient and unchanged.
- Earlier checks missed neighboring compositions because only one sync hook
  around one async tool was covered. This revision adds direct public-boundary
  evidence for all requested shapes without mocks or private helper calls.
- No failed CI runs in this repair before delivery. One dependency-install
  attempt hit sandbox DNS restrictions; the isolated install succeeded with
  authorized network access. No code or dependency pins were changed for it.
- Acceptance: all requested return values, effects, iteration, and error
  assertions must pass; an execution status alone cannot satisfy the tests.
- Remaining gates: candidate CI and maintainer approval. No merge is part of
  this correction. Archive this plan after upstream acceptance, recording the
  implementing source and coverage commits.

## Agent-system review conclusion

- Scope: cumulative async hook-result fix and reviewer-requested regressions.
- Department: deterministic agent harness/tool execution.
- Model-call graph, providers, ownership, and persistent state: unchanged.
- Applicable doctrine: PASS for deterministic mechanics, owner-visible error
  evidence, general invariant coverage, and behavioral verification (principles
  6, 7, 9, 14); the other 14 principles have no changed surface in this revision.
- Anti-slop: not applicable; no semantic rules or model judgment changed.
- Findings and waivers: none outstanding locally; no additional fork machinery.
- Reality proof: real FunctionCall dispatch and generator consumption are
  exercised directly. Model-backed application runs are outside this stateless
  framework test correction.
- Verdict: local correction verified; upstream acceptance awaits CI and review.
