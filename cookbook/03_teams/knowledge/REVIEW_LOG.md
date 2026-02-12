# Review Log: knowledge

> Updated: 2026-02-11

## Framework Issues

(none found — PgVector path works correctly)

## Cookbook Quality

[QUALITY] 01/02/03_team_with_knowledge*.py — All three depend on LanceDb which is not in the demo venv. Should either install lancedb in demo_setup.sh or provide PgVector alternatives.

[QUALITY] 04_team_with_custom_retriever.py — Good example of dependency injection via RunContext. Re-embeds on every run (no skip_if_exists), making it very slow (~100s). Should add `skip_if_exists=True` to `knowledge.insert()`.

[QUALITY] 02_team_with_knowledge_filters.py — Uses `insert_many()` with list of dicts containing path + metadata. Good pattern for batch ingestion with metadata.

## Fixes Applied

(none — failures are missing dependency, not v2.5 issues)
