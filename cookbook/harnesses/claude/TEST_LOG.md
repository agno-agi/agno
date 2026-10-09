# Claude cookbook test log

Latest configuration/API validation is recorded at the end; the original run below used the earlier model.

**Date:** 2026-10-09 (Europe/London)

**Source:** main `ff9b86d5be5245bd349e55c459bce45ba3d3cc21` plus this PR's cookbook/test changes, run from an isolated worktree before commit. The imported Agno path was the worktree's `libs/agno/agno/__init__.py`, not a released wheel or the user's checkout.

**Environment:** Python 3.12.8; editable Agno 3.1.2; SQLAlchemy 2.0.52; pytest 9.1.1. Fresh worktree development venv. Existing local CLI authentication; no credential values read or printed.

**Harness:** claude-agent-sdk 0.2.165; Claude Code 2.1.294; model claude-sonnet-4-6.

**Command:** `AGNO_TEST_CLAUDE_SDK=1 AGNO_TEST_CODEX_SDK=1 .venv/bin/python -m pytest libs/agno/tests/integration/agents/test_harness_cookbooks.py -q -o addopts=''`. Both providers together: 8 passed in 70.07 seconds; none skipped; no retries.

### basic.py

**Status:** PASS

**Description:** Real one-shot Agno wrapper run with the inclusive shipping-threshold prompt.

**Result:** Returned zero-dollar shipping and a COMPLETED RunOutput. A separate run with an invalid model exited 1 at the terminal-status assertion. A provider failure cannot silently pass this example.

---

### native_sdk.py

**Status:** PASS

**Description:** Same prompt/model using the native SDK directly.

**Result:** Returned zero-dollar shipping, a native Claude session ID and successful terminal status. This is a one-shot API comparison, not a timing benchmark or native-resume test.

---

### tools.py

**Status:** PASS

**Description:** Real streamed review of shipping.py and orders.json through the Agno wrapper.

**Result:** Text deltas and tool start/end events appeared; returned tool data contained the fixture's subtotal and boundary values. The answer correctly explained fees 8, 0, 0. The final RunOutput completed with successful tool data. Fixture file hashes stayed unchanged.

---

### agent_os.py

**Status:** PASS

**Description:** Started this exact server script on a loopback port with a temporary SQLite directory. Exercised health, agent discovery, one non-streaming tool run and one SSE tool run in independent sessions. Retrieved both runs through GET /agents/{id}/runs/{run_id}?session_id=... .

**Result:** Both runs were COMPLETED and retained two Read results each. The SSE response contained 146 events in this run, including RunStarted, RunContent, ToolCallStarted, ToolCallCompleted and RunCompleted. IDs were consistent; no RunError/RunCancelled appeared. Both answers correctly explained the boundary. Fixture hashes were unchanged. Event counts vary and are not acceptance thresholds.

---

## Limits

**Clean-install follow-up:** This provider's four cases also passed in the
minimal README environment: agno[os,sqlite], the pinned SDKs, pytest and
pytest-asyncio, with SQLAlchemy 2.1.4. Both providers together: 8 passed in
74.15 seconds. The first collection attempt exposed a missing pytest-asyncio
setup instruction; it was corrected before rerunning. See the root test log.

No browser disconnect, server restart, native transcript recovery, production authorization, queue retry, compaction, approval, subagent or sandbox-replacement claim is made by these tests. API access was real loopback HTTP, not an in-process ASGI mock. The SQLite result checks are separate from native conversation durability. Older tests in cookbook/frameworks retain their historical scope.


## Claude configuration update — 2026-10-09

