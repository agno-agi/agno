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

---

### PgVector swap (2026-05-22)

**Status:** PASS

The cookbook was migrated from `ChromaDb` + `SqliteDb` to `PgVector` +
`PostgresDb` against `agnohq/pgvector:18` (the image
`cookbook/scripts/run_pgvector.sh` brings up on port 5532). The swap
deletes two client-side workarounds that were papering over storage-layer
weirdness in the previous stack:

- `asArray()` in [`public/index.html`](public/index.html): pgvector
  preserves JSONB arrays as native arrays in both
  `/knowledge/content.metadata` and `/knowledge/search.meta_data`. No
  more string ↔ array reconciliation.
- The frontend "trust real keyword hits, not substring noise" heuristic
  is no longer needed. PgVector's keyword branch runs
  `to_tsvector(english, content)` + `websearch_to_tsquery(english,
  query)`, so `car` no longer false-matches `carnivore` or `streetcar` —
  the English Snowball stemmer lemmatizes both query and document into
  lexemes (`car`, `cars` → `car`; `carnivore` → `carnivor`).

**Reindex:** 38/38 indexed in ~10s. No "agent returned str" issues
recurred (the per-worker Agent construction from Fix 2 still applies).

**Query battery** — `MIN_SCORE_RATIO=0.5`, `SCORE_FLOOR=0.30`. PgVector's
hybrid score = `0.5 * cosine_similarity + 0.5 * ts_rank`. A pure vector
match tops out at ~0.5; anything above that is FTS-boosted.

| Query        | Best   | Shown | Below | Verdict                                              |
|--------------|--------|-------|-------|------------------------------------------------------|
| `animal`     | 0.525  | 5     | 7     | bulldog, leopard, bear, coyote, highland cow         |
| `anim`       | 0.488  | 6     | 6     | same set as `animal`, stemmer makes them equivalent  |
| `anima`      | 0.243  | 0     | 12    | tsquery `anima` ≠ lexeme `anim` — tucked under tray  |
| `wildlife`   | 0.532  | 5     | 7     | coyote, bear, leopard, tiger cub, pelican            |
| `mountain`   | 0.696  | 8     | 4     | valleys, peaks, lakes — all mountain scenes          |
| `coffee`     | 0.710  | 1     | 11    | just the macro beans — laptop-in-cafe correctly demoted to 0.27 |
| `car`        | 0.240  | 0     | 12    | no FTS hits — leopard `carnivore` is gone (stemmer)  |
| `night city` | 0.259  | 0     | 12    | vector-only candidates (Milan dusk, NYC) shown via tray |
| `asdf`       | 0.223  | 0     | 12    | correctly tucked under tray                          |

**Observations:**

- `SCORE_FLOOR = 0.30` cleanly separates "real FTS match" (scores >0.45)
  from "vector noise" (scores 0.20–0.27). The relative cutoff
  (`best * MIN_SCORE_RATIO`) only kicks in inside the strong-match tier,
  so `coffee` correctly returns one bullseye instead of dragging in the
  laptop-in-cafe image.
- Search-as-you-type has a quirk: `anim` matches because the lexeme is
  `anim`, but `anima` doesn't because the stemmer treats it as a
  different word. The 250ms debounce + AbortController + tray-fallback
  UX (`Show 12 below threshold`) gives an honest "no high-confidence
  match" experience instead of pretending.
- `prefix_match=True` was tried and reverted: it appends `*` to query
  terms, but agno passes the query through `websearch_to_tsquery`, which
  doesn't honor `:*` / `*` operators — it's a silent no-op.

**Endpoints:** unchanged surface — `/knowledge/content`,
`/knowledge/search`, `/workflows/image-ingest/runs` all behave the same
shape-wise. Just the underlying storage moved.
