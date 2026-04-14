# Google Tools — Test Log

Manual E2E test results for cookbooks in this directory. Each run uses `.venvs/demo/bin/python` against real Google APIs unless otherwise noted.

## 2026-04-14 — DB-backed OAuth token storage (PR #7376)

### gmail_with_db.py

**Status:** PASS (manual E2E, real Gmail API)

**Description:** Single Gmail toolkit with `store_token_in_db=True` + `SqliteDb`. Verifies that the first run opens a local browser for OAuth consent, persists the credentials to `agno_auth_tokens`, and that subsequent runs load the token from the DB without re-prompting.

**Result:** First-run browser consent succeeded. Row created in `agno_auth_tokens` with composite id `google::google`. Re-running the cookbook immediately afterwards loaded the token from DB and returned the user's most recent emails without re-consent.

---

### google_workspace_with_db.py

**Status:** PASS (manual E2E, real Gmail API)

**Description:** `GoogleAuth` coordinator mode with Gmail + Calendar + Drive sharing one consent. Verifies scope consolidation — a single OAuth flow covers the union of all registered scopes and writes one row under `service="google"`.

**Result:** First-run consent screen listed all three services' scopes bundled. Token row created with `granted_scopes` equal to the union. Subsequent runs loaded the shared token across all three toolkits without re-consent.

---

### google_workspace_agent.py

**Status:** PASS (backward-compat verification)

**Description:** Multi-toolkit file-based flow with no DB. Verifies that the existing `token.json` path is unchanged by this PR — default `GmailTools()` / `GoogleCalendarTools()` / `GoogleDriveTools()` construction still opens a browser and writes `token.json` as before.

**Result:** File-based multi-toolkit flow works identically to main. No regression.

---

### google_auth_db_storage.py

**Status:** PENDING (reference example)

**Description:** Documentation cookbook showing the `GoogleAuth` coordinator pattern wired to a DB. End-to-end test deferred to the follow-up interface-mode PR which will add a Slack/WhatsApp cookbook that mounts `get_oauth_router()` and exercises the hosted callback flow.

**Result:** Not yet run against a live deployment — this cookbook is a reference for the pattern rather than an executable E2E example.

---
