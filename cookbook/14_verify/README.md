# Verify

Evidence over prose. An agent's completion claim is checked against executable evidence before it counts, and a
tool call can carry a prediction the framework holds it to.

Two primitives:

- `run_verified(agent, input, verifiers=[...])` runs the agent, then runs every verifier when the model stops.
  A failure injects a bounded evidence report and continues the run through `Agent.continue_run`; a run that
  exhausts its budget without passing ends as `unverified`, a named outcome instead of a silent success.
- `@verified_tool(compare)` on a tool with an `expect` parameter compares the prediction the model sent with the
  result, and prefixes a divergence block on a wrong one.

## Structure

```
14_verify/
├── 01_basics/
│   ├── verify_done.py        # callable verifier: the file-must-exist gate, with a visible continuation
│   └── unverified.py         # an impossible check: the unverified outcome and what a caller reads back
├── 02_shell/
│   └── tests_must_pass.py    # ShellVerifier("pytest -q") as the definition of done for a small fix
├── 03_scorer/
│   └── judge_gate.py         # ScorerVerifier(JudgeScorer(...)): the shipped scorer surface as a completion gate
├── 04_predictions/
│   └── verified_tool.py      # a stateful tool with a hidden rule; a wrong prediction forces a replan
└── 05_fingerprints/
    └── noop_guard.py         # GitWorktreeFingerprint + stop_on_noop: claiming done without changing anything
```

## Running

```bash
export OPENAI_API_KEY=...
.venvs/demo/bin/python cookbook/14_verify/01_basics/verify_done.py
```

Every example creates its own scratch directory (or scratch git repository) and points the tools, the
verifier and the fingerprint at it, so nothing touches your checkout. Every agent driven by `run_verified`
carries `VERIFICATION_NOTICE` in its instructions so the model knows up front that the host checks completion;
`04_predictions` uses a plain `agent.run`, since `verified_tool` works per call and needs no notice.

## What to read in the output

- `result.status` is `verified` or `unverified`; `result.stop_reason` says why the loop ended
  (`passed`, `exhausted`, `timeout`, `noop`, `paused`, `error`, `cancelled`).
- `result.attempts` has one entry per attempt: its `run_id` (each continuation is a forked sibling run), its
  verdicts, its fingerprint, and its metrics.
- `result.output.status` is still `RunStatus.completed` when the verification failed. Read `result.status`.
