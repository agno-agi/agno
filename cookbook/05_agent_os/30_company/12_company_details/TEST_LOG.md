# Test log

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
