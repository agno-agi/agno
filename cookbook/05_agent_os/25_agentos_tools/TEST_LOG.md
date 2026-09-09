# Test Log — 25_agentos_tools

Tested 2026-07-27 on branch `feat/agentos-tools` (tip `567cbdaa0` plus the
review-fix pass: schedule error redaction, page-scoped history summary,
span-stats paging tiebreak, performance eval run times) with
`.venvs/demo/bin/python` and `OPENAI_API_KEY` set.

### platform_ops_agent.py

**Status:** PASS

**Test mode:** LIVE

**Description:** Constructs a worker agent and an ops agent sharing one SqliteDb,
with tracing enabled on the AgentOS. Runs the worker twice (calculator tool calls),
then verifies through AgentOSTools directly: get_run_activity reports 2 traces for
`research-worker` with duration aggregates, get_tool_activity lists the calculator
tools and model calls, get_platform_metrics reports the session with token totals.
Finally the ops agent answers a platform-summary question.

**Result:** Self-verification passed: 2 worker traces at 3,440.5 ms average with
0 errors, tools `add`/`multiply` visible, 1 session with 1,561 total tokens at
mid-demo. The ops agent produced a grounded summary: a per-agent run table
(research-worker, 2 runs, 1 session, 3,440.5 ms avg, 3,798.0 ms max, 0 errors),
one endpoint-level trace reported separately from component-attributed traces,
tool and model-call telemetry repeating the "p95_duration_ms is not available on
this database backend" note, token usage (1,508 input / 53 output / 1,561 total),
model mix (gpt-5.5: 2 runs) — and it closed with "The platform does not report
monetary cost, only token totals" instead of estimating a spend figure.

---

## Validation

- Run activity, tool activity and platform metrics all read back real traced
  data; the demo's built-in assertions (at least 2 worker traces, at least 1
  agent session) passed.
- Truncation and backend-capability notes surface in the payloads and the agent
  repeats them instead of overstating; asked about spend, it gives token totals
  and says cost is not tracked.
- No sensitive payloads (span attributes, tool arguments) appear in any output.
- Reading the same database after the demo shows the ops agent's own run in the
  platform data (sessions rise to 2, model mix to 3 runs): the toolkit observes
  the OS it runs on, including itself.
