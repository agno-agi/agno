# Framework cookbook test log

Earlier entries preserve the paths and filenames used during each test run.
See the final section for validation of the consolidated framework paths.

## Earlier navigation checks

### Harness entry-point migration — 2026-10-09

**Status:** PASS

**Description:** Updated navigation to the six rewritten Claude/Codex basic, tools and AgentOS examples. Existing session, cancellation, framework and managed-harness examples retain their paths.

**Result:** Local-link checks pass for the new root navigation. No active repository command references the six removed entry-point paths; old filenames in historical TEST_LOG entries are retained as historical evidence. This does not rerun or revalidate the remaining framework examples.


## Starting-example verification

See the final section for the latest Claude API/model update; earlier entries are historical evidence.

**Date:** 2026-10-09 (Europe/London)

**Source:** main `ff9b86d5be5245bd349e55c459bce45ba3d3cc21` plus this PR's cookbook/test changes, run from an isolated worktree before commit. The imported Agno path was the worktree's `libs/agno/agno/__init__.py`, not a released wheel or the user's checkout.

**Environment:** Python 3.12.8; editable Agno 3.1.2; SQLAlchemy 2.0.52; pytest 9.1.1. Fresh worktree development venv. Existing local CLI authentication; no credential values read or printed.

### Standalone and AgentOS acceptance

**Status:** PASS

**Description:** Ran the opt-in integration suite with both live-provider gates enabled. It launches six actual script executions and two actual AgentOS server processes. The servers receive two model requests each, one non-streaming and one SSE.

**Result:** 8 tests passed in 70.07 seconds, none skipped and no retries. Both providers returned correct shipping fees, real tool output and readable persisted run data. Fixture hashes were unchanged. See [Claude](claude-agent-sdk/TEST_LOG.md) and [Codex](codex/TEST_LOG.md) for versions and per-example evidence. Two earlier native-SDK smoke runs also passed.

---

### Failed-run exit behavior

**Status:** PASS

**Description:** Invoked each basic.py with its model override set to invalid-harness-cookbook-model.

**Result:** Both providers returned an error and the example exited 1 at its terminal-status assertion. No retry or tool side effect was used to turn the failure into a pass.

---

### Reproduction

Follow [TEST_PROMPT.md](TEST_PROMPT.md). Raw test output, HTTP event JSON and stored run JSON were retained locally under the worktree's ignored .context directory. They are not committed. Model prose and event counts are observations, not fixed golden output.

### Static and repository gates

**Status:** PASS

**Description:** Ran both provider pattern checks, compileall, import checks, local Markdown-link checks, the required ./scripts/format.sh and ./scripts/validate.sh, and git diff --check.

**Result:** All eight runnable examples meet the structure pattern and import without launching a server or model run. All 27 checked relative links resolve. Full repository Ruff and mypy validation passes. The formatter's edits to 12 unrelated baseline files were restored, and validation passed again on the scoped tree. With no provider opt-in flags, all eight live tests skip as intended.

**Environment observation:** The first import check attempted SQLite directory creation under a sandbox-restricted path. Repeating with HARNESS_STATE_DIR pointing at a temporary writable directory passed; importing a server still initializes its database configuration, but does not launch HTTP or invoke a model.

---

### Minimal installation: test collection

**Status:** FAIL

**Description:** Created a second clean venv with only the README's Agno extras, the two pinned SDKs and pytest.

**Result:** Collection stopped before model calls because the repository's integration conftest imports pytest-asyncio. Updated TEST_PROMPT.md to install pytest-asyncio explicitly. This was a test-setup omission, not a harness execution failure; the rerun is recorded separately.

---

### Minimal installation: corrected acceptance run

**Status:** PASS

**Description:** Reran the same eight live cases in the clean quickstart venv after installing pytest-asyncio. Only editable agno[os,sqlite], the two pinned SDKs, pytest and pytest-asyncio (and their dependencies) were installed. No development extras were present.

**Result:** 8 passed in 74.15 seconds, none skipped, no automatic retries. All script, tool, HTTP/SSE, stored-result and fixture-integrity checks passed again. SQLAlchemy resolved to 2.1.4; pytest-asyncio was 1.4.0. Python, model IDs and SDK versions matched the first run. Both HTTP paths again stored two Claude Read results or one Codex shell result per run.


## Configuration update in the normal checkout — 2026-10-09

### Live and unit acceptance

**Status:** PASS

**Description:** Updated Claude examples to named configuration fields and
`claude-sonnet-5-5`, added native `ClaudeAgentOptions` reuse, and ran both providers
from `/Users/ab/code/agno` on `d36a67ebe4` plus this PR's uncommitted update.

