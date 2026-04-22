# Context Cookbook Test Log

## 2026-04-22

### 00_filesystem.py

**Status:** PASS

**Description:** `FilesystemContextProvider` rooted at the cookbook
directory; agent lists and reads files.

**Result:** Agent listed all Python files, opened the custom-provider
cookbook, and quoted its docstring verbatim.

---

### 01_web_exa.py

**Status:** Not yet run (requires EXA_API_KEY not available locally)

**Description:** `WebContextProvider` with `ExaBackend`; cited web
research.

---

### 02_database_read_write.py

**Status:** PASS

**Description:** `DatabaseContextProvider` against a freshly-seeded
SQLite file. Round-trips: insert via `update_<id>`, read-back via
`query_<id>`, then verifies at the SQL level.

**Result:** Write tool inserted Grace Hopper; read tool returned
both contacts; direct SQL check confirmed the row persisted.

---

### 03_slack.py

**Status:** Not yet run (requires SLACK_BOT_TOKEN)

**Description:** `SlackContextProvider` — read-only workspace search
via a bot token.

---

### 04_google_drive.py

**Status:** Not yet run (requires GOOGLE_SERVICE_ACCOUNT_FILE)

**Description:** `GDriveContextProvider` reading via a service
account; exercises `AllDrivesGoogleDriveTools` for shared-folder
coverage.

---

### 05_multi_provider.py

**Status:** Not yet run (requires EXA_API_KEY)

**Description:** fs + web + db providers on one agent; exercises tool
composition across providers.

---

### 06_custom_provider.py

**Status:** PASS

**Description:** Subclass `ContextProvider` in-place (in-memory FAQ).
Exercises `Answer` / `Status` / `get_tools()` with minimal scaffolding.

**Result:** Agent called `query_faq` and returned the refund policy
matching the user's question.

---
