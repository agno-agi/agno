# Implement `cookbook/08_learning/` Restructuring

You are restructuring the `cookbook/08_learning/` directory of the Agno AI agent framework. The full plan is attached as `RESTRUCTURE_PLAN.md`. Read it completely before starting.

## Context

- **Agno** is a Python AI agent framework. The `cookbook/` directory contains runnable example scripts.
- This is the **best-structured cookbook section** — all 31 files have docstrings and main gates. 84% already have section banners (wrong format).
- The goal is to achieve 100% style compliance by converting banner format and adding banners to 5 files that lack them.
- **No file merges, cuts, or moves needed** (except 2 renames in `09_decision_logs/`).
- The virtual environment for running cookbooks is at `.venvs/demo/bin/python`.
- The style checker is at `cookbook/scripts/check_cookbook_pattern.py`.

## CRITICAL: Read Each File Before Modifying

**Do NOT apply blanket regex-based rewrites.** Even though this section is well-structured, every file has unique learning configurations (user profile modes, memory strategies, session context types, entity relationships). You must:

1. **Read each file individually** before making any changes.
2. **Preserve the existing logic exactly** — only change the banner format and add missing banners.
3. **Do NOT change model names, learning configurations, memory strategies, or agent parameters.**

## What Needs to Change

This is a simple, mechanical task:

1. **Convert 26 files** from `# ============================================================================` banners to `# ---------------------------------------------------------------------------` banners
2. **Add section banners** to 5 files that lack them:
   - `00_quickstart/01_always_learn.py`
   - `00_quickstart/02_agentic_learn.py`
   - `00_quickstart/03_learned_knowledge.py`
   - `09_decision_logs/1_basic_decision_log.py` (also rename)
   - `09_decision_logs/2_decision_log_always.py` (also rename)
3. **Rename 2 files** in `09_decision_logs/`:
   - `1_basic_decision_log.py` → `01_basic_decision_log.py`
   - `2_decision_log_always.py` → `02_decision_log_always.py`
4. **Add README.md** to all 10 subdirectories
5. **Add TEST_LOG.md** to all 11 directories

## Style Guide Template

Every `.py` file must follow this exact structure:

```python
"""
<Feature Name>
=============================

Demonstrates <what this file teaches> using Agno learning.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("My name is John and I live in NYC")
```

### Rules

1. **Module docstring** — Title with `=====` underline, then what it demonstrates
2. **Imports before first banner** — `from` imports go between the docstring and the first `# ---` banner
3. **Section banners** — `# ---------------------------------------------------------------------------` (75 dashes) above section name, no blank line between banner and content
4. **Section flow** — Setup → Create Agent/Config → Run
5. **Main gate** — All runnable code inside `if __name__ == "__main__":`
6. **No emoji** — No emoji characters anywhere
7. **Self-contained** — Each file must be independently runnable

## Execution Plan

### Phase 1: Rename Files in 09_decision_logs/

```bash
mv cookbook/08_learning/09_decision_logs/1_basic_decision_log.py cookbook/08_learning/09_decision_logs/01_basic_decision_log.py
mv cookbook/08_learning/09_decision_logs/2_decision_log_always.py cookbook/08_learning/09_decision_logs/02_decision_log_always.py
```

### Phase 2: Convert Banner Format (26 files)

For each file that uses `====` banners:
1. Read the file
2. Replace all `# ============================================================================` with `# ---------------------------------------------------------------------------`
3. Verify the file still has correct structure

Process directories in order: `01_basics/` → `02_user_profile/` → `03_session_context/` → `04_entity_memory/` → `05_learned_knowledge/` → `06_quick_tests/` → `07_patterns/` → `08_custom_stores/`

### Phase 3: Add Banners to 5 Files Missing Them

For each of the 5 files without banners:
1. Read the file
2. Add section banners following the standard flow (Setup → Create → Run)
3. Keep existing logic and structure intact

Files:
- `00_quickstart/01_always_learn.py`
- `00_quickstart/02_agentic_learn.py`
- `00_quickstart/03_learned_knowledge.py`
- `09_decision_logs/01_basic_decision_log.py` (renamed in Phase 1)
- `09_decision_logs/02_decision_log_always.py` (renamed in Phase 1)

### Phase 4: Create README.md and TEST_LOG.md

**README.md** — Create for all 10 subdirectories (root already has one):
- `00_quickstart/`, `01_basics/`, `02_user_profile/`, `03_session_context/`, `04_entity_memory/`, `05_learned_knowledge/`, `06_quick_tests/`, `07_patterns/`, `08_custom_stores/`, `09_decision_logs/`

**TEST_LOG.md** — Create for ALL 11 directories (including root) with placeholder template:
```markdown
# Test Log: <directory_name>

> Tests not yet run. Run each file and update this log.

### <filename>.py

**Status:** PENDING

**Description:** <what the file does>

---
```

### Phase 5: Validate

Run the structure checker on each subdirectory:
```bash
.venvs/demo/bin/python cookbook/scripts/check_cookbook_pattern.py --base-dir cookbook/08_learning/<subdir>
```

Fix any violations. All files must pass.

## Important Notes

1. **This is a safe, mechanical task.** No files are being merged, cut, or moved (except 2 renames). The existing logic is excellent.
2. **Banner conversion only** — The main change is `====` → `----`. Count the dashes: exactly 75 dashes after `# `.
3. **Preserve all learning configs** — Do not change `learning=True`, `update_memory_on_run`, `add_history_to_context`, user profile modes, memory strategies, or any other learning parameters.
4. **No `__init__.py` files** — Cookbook directories don't use `__init__.py`.
5. **Read the plan carefully** — The RESTRUCTURE_PLAN.md confirms this section needs minimal work.
