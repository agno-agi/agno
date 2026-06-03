# Test Log

### strale_tools.py

**Status:** PASS

**Description:** Added a new cookbook example `strale_tools.py` and a built-in toolkit `StraleTools` (in `libs/agno/agno/tools/strale.py`) showing how to use the Strale API. Demonstrates both free capabilities (no API key required on the API, but validated/required by the SDK) like `iban-validate` and `email-validate`, and paid/enterprise capabilities like `company-search` and `sanctions-screening`.

**Result:** Verified that the `StraleTools` module imports correctly and that the script compiles and executes, properly catching the `ValueError` when `STRALE_API_KEY` is not set. Full runtime execution was not performed because agent model and Strale API credentials are required.

---

### file_tools.py (Examples 6-8: exclude_patterns)

**Status:** PASS

**Description:** Added three new examples (6-8) to the existing FileTools cookbook demonstrating the `exclude_patterns` parameter from PR #7618. Example 6 uses the default exclusion list (hides `.venv`, `.git`, `__pycache__`, etc.); Example 7 subtracts `.venv` from `DEFAULT_EXCLUDE_PATTERNS` so the agent can inspect installed packages while still filtering noise; Example 8 uses `exclude_patterns=[]` for full visibility. A `setup_exclusion_sandbox()` helper creates a deterministic fixture (real source + stub `.venv/lib/python3.12/site-packages/requests/` + `.git/HEAD`) so Examples 6-8 are reproducible. New examples use `model=OpenAIResponses(id="gpt-5.4")` per project convention.

**Result:** Ran the three new agents end-to-end with `PYTHONPATH=/Users/coolm/Developer/agno-pr-7618/libs/agno timeout 120 .venvs/demo/bin/python cookbook/91_tools/file_tools.py` (PYTHONPATH needed because the demo venv's editable install resolves to main, but the PR's new `DEFAULT_EXCLUDE_PATTERNS` export lives on the PR branch). Default agent returned only `README.md` and `main.py`; the `.venv`-allowed agent read `__version__ = '2.31.0'` from `.venv/lib/python3.12/site-packages/requests/__init__.py`; the no-exclusions agent listed `.git/HEAD` and every `.venv` file. Module import also verified under importlib — all three agents wire up with the expected `exclude_patterns` lengths (47, 46, 0).

---

### docling_tools/run.py

**Status:** PASS

**Description:** Refactored the original single-file Docling cookbook into a modular folder (`docling_tools/`) with separate files for shared paths, basic conversion examples, and OCR examples. Added PPTX and image conversion examples using static resources (`ai_presentation.pptx` and `restaurant_invoice.png`).

**Result:** Syntax validation passed for `paths.py`, `basic_examples.py`, `ocr_example.py`, and `run.py` using `python -m py_compile`. Re-ran Docling unit tests with `pytest libs/agno/tests/unit/tools/test_docling.py -q` and all 24 tests passed. Full cookbook runtime execution was not performed because agent model credentials are required.

---

### gitlab_tools.py

**Status:** PASS

**Description:** Added GitLab toolkit example and validated sync + async GitLab toolkit behavior with mocked unit tests and live GitLab API checks using a real project (`SalimELMARDI/agno-gitlab-tools-test`).

**Result:** Ran `pytest libs/agno/tests/unit/tools/test_gitlab.py -q` and all 18 tests passed, including async methods, internal async client handling coverage, and `enable_*` tool-toggle coverage (with `enable_get_projects` as the canonical project-read toggle). Also ran `ruff check` for changed files and both validation scripts (`libs/agno/scripts/validate.bat`, `libs/agno_infra/scripts/validate.bat`) with no issues. Live toolkit checks passed for `get_project`, `list_issues`, and `list_merge_requests` against `SalimELMARDI/agno-gitlab-tools-test`. Negative live check also passed: `get_project('wrong-group/wrong-project')` returned expected JSON error (`404 Project Not Found`). The cookbook agent runtime file was not executed because it requires model credentials.

---

### antigravity_tools.py

**Status:** PENDING

**Description:** Gemini-driven Agno agent delegates a research sub-task to an Antigravity sandbox via `AntigravityTools.run_antigravity_task`. The toolkit POSTs to the Gemini Agents API `/interactions` endpoint, caches `environment_id` in `agent.session_state` so the sandbox persists across calls in non-streaming mode, and returns the final text response.

**Result:** Unit tests pass covering session-state caching, env-id reuse on subsequent calls, HTTP error surfacing, custom-agent creation, and the delete endpoint. Live cookbook run with a partner Gemini API key remains the gating verification before merge.

---

### antigravity_agents_crud_tools.py

**Status:** PENDING

**Description:** Gemini-driven Agno agent drives the full Agents API lifecycle via `AntigravityTools` — `create_custom_antigravity_agent`, `run_custom_antigravity_agent`, then `delete_antigravity_agent`. Toolkit also exposes `get_custom_antigravity_agent`, `update_custom_antigravity_agent`, `list_antigravity_agents`, and `list_antigravity_agent_versions` for full CRUD coverage of `/v1beta/agents`.

**Result:** Unit tests pass. Live cookbook run with a partner Gemini API key remains the gating verification.

---

### antigravity_directory_tools.py

**Status:** PENDING

**Description:** `AntigravityTools(agent_directory=...)` parses a local agent folder (`agent.yaml` + `AGENTS.md` + `workspace/` + `skills/`), registers it via POST /agents (idempotent), and routes subsequent `run_antigravity_task` calls at the named agent. Re-uses the `example_agent/` folder from `cookbook/frameworks/antigravity/`.

**Result:** Unit tests pass for the new constructor path (register=False parse-only, register=True POSTs, 409 = success, agent= / default_sources= conflict validation, required-key validation, run_antigravity_task routes at the named agent post-load). Live cookbook awaiting partner key.

---

### antigravity_snapshot_tools.py

**Status:** PENDING

**Description:** Gemini-driven Agno agent runs `run_antigravity_task` to write a few files in the sandbox, then calls `download_antigravity_environment_snapshot` with `environment_id="current"` to resolve the env id from `agent.session_state` and save the resulting tar to disk. Demonstrates the full sandbox-write → archive flow through tool calls.

**Result:** Unit tests pass covering snapshot URL construction, byte-for-byte write to disk, "current" resolution from session_state, and the no-cached-env error path. Live cookbook awaiting partner key.

---