**Source:** `codex/harness-cookbooks` in `/Users/ab/code/agno`, based on
`d36a67ebe4` plus the configuration changes in this PR. Main's merged setup
changes (#10920) are included. This follow-up ran in the user's normal checkout.

### Native model identifier

**Status:** FAIL

**Description:** First attempted the requested `sonnet-5-5` literal using the
native SDK example, before testing the wrapper.

**Result:** The SDK returned `unrecognized_model` and exited 1. No automatic
retry was performed. The user supplied the full ID `claude-sonnet-5-5`; all four
examples now use that literal without a model environment override.

---

### Full-ID standalone and AgentOS acceptance

**Status:** PASS

**Description:** With `claude-sonnet-5-5`, ran the native/basic/tools scripts and
real AgentOS HTTP/SSE/persisted-result checks. Added a fifth Claude test that
reuses the native example's `ClaudeAgentOptions` directly in `ClaudeAgent`.

**Result:** The initial four Claude cases passed in 28.25s in `.venv`.
The expanded combined Claude/Codex suite passed all nine cases in 70.28s in
`.venvs/claude-dx-validation`, with no skips or retries. Claude HTTP results
contained two Read results each and correct fees of 8, 0, 0. Fixture hashes
were unchanged. After giving the new native-options test an explicit async
120-second timeout, that final test passed again in 2.88s. The input options
object retained its original resume, streaming and tool configuration.

**Environment:** Python 3.12.8; editable Agno 3.1.2 from this checkout;
claude-agent-sdk 0.2.165; bundled Claude Code 2.1.294. Clean validation used
SQLAlchemy 2.0.52, pytest 9.1.1 and pytest-asyncio 1.4.0. Existing local CLI
credentials were used; no credential values were logged.

---

### Configuration and session regressions

**Status:** PASS

**Description:** Tested typed options, named overrides including empty/false
values, independent configuration containers, callback/service identity,
legacy deprecation and precedence, conflicting session/stream settings,
transcript-store injection, checkpoint exclusions and SDK-optional imports.
Exercised typed options through sync and async runs, streaming and non-streaming,
including a second run that resumes the native session.

**Result:** 192 external-agent unit tests passed. The final focused Claude
configuration/session suite passed all 45 cases. Native skills/plugins option
forwarding is covered by configuration tests; real skill/plugin execution was
not tested. The earlier durability and deployment limits still apply.


## Shared adapter API update — 2026-10-09

### basic.py, native_sdk.py, tools.py and agent_os.py

**Status:** PASS

**Description:** Reran the combined opt-in live suite after switching basic.py
to the shared failure-aware printer and making adapter constructors keyword-only.

**Result:** All nine Claude/Codex cases passed in 61.99s, including the four
Claude script/HTTP cases. The full run also checks native Claude options.
Model and SDK versions are unchanged from the preceding entry. Runs used the
normal checkout at `924d4ceb90` plus the API update. Fixture integrity and stored
tool output checks passed. Full evidence and limits are in the
[root test log](../TEST_LOG.md#shared-adapter-dx-for-32--2026-10-09).

The shared regression suite passed 265 cases, including both sync/async printers
for success, error and cancellation, keyword-only signatures, unsupported media
rejection, SDK metadata compatibility and public typing.


### Live failed-run printing

**Status:** PASS

**Description:** Loaded each basic example without its main block, changed the
model only in memory to `invalid-harness-cookbook-model`, and invoked the printer.

**Result:** Both native providers rejected the request. Each wrapper displayed
`Run failed` and `Status: ERROR`, raised `AgentRunException`, and exited 1.
No example source or model default was changed, and neither check was retried.


### Example configuration cleanup — 2026-10-09

**Status:** PASS

**Description:** Removed explicit turn and dollar limits from all four Claude
examples and corrected the root README's description. Ran the four-example
pattern check, compileall and whitespace checks.

**Result:** Static checks pass. No live model calls were rerun for this
configuration-only cleanup; previous live results describe the earlier limits.


## Claude live acceptance without explicit limits — 2026-10-09

### native_sdk.py, basic.py, tools.py, agent_os.py and typed options

**Status:** PASS

**Description:** Ran the five Claude acceptance cases on clean source
`78f321ba9ddd3d7c32221ced4c8d9df0c61dff96` from `/Users/ab/code/agno`, after
removing explicit turn and dollar limits. Command:

```bash
AGNO_TEST_CLAUDE_SDK=1 .venvs/claude-dx-validation/bin/python -m pytest \
  libs/agno/tests/integration/agents/test_harness_cookbooks.py -k claude -q
```

**Result:** 5 passed, 4 Codex cases deselected, in 29.47s. No skips or automatic
retries. This made six successful model calls: three standalone examples, two
AgentOS HTTP runs (non-streaming and SSE), and native-options reuse. Native and
wrapped basic answers correctly gave zero shipping at the threshold. The tools
script and both HTTP outputs correctly gave fees 8, 0, 0; each HTTP run stored
two Read results and COMPLETED status with no metadata warnings. Fixture hashes
were unchanged. The input native options retained their original configuration.

**Environment:** Python 3.12.8; editable Agno 3.1.2 imported from this checkout;
Claude SDK 0.2.165 / CLI 2.1.294; literal model `claude-sonnet-5-5`; SQLAlchemy
2.0.52; pytest 9.1.1 and pytest-asyncio 1.4.0. Existing local CLI authentication
was used without reading or logging credentials. Output, HTTP events and stored
results are retained locally under `.context/claude-live-no-limits/`.

### Live failure behavior

**Status:** PASS

**Description:** Loaded the current basic example, set an invalid model only
in memory and invoked its printer. No source defaults were changed.

**Result:** Claude rejected the model; the wrapper displayed `Run failed` and
`Status: ERROR`, raised `AgentRunException` and exited 1. No retry was performed.

These results verify the current Claude cookbook flows. They do not establish
live history/resume, compaction, disconnect survival, durable retries,
multi-replica recovery, skill/plugin execution or sandbox isolation.