**Result:** Nine live cases passed in 70.28s, covering six script launches, two
HTTP cases (two model runs each), and one typed-options model run. The final
async/timeout form of the typed-options test also passed separately in 2.88s.
All 192 external-agent unit tests passed; the final focused Claude suite passed
45 cases. With opt-in flags absent, all nine live tests skip.

Claude SDK 0.2.165 / CLI 2.1.294 used `claude-sonnet-5-5`; Codex SDK/CLI 0.162.1
used `gpt-5.6-luna`. The user's shortened `sonnet-5-5` failed first in the native
SDK; the full model ID was then supplied by the user and passed. See the Claude
log for the failed attempt. Test output and HTTP captures are retained under
this checkout's ignored `.context/claude-dx/` directory.

---

### Repository validation environment

**Status:** FAIL

**Description:** The first full validation in the shared `.venv` encountered
32 mypy errors in unrelated database and optional-provider modules. Six
SQLAlchemy errors were also reproduced with the unchanged adapter through
mypy's shadow-file option.

**Result:** Kept framework changes scoped. Aligned local SQLAlchemy from 2.1.4
to the previously validated 2.0.52. Created a clean validation environment in
this same checkout with editable agno[dev], agnoctl[dev], both pinned harness
SDKs and SQLAlchemy 2.0.52, avoiding unrelated optional-provider packages.

---

### Clean repository validation

**Status:** PASS

**Description:** Ran `./scripts/format.sh` and `./scripts/validate.sh`;
restored formatter-only changes to unrelated files. Verified the scoped final
Python files with Ruff formatting/lint and the Claude cookbook pattern checker.

**Result:** Full validation passed in `.venvs/claude-dx-validation` (1111 Agno
and 21 agnoctl files checked by mypy). Final validation passed again after the
test updates. These checks do not establish disconnect recovery, native
transcript restoration or production isolation.


## Shared adapter DX for 3.2 — 2026-10-09

**Source:** `924d4ceb90` plus this PR's adapter API update, in the normal checkout
`/Users/ab/code/agno`. No worktree was used for this update.

### Constructors, typing, rendering and AgentOS regressions

**Status:** PASS

**Description:** Ran `libs/agno/tests/unit/agents` together with the AgentOS
schema, external background-stream and A2A interface unit modules. Tests cover
all built-in keyword-only signatures, configuration grouping, read-only SDK
identity, legacy metadata, explicit media rejection, sync/async rendering,
terminal persistence before printer exceptions, and static return types.

**Result:** 265 passed in 50.47s, including 55 new DX tests. Python 3.9.25 ran
99 runtime cases successfully (one mypy-only test skipped because mypy was not
installed in that environment). Python 3.9 checks used fake SDKs, not live native
SDK packages. The main validation environment remains Python 3.12.8.

The initial typing checks exposed an incorrect shared async return annotation
and an incomplete cancellation-service type union; both are corrected. The
first repository validation found a renderer-list annotation error, corrected
before the final successful run.

---

### Live examples with the shared printer

**Status:** PASS

**Description:** Reran all nine opt-in acceptance cases, including both updated
`basic.py` printers, native SDK comparisons, tool scripts, real HTTP/SSE and
persisted tool results, and native Claude options reuse.

**Result:** 9 passed in 61.99s; no skips or automatic retries. Claude used
`claude-sonnet-5-5`; Codex used `gpt-5.6-luna`. SDK/CLI versions match the previous
configuration update. Without opt-in flags, all nine cases skip as intended.
Raw results are in this checkout's ignored `.context/external-dx/` directory.

---

### Final repository gates

**Status:** PASS

**Description:** Ran required `./scripts/format.sh` and `./scripts/validate.sh`
in `.venvs/claude-dx-validation`; restored the formatter's unrelated baseline
edits. Ran both provider pattern checks, compileall and whitespace checks.

**Result:** Ruff and mypy pass (1113 Agno and 21 agnoctl source files); both
four-file provider pattern checks pass. The runtime SDK packages are optional
for construction. Native skill/plugin execution, disconnect recovery, durable
retry, multi-replica deployment and sandbox isolation are not established by
these checks.


### Live failed-run printing

**Status:** PASS

**Description:** Loaded each basic example without its main block, changed the
model only in memory to `invalid-harness-cookbook-model`, and invoked the printer.

**Result:** Both native providers rejected the request. Each wrapper displayed
`Run failed` and `Status: ERROR`, raised `AgentRunException`, and exited 1.
No example source or model default was changed, and neither check was retried.


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


## Consolidated framework paths — 2026-10-09

