# Test Log: metrics

> Updated: 2026-02-12

### 01_team_metrics.py

**Status:** PASS

**Description:** Team metrics aggregation — creates a stock research team with YFinanceTools, runs a query, then prints leader message metrics, aggregated team metrics, session metrics, and member metrics.

**Result:** After fixing SurrealDb import (see REVIEW_LOG.md), ran successfully. All four metric levels displayed correctly: per-message metrics (input/output tokens, reasoning tokens, TTFT, duration), aggregated team metrics, session metrics via `team.get_session_metrics()`, and member-level metrics from `run_output.member_responses`.

---
