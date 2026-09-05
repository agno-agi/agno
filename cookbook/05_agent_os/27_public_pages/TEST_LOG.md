# Public pages test log

### public_pages.py

**Status:** PASS

**Description:** Fresh validation on 2026-09-05 after narrowing the migration. Used the owned `.venvs/demo` environment, PostgreSQL 18.1/pgvector, real `text-embedding-3-small` embeddings and `gpt-5.6-luna` responses. Discovery was explicitly limited to one real public page, `https://docs.agno.com/agents/overview.md`; fetch, publication, query embeddings, streamed model responses, HTTP and MCP followed the real implementations.

**Result:** Setup/sync/read/grep, explicit pre-hook chat, HTTP SSE with follow-up completion, selected Agent listing, readiness/CORS, explicit MCP card URL, actual MCPTools search, anonymous sync rejection, and authenticated durable background sync/status polling passed. Background refresh returned unchanged. The isolated database was dropped. No full-site sync or deployment was performed.

**Validation scope:** The current example uses explicit instructions/pre-hook/tools and existing URL configuration. Product recording-model tests independently check prompt, multi-turn/tool-loop evidence and follow-up suggestions. Earlier automatic-reference/Team/derived-URL example results are preserved separately and do not validate this example.

---
