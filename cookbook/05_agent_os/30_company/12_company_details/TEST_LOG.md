# Test log

### company_details.py — chat editing follow-up (2026-11-10)

**Status:** PASS

**Description:** Ran the offline persistence example against a disposable local PostgreSQL 18 container. No model calls.

**Result:** Saved identity survived configuration reseeding and a stale write was rejected. The company-details database suite passed 32 cases across sync/async SQLite and PostgreSQL, including tool edits, partial updates, clearing descriptions, reopening storage and conflicts.

---

### chat.py — app construction only (2026-11-10)

**Status:** PASS

**Description:** Loaded the example with `runpy.run_path` and verified that it constructs an AgentOS app against disposable PostgreSQL. Did not start the server or send a live model request.

**Result:** App construction passed. Separate deterministic offline HTTP tests verify Super Agent delegation to Company Manager, caller permission enforcement, saved values in new conversations and restart persistence. Live-model interpretation and the UI chat walkthrough remain unverified.

---

### company_details.py

**Status:** PASS

**Description:** Local PostgreSQL initialization, human edit persistence across initialization, and rejection of a stale edit. No model calls.

**Result:** Company identity retained and stale update rejected. SQL adapter integration tests also cover PostgreSQL and SQLite, both sync and async.

---

### company_details.py with repository credentials (2026-11-09)

**Status:** PASS

**Description:** The default connection now matches `./cookbook/scripts/run_pgvector.sh`. Run against a throwaway database on that container through `DATABASE_URL`. No model calls.

**Result:** Saved identity retained and stale edit rejected. SQL adapter tests cover configuration updating the single row until it is edited, on PostgreSQL and SQLite, sync and async.

---


### company_details.py — final foundation review (2026-11-10)

**Status:** PASS

**Description:** Ran the offline example against a disposable local PostgreSQL database. Saved edits survived configuration reseeding and stale edits were rejected. Company details and former-manager policy tests passed all 62 cases across sync/async SQLite and PostgreSQL (also included in the final combined 636-test run).

**Result:** PASS. No live provider calls or deployment.

---