### Claude and Codex starting examples

**Status:** PASS

**Description:** Kept all cookbook integrations under `cookbook/frameworks`.
Restored the original `claude_basic.py`, `claude_tools.py`, `claude_agentos.py`
and matching Codex entry-point paths; added each provider's `*_native_sdk.py`
alongside its existing advanced examples. Merged guides and historical logs,
updated the acceptance suite, and moved the shared fixture into this directory.

**Result:** All nine live acceptance cases passed in 60.23s, without skips or
retries, using both provider opt-in flags. Six script executions, four HTTP/SSE
model requests and native Claude options reuse completed. HTTP results contained
two Claude Read results or one Codex shell result per run, correct fees of 8,
0, 0, and no metadata warnings. Fixture hashes were unchanged. Without opt-in
flags, all nine cases skip. Eight starting-example pattern checks, 80 relative
links, compileall, required full format/validation and whitespace checks pass.
All 52 original framework files are present; no active commands point to the
retired cookbook directory. Advanced examples were preserved, not rerun.

**Source/environment:** `1d91efd765` plus the consolidation in the normal checkout
`/Users/ab/code/agno`; Python 3.12.8; editable Agno; Claude SDK 0.2.165 with
`claude-sonnet-5-5`; Codex SDK 0.162.1 with `gpt-5.6-luna`; SQLAlchemy 2.0.52.
Existing CLI authentication was used without logging credentials. Raw evidence
is retained locally in `.context/frameworks-consolidation/`. The earlier limits
on recovery, compaction, skills/plugins and deployment validation still apply.


## Codex configuration DX — 2026-10-09

**Status:** PASS

**Description:** Added native client options, typed thread/turn options, consistent
named-setting precedence and ephemeral session bookkeeping, explicit unsupported
input errors, top-level MCP configuration and the shared Codex tools printer.

**Result:** 280 combined regression cases pass (37 Codex cases, 15 new). Python 3.9
passes 90 Codex/shared-DX cases with two SDK/mypy-dependent skips. All five Codex
live acceptance cases pass in 40.98s without retries or skips; Claude was deselected.
The updated MCP example also completes against the real Agno docs server.
Full format/validation, compile, whitespace and eight starting-example pattern
checks pass. All ten live cases skip without opt-in flags. Detailed commands,
versions, results and limits are in [Codex TEST_LOG](codex/TEST_LOG.md#codex-configuration-dx--2026-10-09).

Tested from `42e8d4191d` plus the Codex update in the normal checkout, using
Python 3.12.8, openai-codex / CLI 0.162.1 and `gpt-5.6-luna`. Evidence is retained
locally in `.context/codex-dx/`. Previous Claude results remain above; the prior
limits on recovery, durability and deployment claims still apply.


## Streaming examples — 2026-10-09

**Status:** PASS

**Description:** Stream the basic and native SDK comparisons, use streaming
printers in the structured-output and transcript examples, and show SSE first
in the HTTP commands. Existing tool/session/MCP printers already streamed.
Explicit non-streaming API acceptance coverage remains in place.

**Result:** All ten live acceptance cases pass in 60.88s without skips or retries.
Both native examples assert receipt of text deltas. The live Codex structured
output example returns valid JSON with the expected movie fields after streaming.
The live Claude transcript example streams both turns and passes its SQLite
mirror/resume/append assertions across two agent instances with separate working
directories. This is a local exercise, not a multi-machine recovery test.
All 13 interactive printer calls explicitly set `stream=True`; eight starting
examples pass pattern checks. Compile, whitespace and the required full format
and validation scripts pass. No framework defaults were changed.

**Test harness correction:** The first transcript verification wrapper forwarded
its own arguments into argparse and exited 2 before a model call. Running the
script directly corrected that wrapper issue and exited 0. Both logs are retained.

**Source/environment:** `9f22383c53` plus these example changes in the normal
checkout, using `.venvs/claude-dx-validation`, Python 3.12.8, Claude SDK 0.2.165
with `claude-sonnet-5-5`, and Codex SDK/CLI 0.162.1 with `gpt-5.6-luna`.
Existing local CLI authentication was used, with ANTHROPIC_API_KEY unset.
Logs and acceptance artifacts are in `.context/harness-streaming/`.

```bash
AGNO_TEST_CLAUDE_SDK=1 AGNO_TEST_CODEX_SDK=1 python -m pytest \
  libs/agno/tests/integration/agents/test_harness_cookbooks.py -q
python cookbook/frameworks/codex/codex_structured_output.py
python cookbook/frameworks/claude-agent-sdk/transcript_store.py
```
