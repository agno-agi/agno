# Verifiers

Evidence-based verification: `Agent(verifiers=[...])` checks the model's "done" against
executable evidence inside the run loop. When the model stops, the verifiers run; a failure
goes back to the model as an evidence report and the model continues working — inside the
same run. A run that never passes within budget ends with `RunStatus.unverified` and the
full record on `output.verification`.

## Quick Start

```python
import sys
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools
from agno.verifiers import ShellVerifier

# The agent edits src/; the tests live in checks/, a directory it cannot write
src = Path("src")
checks = Path("checks")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[FileTools(base_dir=src)],
    # The definition of done; sys.executable keeps the check on this interpreter
    verifiers=[ShellVerifier(f"{sys.executable} -m pytest -q", cwd=str(checks), env={"PYTHONPATH": str(src)})],
)

output = agent.run("Make the failing test pass.")
output.status  # RunStatus.completed or RunStatus.unverified
output.verification.stop_reason  # "passed" | "exhausted" | "timeout" | "unchanged_state" | "fatal"
```

The checks, not the model's summary, define done.

Start with [`01_basics/verify_done.py`](01_basics/verify_done.py); [`02_shell/tests_must_pass.py`](02_shell/tests_must_pass.py) is the Quick Start above with the scratch project built for you.

## Run

From the agno repo root, create the demo venv:

```bash
./scripts/demo_setup.sh
```

```bash
.venvs/demo/bin/python cookbook/14_verifiers/01_basics/verify_done.py
```

Every example uses `OPENAI_API_KEY` (`gpt-5.6-luna`) and writes its scratch files under `tmp/verifiers/`, resetting its own directory at the start of each run. `02_shell/` also needs `pytest` and `04_fingerprints/unchanged_state_guard.py` needs `git` on the PATH. `06_agentos/verified_agent_os.py` serves on `http://localhost:7777`.

## What's here

| Folder | Shows |
|--------|-------|
| `01_basics/` | A callable verifier, the unverified outcome, printed and persisted, streaming and async loops, per-check policy (`required`, `run_condition`, `max_retries`, `stop_on_failure`), the wall-clock budget |
| `02_shell/` | `ShellVerifier`: a passing test suite as the definition of done, run from a directory the agent cannot write |
| `03_scorer/` | `ScorerVerifier`: an LLM judge as an in-loop gate |
| `04_fingerprints/` | `GitWorktreeFingerprint` and `CallableFingerprint` + `stop_on_unchanged_state`: ending runs that change nothing |
| `05_team/` | A team member that verifies its own work; `Team(verifiers=...)` on the leader |
| `06_agentos/` | A verified agent served over AgentOS |
| `07_predictions/` | `@verified_tool`: a tool call that carries a falsifiable prediction |
| `08_workflow/` | `Verify` as a workflow step: conditional continue with evidence |

## The pieces

- **`verifiers=[...]`** — the definition of done: `ShellVerifier`, `ScorerVerifier`, or any
  callable taking `run_output` (optionally `run_context`, `agent`, `team`, `workflow`,
  `session`; it receives only what it declares). Return `True` to pass; a string or `False`
  to fail (the string becomes the evidence report); or a full `Verdict`. A coroutine is
  awaited on the async path.
- **`verifier(fn, ...)`** — per-check policy on any callable or verifier; the shipped verifiers
  take the same kwargs directly. `required=False` makes the check advisory (reports, never
  gates). `run_condition=predicate` decides per attempt whether the check runs, from the verdicts
  so far. `max_retries=N` re-runs the check itself up to N extra times before a failure counts.
  `stop_on_failure=True` ends the run on the first failure instead of re-entering the model.
- **`verification=VerificationConfig(...)`** (or `True` for the defaults) — the shared loop budget: `max_attempts`
  (default 3), `timeout` (a wall clock in seconds, checked between attempts), `stop_on_unchanged_state` +
  `fingerprint`, `add_verification_to_context` (the system-message paragraph naming the checks). Per-check
  config (a shell command's timeout, a judge's threshold) lives on the verifier itself.
- **`ShellVerifier(command, cwd=..., env=..., timeout=...)`** — exit 0 passes; the merged
  output is the report. The command runs on the host with no sandboxing and its exit code is
  the whole verdict, so run it from a directory the agent cannot write (`02_shell/`).
- **Fingerprints** — `GitWorktreeFingerprint(path)` digests a worktree; `CallableFingerprint(fn)`
  wraps any `() -> str` digest. With `stop_on_unchanged_state=True` a failed attempt whose fingerprint
  did not move ends the run with stop reason `"unchanged_state"`.
- **`Team(verifiers=..., verification=...)`** — the same loop on the leader's final answer;
  a member keeps its own verifiers inside every delegation.
- **`Verify([checks], on_fail=..., max_attempts=..., stop_on_unverified=...)`** — the workflow
  step. `on_fail` names the step (or index) to re-run with the evidence attached; the default
  is the previous step. `max_attempts` bounds the total passes through the checks (default 3). `stop_on_unverified=True` halts
  the workflow when the gate ends unverified instead of running the next step.
- **`@verified_tool(compare)`** — a tool whose optional `expect` argument carries the model's
  prediction; after the call `compare(result, expect)` runs and a mismatch prefixes the
  result with a divergence block the model has to address.
- **`output.verification`** — the persisted record: status, stop reason, and per-attempt
  verdicts with fingerprints and message indices. `print_response` prints an unverified run's
  last answer like any other, so read the outcome off `get_last_run_output()` after printing.
