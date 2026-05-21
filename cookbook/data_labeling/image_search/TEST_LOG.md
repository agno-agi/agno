# TEST_LOG — image_search

## Run env

- Tested 2026-05-21 against `gemini-3.5-flash` (vision + structured output)
  and `gemini-embedding-001` (embeddings), agno 2.6.8.
- Vector DB: ChromaDb local (`persistent_client=True`, `data/chroma/`).
- Contents DB: SqliteDb (single file, shared by Knowledge + Workflow).
- Run command: `fastapi dev cookbook/data_labeling/image_search/run.py --port 7777`.

---

### Knowledge plumbing roundtrip

**Status:** PASS

**Description:** 3 hand-typed `ImageDescription` fixtures roundtripped
through `Knowledge.insert(text_content=..., metadata=...)`, `get_content()`,
`search()`, and re-insert with `skip_if_exists=True`.

**Result:**

- `insert(text_content=..., metadata=...)` round-trips through both
  contents_db and vector_db on the same call. Synchronous — search hits
  return immediately, status=COMPLETED on return.
- No chunking for ~150-char descriptions — 1 chunk per fixture.
- Idempotent: re-insert with `skip_if_exists=True` leaves the count alone.
- ChromaDb persistent_client survives process restarts.

---

### AgentOS endpoints

**Status:** PASS

- `GET /ui` → 200 with index.html.
  - Note: `StaticFiles(html=True)` mounted at `/ui` redirect-loops because
    AgentOS's `TrailingSlashMiddleware` strips the slash StaticFiles uses
    for index-resolution. Resolved by registering an explicit
    `@base_app.get("/ui")` returning `FileResponse`.
- `GET /knowledge/content` → paginated list with `metadata` per item.
- `POST /knowledge/search` → vector hits with `meta_data` carrying the
  full ImageDescription.
- `POST /workflows/image-ingest/runs` (form-encoded, background=true) →
  run_id + session_id.
- `GET /workflows/image-ingest/runs/{id}?session_id=...` → status
  progression + the final indexed/skipped/failed/total summary.

**Port gotcha:** `fastapi dev` defaults to port 8000. Docker Desktop's
webview also binds 8000 with a wildcard listener that silently returns
stale JSON to local curl. We run on 7777 to dodge that. README documents
the flag.

---

### End-to-end parallel ingest

**Status:** PASS (after two fixes)

**Description:** Triggered the ingest workflow against the 38 Picsum URLs
with `INGEST_CONCURRENCY=8`.

**Result:** all 38 indexed in ~10s.

**Fix 1 — image fetch:** initial impl passed `Image(url=picsum_url)` to
the agent. Picsum redirects via 302 to signed Fastly URLs and Gemini's URL
fetcher handles redirects inconsistently — most URLs returned `400
INVALID_ARGUMENT`. Solved by fetching bytes locally with `httpx` and
passing `Image(content=...)`. Works for any public URL, including the
future S3 path.

**Fix 2 — agent thread-safety:** initial impl shared one `Agent` instance
across the ThreadPoolExecutor. Under concurrency=8, ~63% of calls
returned a string instead of an `ImageDescription` — the agent's
structured-output parsing has per-run state that isn't thread-safe.
Solved by constructing a fresh `Agent` inside `_ingest_one` for each
worker. Object construction is cheap; the underlying Gemini client is
shared via the model. After fix: 38/38 clean.

---

### Search quality with the search-tuned schema

**Status:** PASS

Spot-checked against the live index:

| Query                  | Top hit                                                              |
|------------------------|----------------------------------------------------------------------|
| `mountains and lakes`  | "A dense green evergreen forest overlooking a wide blue lake..."     |
| `cozy indoor scene`    | "A steaming teacup and an open book..."                              |
| `abstract patterns`    | "Wavy sandstone formations of a slot canyon..."                      |
| `wildlife on savanna`  | (no result — no wildlife in the 38-image Picsum set)                 |

The five-field schema (caption + subjects + scene + visual_style + tags)
gives noticeably stronger signal than the previous four (subject /
setting / mood / key_objects). The caption alone tends to dominate, but
the tag list catches near-misses (e.g. "outdoors" / "wilderness" surfacing
nature shots that don't match the literal query).

---

### UI

**Status:** PASS

Static preview renders. Live API wiring verified via curl path-equivalence
(`fetch()` from index.html issues identical requests). Cards render
caption, subjects line, scene, visual style, and up to 6 tag chips.

Open <http://localhost:7777/ui>. First load is empty — click Reindex,
counter ticks up live, gallery and search populate on completion.

---

### UI rewrite — Alpine + Lucide + PhotoSwipe (post-test addendum)

**Status:** Static rendering verified; interactive smoke pending.

The UI was rewritten after the section above to swap the imperative
vanilla JS for Alpine.js (declarative state via `x-data`), add Lucide
icons to the Reindex (spinning when active) and Search buttons, and wire
PhotoSwipe lightboxes to both `#search-grid` and `#gallery-grid`. All CDN,
no build step.

Fetch URLs and field mappings are unchanged, so the curl-equivalence
verification above still applies. Interactive features (lightbox click,
reindex polling, tab switching) should be re-smoked against a live server
before relying on them.
