# Public pages test log

### public_pages.py

**Status:** PASS

**Description:** Executed on 2026-09-05 in the isolated `.venvs/demo` environment with candidate Agno 3.0.6, PostgreSQL 18.1/pgvector, real OpenAI `text-embedding-3-small` embeddings and `gpt-5.6-luna` responses. A validation driver bounded discovery to one real page (`https://docs.agno.com/agents/overview.md`). HTTPS fetch, page preparation, catalog/filesystem/vector commit, query embeddings, streamed answers, and HTTP/MCP were real; the one-page discovery selection was injected.

**Result:** Sync/search/read/grep passed; direct streamed chat and HTTP SSE chat passed; selected Agent/Team lists and hidden member behavior passed; readiness, CORS, derived MCP Card URL and an actual MCPTools connection/call passed. Anonymous workflow trigger returned 401. The isolated database was dropped. No full-site live sync or deployment was performed. Full reader discovery and protected workflow/scheduler execution are covered by fixture and real PostgreSQL/HTTP integration tests.

**Observation:** The first attempt caught an unsupported embedder constructor argument before provider calls. Corrected to `client_params` and reran successfully. The current configured product staging index returns 404, so this bounded live example used the available public documentation host instead.

---
