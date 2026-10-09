# Claude cookbook test log

All examples now live in this directory. Earlier entries retain the paths and
filenames used at the time of each run. See the final section for validation
of the consolidated paths.

## Earlier framework examples


## 2026-10-09

### transcript_store.py

**Status:** PASS

**Description:** Replaces `session_store.py`. Runs replica A (first turn, stores a fact) and replica B (second agent instance, different working directory) against one database in a single process, printing the `agno_transcripts` rows after each step. Ran with the demo environment, claude-agent-sdk 0.2.110, Claude Code 2.1.250 and macOS Keychain login, both without flags (SQLite) and with `--postgres` (pgvector container).

**Result:** On this branch's schema (positions numbered from 1, `framework` and `agno_session_id` columns): SQLite: replica A mirrored rows 1 to 12; replica B replied with the stored password, kept the same Claude session id, and appended rows 13 to 21. Postgres: same, 12 rows then 9 new. A Postgres table left over from the earlier branch schema raised a schema mismatch and had to be dropped first; it is recreated on first use. No API key or custom `CLAUDE_CONFIG_DIR` was needed because the SDK copies credentials into the temporary config directory it uses for a store-backed resume.

---

## 2026-10-08

### session_store.py

**Status:** FAIL

**Description:** Launched the real two-process verification with claude-agent-sdk 0.2.148 using the shared demo environment and this worktree on PYTHONPATH. Both processes use fresh config directories.

**Result:** Process A reached Claude but returned `Not logged in`. Authentication for an empty config directory is not configured. Cross-process transcript resume remains unverified; this is not a passing integration run.

---

### Transcript and adapter unit tests

**Status:** PASS

**Description:** 70 agent tests passed, including SDK store conformance through one bound store per project, SQLite/AsyncSQLite persistence, key rewriting, retries, tools, and resume fallback. The optional summary contract is not implemented.

**Result:** Unit coverage passes; real SDK verification is separate.

---

### session_store.py (authenticated rerun)

**Status:** PASS

**Description:** Used the existing `ANTHROPIC_API_KEY` exported by `.envrc`, inherited by both child processes. No credential values were read or printed. Ran the demo environment with this worktree's `libs/agno` on PYTHONPATH and debug/monitor flags unset.

**Result:** Process A replied `OK` and stored the SDK transcript. Its Agno run history was deleted. Process B, with a separate empty config directory, replied `cobalt orchard 742`. Verified with the per-run ClaudeSDKClient implementation.

---

### PostgreSQL transcript conformance

**Status:** PASS

**Description:** Executed the SDK store contracts on PostgresDb and AsyncPostgresDb against disposable schemas in PostgreSQL 18. SQLite and AsyncSQLite also pass. The optional summary contract is not implemented. Tests use one bound store per project to reconcile the SDK suite's caller-selected project keys with this adapter's binding.

**Result:** Both PostgreSQL variants pass. A database transaction serializes position allocation across processes; the SQLite restart test resets the in-memory counter while holding time constant and verifies append order.

---

### Exact phase 1 source verification

**Status:** PASS

**Description:** Checked the committed phase 1 source independently of phase 2 in an isolated archive. Verified the imported Agno path before testing.

**Result:** 72 phase 1 agent tests passed and the original query-based adapter passed the real two-process resume test. Four additional missing-table/empty-batch tests cover every transcript DB adapter. Guard mutation checks all failed their named tests when the guard was removed and passed after restoration.

**Environment:** Python 3.12; claude-agent-sdk 0.2.148; openai-codex 0.162.0; SQLAlchemy 2.0.52, matching the demo environment. Fresh setup resolved SQLAlchemy 2.1.4, which reproduced six unrelated mypy errors on the unchanged base; validation passes with 2.0.52.

---

## 2026-10-08: background lifecycle

### background_cancel.py

**Status:** PASS

**Description:** Ran the real SDK with this worktree imported. Started a detached streamed run, cancelled after the first content event, drained the SSE stream, and read the stored run. Claude used the API key exported by `.envrc`. Codex used `gpt-5.6-luna`, read-only sandboxing and `approval_mode="deny_all"`.

