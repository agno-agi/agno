# Parallel — Test Log

## Static validation

### check_cookbook_pattern.py

**Status:** PASS

**Description:** Ran `.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/integrations/parallel --recursive`.

**Result:** Checked 9 files, 0 violations (docstrings, section banners, Create/Run order, main gates, emoji rules).

---

### ruff (format + check)

**Status:** PASS

**Description:** `ruff format` and `ruff check` over `cookbook/integrations/parallel`.

**Result:** 9 files left unchanged by format; ruff check clean.

---

## Runtime

**Status:** PENDING — requires `PARALLEL_API_KEY` (and `OPENAI_API_KEY` for the model/embeddings). Not run in this pass.

Notes for whoever runs these live:

| File | Status | Notes |
|------|--------|-------|
| `01_quickstart.py` | PENDING | Search; fastest smoke test |
| `02_extract_content.py` | PENDING | Extract from given URLs |
| `03_deep_research.py` | PENDING | Task API; base processor, can take minutes |
| `04_research_assistant.py` | PENDING | Writes `tmp/parallel_assistant.db` |
| `05_web_plus_knowledge.py` | PENDING | Needs `chromadb`; downloads a sample PDF; writes `tmp/chromadb` |
| `06_research_team.py` | PENDING | Team run; deep researcher uses Task API |
| `07_research_workflow.py` | PENDING | Writes `tmp/parallel_workflow.db` |
| `08_competitive_intel_monitor.py` | PENDING | Creates a server-side monitor; no events on first run |
| `09_agent_os_app.py` | PENDING | Starts AgentOS on http://localhost:7777 — boot then terminate |

---
