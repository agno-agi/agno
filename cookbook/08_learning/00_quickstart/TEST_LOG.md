# Test Log: 00_quickstart

**Date:** 2026-02-10
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o
**Services:** pgvector

## Structure Check

**Result:** Checked 3 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_always_learn.py

**Status:** PASS
**Time:** ~30s
**Description:** ALWAYS mode learning. Agent auto-extracts user profile and memories without explicit tool calls. Cross-session recall confirmed.
**Output:** Profile and memories persisted, second session recalled prior context.
**Triage:** n/a

---

### 02_agentic_learn.py

**Status:** PASS
**Time:** ~30s
**Description:** AGENTIC mode learning. Agent uses update_profile and memory tools to store user info. Cross-session recall confirmed.
**Output:** Agent called update_profile and add_memory tools, second session recalled prior context.
**Triage:** n/a

---

### 03_learned_knowledge.py

**Status:** PASS
**Time:** ~45s
**Description:** Learned knowledge feature. Agent saves reusable knowledge about cloud provider selection and retrieves it in a later session.
**Output:** Knowledge saved via tool, search retrieved relevant insights on follow-up query.
**Triage:** n/a

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 01_always_learn.py | PASS | n/a | Cross-session recall confirmed |
| 02_agentic_learn.py | PASS | n/a | Cross-session recall confirmed |
| 03_learned_knowledge.py | PASS | n/a | Knowledge save and retrieval works |

**Totals:** 3 PASS, 0 FAIL, 0 SKIP, 0 ERROR
