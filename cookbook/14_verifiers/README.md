# Verifiers

Evidence-based verification: `Agent(verifiers=[...])` checks the model's "done" against
executable evidence inside the run loop. When the model stops, the verifiers run; a failure
goes back to the model as an evidence report and the model continues working — inside the
same run. A run that never passes within budget ends with `RunStatus.unverified` and the
full record on `output.verification`.

## Quick Start

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.verifiers import ShellVerifier

agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[...],
    verifiers=[ShellVerifier("pytest -q", cwd=repo)],  # the definition of done
)

output = agent.run("Make the failing test pass.")
output.status                    # RunStatus.completed or RunStatus.unverified
output.verification.stop_reason  # "passed" | "exhausted" | "timeout" | "noop"
```

The principle: **evidence over prose.** The checks, not the model's summary, define done.

## What's here

| Folder | Shows |
|--------|-------|
| `01_basics/` | A callable verifier, the unverified outcome, streaming the loop |
| `02_shell/` | `ShellVerifier`: a passing test suite as the definition of done |
| `03_scorer/` | `ScorerVerifier`: an LLM judge as an in-loop gate |
| `04_fingerprints/` | `GitWorktreeFingerprint` + `stop_on_noop`: ending runs that change nothing |
| `05_team/` | A team member that verifies its own work |
| `06_agentos/` | A verified agent served over AgentOS |
| `07_predictions/` | `@verified_tool`: a tool call that carries a falsifiable prediction |

## The pieces

- **`verifiers=[...]`** — the definition of done: `ShellVerifier`, `ScorerVerifier`, or any
  callable taking `run_output` (optionally `run_context`, `agent`, `session`). Return `True`
  to pass; a string or `False` to fail (the string becomes the evidence report); or a full
  `Verdict`.
- **`verification=VerificationConfig(...)`** — the shared loop budget: `max_attempts`
  (default 3), `timeout_s`, `stop_on_noop` + `fingerprint`, `add_notice`. Per-check config
  (a shell command's timeout, a judge's threshold) lives on the verifier itself.
- **`output.verification`** — the persisted record: status, stop reason, and per-attempt
  verdicts with fingerprints and message indices.
