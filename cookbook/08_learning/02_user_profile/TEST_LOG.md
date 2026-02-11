# Test Log: 02_user_profile

**Date:** 2026-02-10
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o
**Services:** pgvector

## Structure Check

**Result:** Checked 3 file(s). Violations: 0
**Details:** Clean

---

## Runtime Results

### 01_always_extraction.py

**Status:** PASS
**Time:** ~30s
**Description:** Multi-session progressive profile building in ALWAYS mode. Profile for Marcus (backend engineer, Python/Go) built across sessions, preferred name updated to "Marc".
**Output:** Profile progressively enriched across sessions, preferred name update persisted.
**Triage:** n/a

---

### 02_agentic_mode.py

**Status:** PASS
**Time:** ~30s
**Description:** AGENTIC mode user profile with update_profile tool. Profile creation, recall, and preferred name update for Jordan Chen (JC -> Jordan).
**Output:** Agent created profile, recalled it in second session, updated preferred name in third.
**Triage:** n/a

---

### 03_custom_schema.py

**Status:** PASS
**Time:** ~35s
**Description:** Custom profile schema with additional fields beyond default name/preferred_name. Extended schema fields populated and persisted.
**Output:** Custom schema fields extracted and stored correctly alongside default fields.
**Triage:** n/a

---

## Summary

| File | Status | Triage | Notes |
|------|--------|--------|-------|
| 01_always_extraction.py | PASS | n/a | Progressive profile building, Marcus/Marc |
| 02_agentic_mode.py | PASS | n/a | Tool-based profile, Jordan Chen/JC->Jordan |
| 03_custom_schema.py | PASS | n/a | Extended schema fields work |

**Totals:** 3 PASS, 0 FAIL, 0 SKIP, 0 ERROR
