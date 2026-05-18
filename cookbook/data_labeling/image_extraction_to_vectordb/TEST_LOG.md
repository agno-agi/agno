# Test Log - image_extraction_to_vectordb

Tested 2026-05-17 against `gpt-5.5` (OpenAIResponses) + `text-embedding-3-small`, agno 2.6.6.

### basic.py

**Status:** PASS

**Description:** Describe three images, embed the descriptions, store in LanceDb, then run two semantic queries.

**Result:** "a famous landmark" returns Golden Gate and Eiffel; "a sleeping pet" returns the cat as top hit.

**Note:** Requires `lancedb` (not in the `agno[demo]` extras). Install with `uv pip install lancedb` into `.venvs/demo`. Worth either adding to the demo extras or shipping a `requirements.in` for this folder.

---