**Result:** The SDK turn was interrupted and the final output and database row were CANCELLED. Both the shared demo environment and the env-gated integration tests in the worktree's development environment passed.

---

### Lifecycle and regression suite

**Status:** PASS

**Description:** 736 tests covering external agents, native background execution, cancellation, event streams, status persistence, queue retries/fencing, scoped reads and A2A. All five real integration cases were enabled and passed: Claude two-process resume, Claude cancel, Codex cancel, sync PostgreSQL transcripts, async PostgreSQL transcripts.

**Result:** 736 unit/regression tests passed; 5 integration tests passed, none skipped. One existing AsyncMock warning arose in the unchanged native save-fencing test. Required format and validation scripts passed with SQLAlchemy 2.0.52.

---


### Transcript mirror failure regression (2026-10-08)

**Status:** PASS

**Description:** The installed SDK parser and mirror batcher were driven with synthetic transport
frames and a transcript store that rejects every append. All three attempts failed. The completed
response retained its content and exposed `transcript_persistence_failed` in run metadata.
Streaming/non-streaming unit regressions also verify warning serialization and persisted history.

**Result:** Durability failure is visible without reexecuting completed work. This is a local SDK
fault-injection test, not a live provider run. Phase 1 agent tests: 78 passed. Format and validation pass.

### Lifecycle persistence review regressions (2026-10-09)

**Status:** PASS

**Description:** Injected terminal database failures in sync/async SQLite queue runs, with both
streaming modes and transient/permanent failures. Tickets retry and do not report success over
an unfinished run. Real sync/async PostgreSQL tests cover session-identity fencing and rollback
when session storage fails. In-memory SQLite async polling retains the completed run.

**Result:** 751 unit/regression tests, 12 external-agent PostgreSQL integration tests and 13 existing
native PostgreSQL tests passed. Format and validation passed. These are persistence fault-injection
checks; the earlier live provider cancellation runs were not repeated.

---

---

### session_store.py (transcript schema revision)

**Status:** PASS

**Description:** Reran the two-process verification after scoping transcript rows by framework, project, session and subpath, numbering positions per transcript and recording the owning Agno session. Used claude-agent-sdk 0.2.95 from the demo environment, the `ANTHROPIC_API_KEY` from `.envrc` and empty config directories.

**Result:** Process A replied `OK`; process B, with its Agno run deleted, replied `cobalt orchard 742`. The PostgreSQL contract test (PostgresDb and AsyncPostgresDb) passed against PostgreSQL 14.


## Refreshed starting examples


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


### Claude streamed tools through print_response — 2026-10-09

**Status:** PASS

**Description:** Simplified `claude/tools.py` to
`result = agent.print_response(prompt, stream=True)`. The live test executes
its actual main block, checks the Tool Calls panel, and reads the returned
RunOutput to verify successful tool results contain both fixture files.

**Result:** 1 passed, 8 deselected in 6.71s, without retries, using
`AGNO_TEST_CLAUDE_SDK=1` and `-k 'claude and tools'`. Claude returned COMPLETED,
two successful Read results and correct shipping fees. Fixture hashes remained
unchanged. Tested `e1d1f5a48c` plus this update in the normal checkout, with the
same SDK/model environment as the preceding live acceptance run. Required
format/validation scripts and the provider pattern check passed. Raw evidence
is retained under `.context/claude-tools-printer/`.


## Consolidated paths — 2026-10-09

### claude_basic.py, claude_native_sdk.py, claude_tools.py and claude_agentos.py

**Status:** PASS

**Description:** Ran the actual examples from this directory, alongside the
existing advanced examples, through the updated live acceptance suite.

**Result:** All nine combined Claude/Codex cases passed in 60.23s with no skips
or retries. Correct shipping answers, actual tool data, HTTP/SSE, saved results
and fixture integrity checks passed. Native Claude options reuse also passed.
Source was `1d91efd765` plus the path consolidation in the normal checkout;
SDK/model versions are unchanged from the preceding runs. See the
[root log](../TEST_LOG.md#consolidated-framework-paths--2026-10-09) for complete
evidence and limits. This does not rerun this directory's advanced examples.
