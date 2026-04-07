# Test Log

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
