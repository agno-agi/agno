# Test Log: examples

**Date:** 2026-02-11
**Environment:** `.venvs/demo/bin/python`
**Model:** gpt-4o

---

## Runtime Results

### multi_user_multi_session.py

**Status:** PASS
**Time:** ~15s
**Description:** Multi-user, multi-session pattern with SqliteDb. 2 users, 2 sessions each. Agent recalls previous context within same session.
**Triage:** n/a

---

### selecting_tables.py

**Status:** PASS
**Time:** ~10s
**Description:** Custom table selection pattern with SqliteDb. Agent uses custom session table name and persists history.
**Triage:** n/a

---

## Summary

| File | Status | Notes |
|------|--------|-------|
| `multi_user_multi_session.py` | PASS | ~15s, 2 users/2 sessions |
| `selecting_tables.py` | PASS | ~10s, custom table name |

**Totals:** 2 PASS, 0 FAIL, 0 SKIP
