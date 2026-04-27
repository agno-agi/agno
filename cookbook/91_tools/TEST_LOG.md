# Test Log

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
