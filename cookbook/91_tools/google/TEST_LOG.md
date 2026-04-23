# Google Tools — Test Log

Manual E2E test results for cookbooks in this directory. Each run uses `.venvs/demo/bin/python` against real Google APIs unless otherwise noted.

## 2026-04-14 — DB-backed OAuth token storage (PR #7376)

### gmail_with_db.py

**Status:** PASS (manual E2E, real Gmail API)

**Configuration:** single toolkit, `GmailTools(store_token_in_db=True)` + `SqliteDb(db_file="tmp/gmail_tokens.db")`, model `OpenAIResponses(id="gpt-5.4")`.

**Test run:** cookbook re-executed against an existing token row (created ~2.5h earlier), so this exercised the **refresh + hot path** rather than first-run OAuth. No browser opened.

**Observed DB state after run (direct sqlite query):**

```
row count: 1
id              = "google::google"
provider        = "google"
user_id         = null
service         = "google"
granted_scopes  = [gmail.readonly, gmail.modify, gmail.compose]
expiry          = "2026-04-14T21:41:54Z"  (fresh, refreshed from the expired token in the DB)
created_at      = 1776190407
updated_at      = 1776199315               (diff +8908s — refresh bumped updated_at, created_at preserved)
```

**Result:** `load_token` found the row, detected `creds.expired == True`, called `creds.refresh(Request())`, silently re-persisted the refreshed token, and proceeded with the Gmail API call. Model returned 3 most recent emails in 6.3s. No user interaction required.

---

### google_workspace_with_db.py

**Status:** PASS (manual E2E, real Gmail + Calendar API)

**Configuration:** `GoogleAuth()` coordinator + `GmailTools(google_auth=ga)` + `GoogleCalendarTools(google_auth=ga)` + `GoogleDriveTools(google_auth=ga)`, single `SqliteDb(db_file="tmp/google_workspace_db.db")`, model `OpenAIResponses(id="gpt-5.4")`.

**Test run:** re-executed against an existing token row. Exercises the **multi-toolkit coordinator refresh path** — the shared token is refreshed once and all three toolkits read the same row.

**Observed DB state after run:**

```
row count: 1                                              ← one row for THREE toolkits
id              = "google::google"
provider        = "google"
service         = "google"                                ← consolidated, not per-API
granted_scopes  = [
                    calendar,
                    calendar.readonly,
                    drive.readonly,
                    gmail.compose,
                    gmail.modify,
                    gmail.readonly,
                  ]                                        ← 6 scopes unioned from 3 toolkits
expiry          = "2026-04-14T21:42:17Z"                   (fresh)
created_at      = 1776190152
updated_at      = 1776199338                               (diff +9186s — refresh bumped updated_at)
```

**Result:** Single DB row serves all three toolkits. Gmail tool call (`get_latest_emails(count=3)`) and Calendar tool call (`list_events(limit=20, start_date=2026-04-14T00:00:00)`) both succeeded using credentials from the same row. Model composed a unified "3 emails + 0 meetings today" response in 6.1s. No user interaction required.

**Invariants verified by this run:**

1. **One row across multiple toolkits** — not three rows, not per-API splits. Matches the PR description's claim that `service` is always `"google"` for Google toolkits.
2. **Scope consolidation writes the union** — the stored `granted_scopes` covers all three toolkits' scopes (6 total), not just whichever toolkit triggered the most recent refresh.
3. **Refresh path preserves `created_at` and bumps `updated_at`** — the upsert `set_` clause deliberately omits `created_at`, so the first-consent timestamp survives across refreshes.
4. **`load_token` prefers stored `granted_scopes` over caller's scopes** — `GoogleCalendarTools` asking for calendar scopes still gets a Credentials object with the full 6-scope union, preventing scope narrowing on its refresh.

---

### google_workspace_agent.py

**Status:** PASS (backward-compat verification)

**Description:** Multi-toolkit file-based flow with no DB. Verifies that the existing `token.json` path is unchanged by this PR — default `GmailTools()` / `GoogleCalendarTools()` / `GoogleDriveTools()` construction still opens a browser and writes `token.json` as before.

**Result:** File-based multi-toolkit flow works identically to main. No regression.

---

### google_auth_db_storage.py

**Status:** PENDING (reference example)

**Description:** Documentation cookbook showing the `GoogleAuth` coordinator pattern wired to a DB without mounting the callback router. End-to-end semantics are identical to `google_workspace_with_db.py` above (which IS smoke-tested) — this cookbook differs only in having a single toolkit under the coordinator. Not separately E2E-tested because the covering test above exercises the same code paths.

---
