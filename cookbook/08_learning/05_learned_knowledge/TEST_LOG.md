# Test Log: 05_learned_knowledge

**Date:** 2026-02-10
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o
**Services:** pgvector

## Structure Check

**Result:** Checked 2 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_agentic_mode.py

**Status:** PASS
**Time:** ~45s
**Description:** Agentic learned knowledge. Agent saves insights via tools and searches them to answer future questions.
**Output:** Knowledge saved via save_knowledge tool, search_knowledge returned relevant results.
**Triage:** n/a

---

### 02_propose_mode.py

**Status:** PASS
**Time:** ~40s
**Description:** Propose mode for learned knowledge. Agent proposes learnings for user approval. User can accept or reject proposed knowledge.
**Output:** Agent proposed knowledge items, accepted items persisted, rejected items discarded.
**Triage:** n/a

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 01_agentic_mode.py | PASS | n/a | Save and search knowledge via tools |
| 02_propose_mode.py | PASS | n/a | Propose-approve workflow works |

**Totals:** 2 PASS, 0 FAIL, 0 SKIP, 0 ERROR
