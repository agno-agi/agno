# REVIEW_LOG

## embedders — v2.5 Review

Reviewed: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

## Framework Issues

No framework issues found — all embedder cookbooks use consistent API patterns. The `knowledge.embedder.{provider}` import paths are stable.

---

## Cookbook Quality

[QUALITY] All embedder cookbooks — Excellent consistency. Every cookbook follows the same pattern: create embedder, create Knowledge with PgVector, insert CV PDF, create Agent, ask question. Good for teaching.

[QUALITY] All embedder cookbooks — Every example uses the same CV PDF (`testing_resources/cv_1.pdf`). Good standardization but limits testing of batch/multi-doc embedding.

[QUALITY] gemini_embedder.py — Logs "Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using GOOGLE_API_KEY." when both env vars exist. This is framework behavior, not a cookbook issue, but worth documenting.

[QUALITY] cohere_embedder.py — Uses `embed-v4.0` model but `cohere` package is not in the demo venv despite having COHERE_API_KEY set.

---

## Fixes Applied

No v2.5 compatibility fixes needed.
