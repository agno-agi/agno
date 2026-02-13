# Test Log: reasoning

> Updated: 2026-02-12

### reasoning_multi_purpose_team.py

**Status:** FAIL

**Description:** Multi-purpose reasoning team with mixed Claude/OpenAI models, ReasoningTools, and many specialist agents (web, finance, medical, calculator, knowledge, github, python, code sandbox). Sync team uses local Python agent; async team uses E2B sandbox. Loads knowledge from docs.agno.com URL.

**Result:** Import error — `e2b_code_interpreter` package not installed in demo venv. The E2B import is at module level (line 19: `from agno.tools.e2b import E2BTools`), so even the sync team path cannot execute. The sync team doesn't use E2BTools (only the async team does via `code_agent`), but the import blocks both.

---
