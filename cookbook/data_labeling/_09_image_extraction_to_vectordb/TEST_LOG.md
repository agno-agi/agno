# Test Log - _09_image_extraction_to_vectordb

Tested 2026-05-22 against `gemini-3.5-flash` + `gemini-embedding-001` (embedder), agno 2.6.9.

### basic.py

**Status:** PASS

**Description:** Describe three images (Krakow basilica, fjord, savanna wildlife), embed the descriptions with `GeminiEmbedder`, store in LanceDb, then run two semantic queries.

**Result:** "a historic city at night" returns the Krakow basilica as top hit; "wildlife on the savanna" returns the elephants/giraffes/zebras scene.

**Note:** Requires `lancedb` (not in the `agno[demo]` extras). Install with `uv pip install lancedb` into `.venvs/demo`. Test inputs were also swapped off Wikimedia URLs since Gemini can't fetch those.

---
