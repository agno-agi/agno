# Test Log: metrics

> Updated: 2026-02-14

### 01_team_metrics.py

**Status:** FAIL (pre-existing model issue)

**Description:** Team metrics aggregation — creates a stock research team with YFinanceTools, runs a query, then prints leader message metrics, aggregated team metrics, session metrics, and member metrics.

**Result:** SurrealDb import fixed (removed unused import). However, fails with `gpt-5.2-mini` model not found error. This is a pre-existing issue from V2.5 phase5 rebase — the model ID was already wrong before this PR's changes. The PR's fix (removing SurrealDb import) is correct and verified via import check.
**Re-verified:** 2026-02-14 — SurrealDb import removal confirmed. Model ID `gpt-5.2-mini` needs separate fix.

---
