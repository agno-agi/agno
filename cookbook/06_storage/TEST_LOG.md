# Test Log: 06_storage

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o, gpt-4o-mini
**Services:** pgvector (port 5532), sqlite, json file

---

## Runtime Results

### 01_persistent_session_storage.py

**Status:** PASS
**Time:** ~7s
**Description:** Team persistence with PostgresDb. Agent stores session and responds to follow-up about space facts.
**Triage:** n/a

---

### 02_session_summary.py

**Status:** PASS
**Time:** ~15s
**Description:** SessionSummaryManager with PostgresDb. Agent creates session summaries after conversations about name/hobbies.
**Triage:** n/a

---

### 03_chat_history.py

**Status:** PASS
**Time:** ~10s
**Description:** Chat history retrieval from PostgresDb. Prints full message history including tool calls.
**Triage:** n/a

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `01_persistent_session_storage.py` | PASS | ~7s, PostgresDb team |
| `02_session_summary.py` | PASS | ~15s, SessionSummaryManager |
| `03_chat_history.py` | PASS | ~10s, history retrieval |

**Totals:** 3 PASS, 0 FAIL, 0 SKIP
