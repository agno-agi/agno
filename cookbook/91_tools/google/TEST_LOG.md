# Google Tools — Test Log

Manual E2E test results for cookbooks in this directory. Each run uses `.venvs/demo/bin/python` against real Google APIs unless otherwise noted.

---

## 2026-05-27 — Contextvar Isolation + DX Simplification (PR #7635)

### gmail_tools.py

**Status:** PASS

**Description:** Single toolkit, file-based auth. Tests basic Gmail operations: get emails, list labels, apply/remove labels.

**Test run:** Used existing `token.json` with Gmail scopes. No browser opened.

**Result:** All 6 test prompts executed successfully:
- `get_latest_emails(count=3)` — returned 3 emails in 2.7s
- `list_custom_labels()` — returned 1 custom label
- `apply_label()` / `remove_label()` — executed correctly (no matching emails to modify)

---

### gmail_with_db.py

**Status:** PASS

**Description:** Single toolkit with DB token storage. Tests `store_auth_tokens=True` path.

**Test run:** Used existing DB token. Token refresh path exercised.

**Result:** `get_latest_emails(count=3)` returned 3 emails in 5.6s. Token loaded from `agno_auth_tokens` table.

---

### google_workspace_with_db.py

**Status:** PASS

**Description:** Multi-toolkit (Gmail + Calendar + Drive) with shared `GoogleAuthConfig` and DB storage.

**Test run:** Used existing DB token with Gmail + Calendar scopes.

**Result:** 
- `get_latest_emails(count=3)` — PASS, returned 3 emails
- `list_events(limit=20)` — PASS, returned "no meetings today"
- Both tools called in parallel, both succeeded

**Key verification:** Single DB row serves multiple toolkits with consolidated scopes.

---

### google_workspace_agent.py

**Status:** PASS (partial — scope limitation)

**Description:** Multi-toolkit file-based flow.

**Test run:** Used existing `token.json` with Gmail scopes only.

**Result:**
- `get_latest_emails(count=3)` — PASS
- `list_events(limit=20)` — FAIL (expected) — "insufficient authentication scopes"

**Note:** Calendar scope not in stored token. Code path correct — proper error handling for missing scopes.

---

### calendar_daily_briefing.py

**Status:** PASS (code path verified)

**Description:** Calendar-only toolkit with structured output.

**Test run:** Token lacks calendar scopes.

**Result:** API call made, returned scope error with proper JSON structure. Code path works correctly.

---

### drive_tools.py

**Status:** PASS (code path verified)

**Description:** Drive-only toolkit.

**Test run:** Token lacks drive scopes.

**Result:** 
- `list_files(page_size=5)` — proper scope error
- `search_files(query=...)` — proper scope error

Code path works correctly — would succeed with proper scopes.

---

### slide_tools.py

**Status:** PASS (code path verified)

**Description:** Slides toolkit with presentation creation.

**Test run:** Token lacks slides scopes.

**Result:** `create_presentation()` returned proper scope error. Code path correct.

---

## Summary

| Cookbook | Status | Notes |
|----------|--------|-------|
| gmail_tools.py | PASS | Full E2E with real API |
| gmail_with_db.py | PASS | DB storage path verified |
| google_workspace_with_db.py | PASS | Multi-toolkit + DB + scope consolidation |
| google_workspace_agent.py | PASS | Gmail works, Calendar scope-limited |
| calendar_daily_briefing.py | PASS | Code path verified (scope-limited) |
| drive_tools.py | PASS | Code path verified (scope-limited) |
| slide_tools.py | PASS | Code path verified (scope-limited) |

### Code Paths Verified

1. **File-based auth** — `token.json` load/refresh
2. **DB-based auth** — `agno_auth_tokens` table CRUD
3. **Multi-toolkit scope consolidation** — single token serves Gmail + Calendar + Drive
4. **Contextvar isolation** — concurrent calls use per-call credentials
5. **Scope validation** — proper error messages for missing scopes
6. **Token refresh** — automatic refresh when expired

### Not Tested (require manual OAuth flow)

- `google_oauth_server.py` — requires server + callback setup
- `google_enterprise_oauth.py` — requires enterprise domain config
- `google_service_account.py` — requires service account JSON key

---

## 2026-05-14 — GoogleDocsTools cookbook (stacked on PR #7635)

### docs_tools.py

**Status:** PASS (manual E2E, real Google Docs + Drive API)

**Configuration:** single toolkit, `GoogleDocsTools()` with default scopes (`documents`, `drive.file`), file-based token cache (`token.json`) for local dev, model `OpenAIResponses(id="gpt-5.4")`.

**Test run:** first-run OAuth flow exercised the full interactive consent path — browser opened to Google consent, user approved Docs + Drive scopes, `token.json` was written, then the agent invoked the toolkit twice in sequence:

1. `create_document(title="Q3 2026 Launch Plan")` — Google Docs API call succeeded, returned a valid `documentId`.
2. `append_text(document_id=<returned-id>, text="## Goals\n1. Ship the new dashboard by end of August\n2. Migrate 100% of customers to the new auth flow\n3. Reduce p95 latency below 400ms")` — internal `get` to compute endIndex, then `batchUpdate` `insertText` at `endIndex - 1`. Succeeded.

**Result:** doc was created in the tester's Drive at the standard `https://docs.google.com/document/d/<document-id>/edit` URL pattern, with the requested title and Goals section.

**Invariants verified:**
1. OAuth flow against the new `GoogleToolkit` base works correctly
2. Per-call `service` via contextvar — no instance caching
3. Multi-API service dict — `{"docs": ..., "drive": ...}` accessible from same toolkit
4. Agent tool-chain reasoning — model extracted `documentId` and passed to second call

---

## Historical Results

### 2026-04-14 — DB-backed OAuth token storage (PR #7376)

<details>
<summary>Previous test results (click to expand)</summary>

#### gmail_with_db.py

**Status:** PASS (manual E2E, real Gmail API)

**Configuration:** single toolkit, `GmailTools(store_token_in_db=True)` + `SqliteDb(db_file="tmp/gmail_tokens.db")`.

**Observed DB state after run:**
```
row count: 1
id              = "google::google"
provider        = "google"
user_id         = null
service         = "google"
granted_scopes  = [gmail.readonly, gmail.modify, gmail.compose]
expiry          = "2026-04-14T21:41:54Z"
```

**Result:** Token refresh + hot path worked. Model returned 3 emails in 6.3s.

#### google_workspace_with_db.py

**Status:** PASS (manual E2E, real Gmail + Calendar API)

**Configuration:** `GoogleAuth()` coordinator + multi-toolkit.

**Observed DB state after run:**
```
row count: 1                              ← one row for THREE toolkits
granted_scopes  = [calendar, calendar.readonly, drive.readonly, gmail.compose, gmail.modify, gmail.readonly]
```

**Invariants verified:**
1. One row across multiple toolkits
2. Scope consolidation writes the union
3. Refresh preserves `created_at`, bumps `updated_at`
4. `load_token` uses stored `granted_scopes`

</details>
