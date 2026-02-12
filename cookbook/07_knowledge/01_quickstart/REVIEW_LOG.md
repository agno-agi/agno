# REVIEW_LOG

## 01_quickstart — v2.5 Review

Reviewed: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

## Framework Issues

[FRAMEWORK] knowledge/knowledge.py:1560 + reader/youtube_reader.py:78 — Async URL ingestion calls `reader.read()` (sync) instead of `reader.async_read()` for YouTubeReader. The async path falls back to sync reading, which works but defeats the purpose of async.

[FRAMEWORK] knowledge/knowledge.py:1553, :1700 — URL ingestion error handling: if `httpx.get()` or `fetch_with_retry()` fails, the exception propagates unhandled rather than setting `content.status = FAILED`.

[FRAMEWORK] knowledge/knowledge.py:1526, :1673 — Invalid URL format (no scheme, malformed) will raise an unhandled exception from `urlparse()`. No validation before attempting to parse.

[FRAMEWORK] vectordb/pgvector/pgvector.py:1402 (and :1418, :1434, :1450, :1466) — `sess.rollback()` called outside `with` block in delete methods. If the session context manager exits on exception, `sess` is already closed and rollback fails with a secondary error.

[FRAMEWORK] knowledge/knowledge.py:521, :560 — Knowledge isolation (`isolate_vector_search=True`) adds `linked_to` filter at search time, but existing vectors inserted before isolation was enabled won't have this metadata, causing them to be invisible. Not a bug per se, but a silent data loss scenario that should be documented.

---

## Cookbook Quality

[QUALITY] 01_from_path.py — Good basic flow. Sync/async differ in contents_db usage (sync has it, async doesn't), which is confusing for a quickstart.

[QUALITY] 02_from_url.py — Cleanup removes vectors only; contents rows left behind when contents_db is configured. Could mislead users about cleanup completeness.

[QUALITY] 03_from_topic.py — Good topic-reader coverage. Should mention arxiv dependency requirement upfront.

[QUALITY] 04_from_multiple.py — Useful overload demo. Sync/async use different model/embedder configs, making comparison harder than necessary for a teaching example.

[QUALITY] 05_from_youtube.py — Works but doesn't explicitly set YouTubeReader, relying on auto-detection. More explicit for a quickstart.

[QUALITY] 06_from_s3.py — Good remote-content shape. Missing prerequisites section (auth, deps).

[QUALITY] 07_from_gcs.py — Same as S3 issue. Hardcoded bucket name not runnable.

[QUALITY] 08_include_exclude_files.py — Solid include/exclude demo. Agent prompts are subjective.

[QUALITY] 09_remove_content.py — Demonstrates APIs well but doesn't validate return values.

[QUALITY] 10_remove_vectors.py — Demonstrates remove APIs but ignores boolean return values.

[QUALITY] 12_skip_if_exists_contentsdb.py — Useful pattern but content name "CV" used for Thai recipes is confusing.

[QUALITY] 16_knowledge_instructions.py — Missing async variant, only shows sync example.

---

## Fixes Applied

No v2.5 compatibility fixes needed — all cookbooks use current import paths and APIs.
