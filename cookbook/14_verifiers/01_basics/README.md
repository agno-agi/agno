# 01_basics

The verification loop on a single agent: callable checks, outcomes, streaming and per-check policy.

## Files

- `verify_done.py`: A callable verifier as the definition of done; the evidence report drives a second attempt.
- `unverified.py`: A run whose checks never pass ends `RunStatus.unverified` and persists the record.
- `print_unverified.py`: `print_response` on an unverified run, then the status and stop reason read off `get_last_run_output()`.
- `streamed.py`: `VerificationStarted` and `VerificationCompleted` events on a streamed run.
- `async_verify.py`: `agent.arun` with a coroutine check awaited in place.
- `check_policy.py`: Per-check policy: `required=False` for an advisory check, `run_condition` to gate a judge.
- `flaky_check.py`: `check(fn, max_retries=2)` retries a flaky probe without spending a model attempt.
- `stop_on_failure_check.py`: `check(fn, stop_on_failure=True)` ends the run on the first failure with stop reason `"fatal"`.
- `budget_timeout.py`: `VerificationConfig(timeout=1.0)` ends the loop on the wall clock with stop reason `"timeout"`.
