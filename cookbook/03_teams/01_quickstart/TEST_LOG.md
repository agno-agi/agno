# Test Log: 01_quickstart

> Updated: 2026-02-11

### 01_basic_coordination.py

**Status:** FAIL (timeout)

**Description:** Demonstrates basic sync+async team coordination with tool delegation. Uses HackerNewsTools, Newspaper4kTools, and WebSearchTools across agents with different models (gpt-5.2, o3-mini, o3).

**Result:** Timed out at 180s. The team coordination and HN story retrieval work correctly, but the Article Reader agent uses Newspaper4kTools to fetch external URLs which are slow/broken (SSL cert expired on zhipu.ai, 404s on alternate URLs). Team coordination logic is sound — timeout is caused by tool execution, not framework.

---

### 02_respond_directly_router_team.py

**Status:** PASS

**Description:** Demonstrates language routing with `respond_directly=True`. Router team delegates to language-specific agents (English, Spanish, Japanese, French, German) and returns member responses directly. Tests 4 languages + unsupported language fallback.

**Result:** All 4 language queries routed correctly. German response correct. Italian (unsupported) correctly returned fallback message. Duration ~32s.

---

### 03_delegate_to_all_members.py

**Status:** PASS

**Description:** Demonstrates collaborative execution with `delegate_to_all_members=True`. All members participate in discussion, team orchestrates consensus response.

**Result:** Completed successfully in ~60s. All members contributed to comprehensive coding learning advice. Team synthesized a coherent collaborative response.

---

### 04_respond_directly_with_history.py

**Status:** PASS

**Description:** Demonstrates `respond_directly=True` with SQLite history persistence via SqliteDb. Uses `add_history_to_context=True` for context-aware responses.

**Result:** Completed successfully. Multi-turn history maintained across requests. Second query correctly referenced prior context. SQLite NameError at `sqlite.py:998` logged during session upsert but did not block execution.

---

### 05_team_history.py

**Status:** PASS

**Description:** Demonstrates shared team history via `add_team_history_to_members=True` with SqliteDb persistence. Multi-turn conversation across language agents.

**Result:** Completed successfully. Team history shared with all members. Second request built on prior context. SQLite NameError logged during session upsert.

---

### 06_history_of_members.py

**Status:** PASS

**Description:** Demonstrates per-member history with `add_history_to_context=True` set on individual agents. Each member maintains independent history via SqliteDb.

**Result:** Completed successfully. Member-level history maintained independently. SQLite NameError logged during session upsert.

---

### 07_share_member_interactions.py

**Status:** PASS

**Description:** Demonstrates `share_member_interactions=True` so the team sees what members did during current run. Technical support team use case with function tools.

**Result:** Completed successfully. Team coordinator saw member execution details and synthesized a support response. SQLite NameError logged during session upsert.

---

### 08_concurrent_member_agents.py

**Status:** PASS

**Description:** Demonstrates async streaming with `stream_member_events=True` for real-time event streaming (tool calls, completions) with timing. Uses HackerNewsTools and WebSearchTools concurrently.

**Result:** Completed successfully in ~76s. Concurrent member execution with real-time event streaming. Both agents ran tools in parallel. Total execution time reported.

---

### broadcast_mode.py

**Status:** PASS

**Description:** Demonstrates `TeamMode.broadcast` where all members receive the same task for independent parallel evaluation. PM, Engineer, and Designer agents each evaluate an autopilot feature.

**Result:** Completed successfully within 180s timeout. All 3 members provided independent evaluations. Team synthesized perspectives into comprehensive recommendation.

---

### nested_teams.py

**Status:** PASS

**Description:** Demonstrates teams as members of a parent team (2-level nesting). Research Team feeds into Writing Team for AI coding tool adoption analysis.

**Result:** Completed successfully within 180s timeout. Prior run (2026-02-08) timed out — this run completed. Nested team coordination worked correctly with hierarchical execution.

---

### task_mode.py

**Status:** PASS

**Description:** Demonstrates `TeamMode.tasks` for autonomous task decomposition with dependencies. Team decomposes AI feature deployment into subtasks and executes them.

**Result:** Completed successfully within 180s timeout. Task decomposition, dependency resolution, and sequential execution all worked. Produced comprehensive deployment checklist with rollback procedures.

---

### caching/cache_team_response.py

**Status:** PASS

**Description:** Demonstrates model-level response caching with `cache_response=True` on OpenAIChat. Reduces cost/latency on repeated queries.

**Result:** Completed successfully in ~1s. Cached response returned immediately on second call.

---
