# Review Log: metrics

> Updated: 2026-02-11

## Framework Issues

(none found)

## Cookbook Quality

[QUALITY] 01_team_metrics.py — Uses `o3-mini` model which includes reasoning tokens; good for demonstrating that metric. Clear separation of four metric levels (message, team, session, member). Good teaching example.

## Fixes Applied

[COMPAT] 01_team_metrics.py:10,23-30 — Removed `from agno.db.surrealdb import SurrealDb` import and SurrealDb configuration block (lines 23-30) that overwrote the PostgresDb `db` variable. SurrealDb package not installed in demo venv. PostgresDb was already configured correctly on line 21.
