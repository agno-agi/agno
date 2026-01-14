# Database Cookbook Testing Log

Testing database examples in `cookbook/06_storage/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## sqlite/

### sqlite_for_agent.py

**Status:** NOT TESTED

**Description:** Agent with SQLite storage.

---

## postgres/

### postgres_for_agent.py

**Status:** NOT TESTED

**Description:** Agent with PostgreSQL storage.

**Dependencies:** PgVector running

---

## in_memory/

### in_memory_storage_for_agent.py

**Status:** NOT TESTED

**Description:** Agent with in-memory storage.

---

## TESTING SUMMARY

**Summary:**
- Total examples: 63
- Tested: 0
- Passed: 0

**Notes:**
- Start with sqlite and in_memory (no external deps)
- postgres requires running pgvector
