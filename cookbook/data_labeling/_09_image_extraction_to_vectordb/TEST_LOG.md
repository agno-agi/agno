# Test Log - _09_image_extraction_to_vectordb

Tested 2026-07-18 against `gemini-3.5-flash` + `gemini-embedding-001` (embedder), agno 2.7.4.

### basic.py

**Status:** PASS

**Description:** End-to-end labeling pipeline run from a clean slate (tmp/lancedb/ deleted before the run). An agent extracts a structured `ImageDescription` (subject, setting, mood, key_objects) from three image URLs (Krakow basilica, fjord, savanna wildlife), the descriptions are flattened to searchable strings, embedded with `GeminiEmbedder`, inserted into a fresh LanceDb table (`data_labeling_images`, `SearchType.vector`), and two natural-language queries are run against the index. Exercised without `tantivy` installed - vector search does not need it.

**Result:** All three extractions succeeded with well-formed structured output (e.g. Krakow: subject "St. Mary's Basilica framed by the arches of the Cloth Hall", mood "Magical and serene"; savanna: subject "A diverse group of African wildlife, including elephants, giraffes, zebras, and a crocodile, gathered at a watering hole"). 3 documents inserted. Query "a historic city at night" returned the Krakow basilica as top hit; "wildlife on the savanna" returned the elephants/giraffes/zebras scene as top hit. Each extraction took roughly 2.7-4.8s.

---
