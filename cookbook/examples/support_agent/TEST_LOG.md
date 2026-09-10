# Test Log - support_agent

Tested 2026-09-10. Published dependency: Agno 3.0.8, clean per-example uv environment,
Python 3.12.8. Source: Agno 3.0.9 at
`37fc4121e3cf8863a2957b838fbad7c920bffe0f`, selected explicitly with PYTHONPATH.
Live model: `openai:gpt-5.6`. All runtime data used isolated temporary directories.

### test_contracts.py

**Status:** PASS

**Description:** Scripted model drives actual Agno knowledge retrieval, reference recording, follow-up history, and structured handoff. Three persisted runs survive a new database instance.

**Result:** 1 passed on published package and 1 passed on exact local source.
Deterministic checks use real Agno persistence and APIs; scripted responses do not
evaluate model judgment. Second Brain's explicit correction test does not test the
model-assisted supersession judge; that was exercised by the live demo.

---

### demo.py and restart checks

**Status:** PASS

**Description:** Bounded live-model smoke using exact local source.

**Result:** Three live turns produced an exports answer with a source, a member-permissions follow-up, and a needs_human response for the Germany contractual guarantee. The handoff was saved locally; nobody was contacted.
Model prose is paraphrased here. See the collection validation report for limits.

---

### support_agent.py startup

**Status:** PASS

**Description:** Documented uv entry point from a clean copied example directory.

**Result:** AgentOS /health returned HTTP 200 on a temporary loopback port using
both published package and local source. All server processes were stopped.
This is a local startup check, not a hosted integration check.

---

### demo.py --fixture

**Status:** PASS

**Description:** Completely offline scripted model with real Agent execution.

**Result:** Exit 0 from clean directories against published package and source.
Structured artifacts and provenance checks passed. This does not prove live model
or retrieval quality.

---
