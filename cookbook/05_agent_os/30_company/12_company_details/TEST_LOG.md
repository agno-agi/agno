# Test log

### Chat review follow-up — offline checks (2026-11-10)

**Status:** PASS

**Description:** Replaced the patch dictionary with optional name/description arguments, limited chat descriptions to 2,000 characters, and added confirmation-protected replacement of human-edited details. Tested on the isolated Python 3.12 development environment.

**Result:** 687 selected unit cases passed across CompanyTools, company-details HTTP, Company Manager Routines, authorization and manager regressions. The final result/prompt adjustments were rechecked with 133 affected unit cases. All 32 database cases passed on sync/async SQLite and PostgreSQL 18. Approval tests verify pause without writes, approval, rejection, permission revocation and an intervening edit. Full format and validation scripts passed. The HTTP description limit remains 20,000 characters.

The continuation tests also logged a nonfatal `TypeError: '_RoutineResultGuardrail' object is not callable` from the unchanged framework post-hook path. Their approval and database assertions passed; this follow-up does not change the framework hook handling.

---

### chat.py configuration — three live phrases (2026-11-10)

**Status:** PASS

**Description:** Real `gpt-5.6-luna` runs through the Super Agent HTTP endpoint, using disposable PostgreSQL schemas and the built-in managers; documentation access and result offloading were disabled. The first two phrases used the same company record in separate conversations; the partner phrase used a fresh, unedited company record. No web-search tools were configured.

**Result:** Final run:

| Exact phrase | Observed behaviour |
| --- | --- |
| “Our company is Acme. We build warehouse robots.” | Completed after one delegation and `update_company_details`. Saved name `Acme`, description `Builds warehouse robots.`; no approval pause. |
| “Rename our company to Acme Robotics; keep the description.” | Called `update_company_details`, then `confirm_company_details`, and paused for approval. The saved name remained `Acme` and description remained `Builds warehouse robots.` |
| “We're working with Acme, they build warehouse robots.” | Completed with no tool calls. Name remained `Company`, description remained null. The reply explicitly treated Acme as a customer or partner, not the user's company. |

Earlier live iterations exposed an unnecessary confirmation after a successful initial save, an acknowledged-but-unsaved introduction, and a partner company incorrectly saved into the unedited record. Those results led to an explicit successful-save result and clearer own-company routing in the existing prompt lines. One earlier partner check also hit a test-harness event-loop error; separate model clients fixed the harness before rerunning.

The final live rename was not approved; approval/rejection and continuation were verified with deterministic offline tests. No UI walkthrough, hosted deployment or merge. These are observed live outcomes, not a guarantee that every future ambiguous phrase will be classified correctly.

---

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
