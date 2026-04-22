# Context Cookbook Test Log

## 2026-04-22

### 00_minimal_provider.py

**Status:** Not yet run (requires OPENAI_API_KEY)

**Description:** In-place `ContextProvider` subclass over an in-memory
dict of quotes. Exercises `Answer`/`Status`/`get_tools()`.

---

### 01_filesystem.py

**Status:** Not yet run (requires OPENAI_API_KEY)

**Description:** `FilesystemContextProvider` rooted at the cookbook
directory; agent lists + reads files.

---

### 02_web_exa.py

**Status:** Not yet run (requires OPENAI_API_KEY + EXA_API_KEY)

**Description:** `WebContextProvider` with `ExaBackend`; cited web
research.

---

### 03_database_read_write.py

**Status:** Not yet run (requires OPENAI_API_KEY)

**Description:** `DatabaseContextProvider` against a freshly-seeded
SQLite file. Round-trips: insert via `update_<id>`, read-back via
`query_<id>`, then verifies at the SQL level.

---

### 04_mcp_server.py

**Status:** Not yet run (requires OPENAI_API_KEY)

**Description:** `MCPContextProvider` against Exa's keyless MCP
server. Exercises lazy connect, dynamic tool-description instructions,
and `aclose()`.

---

### 05_multi_provider.py

**Status:** Not yet run (requires OPENAI_API_KEY + EXA_API_KEY)

**Description:** fs + web + db providers on one agent; exercises tool
composition across providers.

---
