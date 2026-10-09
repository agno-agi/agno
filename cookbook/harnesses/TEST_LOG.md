# Harness cookbook verification

See the final section for the latest Claude API/model update; earlier entries are historical evidence.

**Date:** 2026-10-09 (Europe/London)

**Source:** main `ff9b86d5be5245bd349e55c459bce45ba3d3cc21` plus this PR's cookbook/test changes, run from an isolated worktree before commit. The imported Agno path was the worktree's `libs/agno/agno/__init__.py`, not a released wheel or the user's checkout.

**Environment:** Python 3.12.8; editable Agno 3.1.2; SQLAlchemy 2.0.52; pytest 9.1.1. Fresh worktree development venv. Existing local CLI authentication; no credential values read or printed.

### Standalone and AgentOS acceptance

**Status:** PASS

**Description:** Ran the opt-in integration suite with both live-provider gates enabled. It launches six actual script executions and two actual AgentOS server processes. The servers receive two model requests each, one non-streaming and one SSE.

**Result:** 8 tests passed in 70.07 seconds, none skipped and no retries. Both providers returned correct shipping fees, real tool output and readable persisted run data. Fixture hashes were unchanged. See [Claude](claude/TEST_LOG.md) and [Codex](codex/TEST_LOG.md) for versions and per-example evidence. Two earlier native-SDK smoke runs also passed.

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
