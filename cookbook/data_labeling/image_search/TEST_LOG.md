# Test Log - image_search

Tested 2026-07-18 against gemini-3.5-flash + gemini-embedding-001 (embedder), agno 2.7.4.

### run.py (server + endpoints)

**Status:** PASS

**Description:** Starts the AgentOS server app (run.py, wiring db.py, schemas.py, settings.py, workflows/ingest.py) against the local pgvector on port 5532 and exercises the HTTP surface: the explicit /ui route, the native /knowledge/content gallery endpoint, and the native workflow-run endpoints. Note: the demo venv does not ship the `fastapi` CLI (`fastapi[standard]`), so the server was started with the equivalent `python -m uvicorn run:app --app-dir cookbook/data_labeling/image_search --port 7777`.

**Result:** Server started cleanly ("Application startup complete", port 7777). GET /ui returned 200 with the index.html document (doctype + Tailwind/Alpine CDN head visible). GET /knowledge/content returned the paginated envelope `{data, meta}` with `meta.total_count: 0` on the empty index before ingest and `meta.total_count: 38` after ingest. POST /workflows/image-ingest/runs requires the form field `message` (422 "Field required" without it) and defaults to `stream=true`, so a background run that should return 202 metadata immediately needs `background=true&stream=false`; with those it returned `{"run_id": "78ac80c2-...", "session_id": "8d1d5ddf-...", "status": "PENDING"}` at once.

---

### run.py (ingest workflow)

**Status:** PASS

**Description:** Triggers the image-ingest workflow (full wipe + re-ingest of the 38 built-in Picsum URLs at INGEST_CONCURRENCY=3: httpx fetch, gemini-3.5-flash structured ImageDescription extraction, gemini-embedding-001 embed, PgVector upsert) via POST /workflows/image-ingest/runs with background=true and stream=false, then polls GET /workflows/image-ingest/runs/{run_id}?session_id={session_id} until terminal status.

**Result:** Run completed with status COMPLETED and final summary content `{'total': 38, 'failed': 0, 'indexed': 38}` in well under a minute. Server log showed 38 "Upserted batch of 1 documents" lines for the run (76 cumulative across the two runs performed today, confirming the wipe + full re-ingest behavior), and /knowledge/content reported `total_count: 38` afterward. Per-image Gemini extraction calls ran at roughly 4s each (e.g. one logged call: input=1401 tokens, output=240, duration 3.88s). No failed URLs, no "agent returned str" structured-output corruption.

---

### run.py (search quality)

**Status:** PASS

**Description:** Exercises POST /knowledge/search (hybrid PgVector search: cosine similarity over GeminiEmbedder vectors fused with Postgres FTS, prefix_match=True) against the freshly built 38-image index using four probe queries: animal, mountain, coffee, and the nonsense token asdf. Scores read from `meta_data.similarity_score` on each hit.

**Result:** All four queries behaved as designed. "animal" top hits: tiger cub 0.602, English Bulldog 0.600, leopard on savanna road 0.594. "mountain" top hits: mountain valley under overcast sky 0.695, mountain lake at sunset 0.690, Mount Everest peaks 0.683. "coffee": roasted coffee beans macro 0.710 as a clear bullseye, with the laptop-in-cafe image second at 0.523 and the tea cup demoted to 0.276. "asdf" returned only vector noise, all scores 0.217-0.227 - below the UI's 0.30 score floor, so it would correctly land in the below-threshold tray. Full ImageDescription metadata (caption, subjects, scene, visual_style, tags) round-tripped on every hit as native JSON.

---
