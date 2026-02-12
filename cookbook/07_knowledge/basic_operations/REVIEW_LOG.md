# REVIEW_LOG

## basic_operations — v2.5 Review

Reviewed: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

## Framework Issues

[FRAMEWORK] knowledge/knowledge.py — `isolate_vector_search` parameter removed entirely. No replacement API visible in Knowledge class. The `linked_to` metadata concept appears gone.

---

## Cookbook Quality

[QUALITY] async/04_from_multiple.py — Good async example. Agent creation is sync after async work, order could confuse beginners.

[QUALITY] async/05_isolate_vector_search.py — Excellent documentation about backwards compatibility and multi-tenancy. Feature appears removed in v2.5 with no replacement.

---

## Fixes Applied

[COMPAT] async/05_isolate_vector_search.py — BROKEN. `isolate_vector_search` parameter removed from Knowledge. No trivial fix available — feature was removed.
