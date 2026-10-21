### 06_search_error_handling.py

**Status:** PASS

**Description:** Ran with an in-memory Qdrant collection and a deliberately failing
embedder, without API credentials or external services.

**Result:** Default search returned `[]`. With `raise_on_search_error=True`, sync
and async callers caught `EmbeddingError`; the agent search tool returned
`Error searching knowledge base: EmbeddingError`. Local Qdrant emitted its expected
warning that payload indexes have no effect in local mode.

---
