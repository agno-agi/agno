# Test Log - Product Agent

Tested 2026-09-16 using Python 3.14.5. Published runtime: Agno 3.0.8, OpenAI
3.14.1, ChromaDB 1.5.9. Source runtime: Agno 3.0.9 at
`37fc4121e3cf8863a2957b838fbad7c920bffe0f` selected explicitly with PYTHONPATH.
All data used temporary directories. The docs checkout was read-only.

Source: the live working `content/docs/use-cases/agents-as-api.mdx` draft,
SHA-256 `e0229208640880640037525263256061bccceeb5e93f12f43124c61d89d12aa6`.
The agent configuration and sample document come from this guide. The cookbook
normalizes the unfinished rename to `product_agent.py`, `product_agent`,
`product-agent`, and `Product Agent`, including loader imports and HTTP routes.
It adds cookbook section comments, a main guard for loading, and an HTTP demo.

### requirements.txt and product_agent.py

**Status:** PASS

**Description:** Fresh Python 3.14 environment, requirements installation, imports,
AgentOS startup and health request.

**Result:** Installation succeeded. /health returned HTTP 200 on both published
and source implementations. No embedding/model call occurs at startup.

---

### test_contracts.py

**Status:** PASS

**Description:** Real ChromaDB hybrid indexing/search, SQLite content/session
persistence, and AgentOS HTTP routes; deterministic embedder and scripted model.

**Result:** 2 passed on published and 2 passed on source. Reopened index retrieved
stored content; reloading an edited document replaced the old plan name. HTTP
follow-ups retained history, and both runs persisted retrieved references and the
same session ID. These checks establish contracts, not embedding or model quality.
Third-party ChromaDB/Starlette deprecation warnings did not affect execution.

---

### load_knowledge.py, demo.py, and server restart

**Status:** PASS

**Description:** One bounded live run on exact source using the existing test
OpenAI key, real embeddings and model responses, and a temporary data directory.

**Result:** The loader indexed Acme Reports. The actual demo made two HTTP calls
in one session, correctly identifying weekly scheduling, the Team plan, and admin
permissions. Its third call streamed CSV export guidance with source references
and a RunCompleted event. After stopping and restarting the server, another HTTP
follow-up with the same session correctly retained the plan and permissions.
The service was stopped afterward. No hosted integration or deployment was tested.

---
