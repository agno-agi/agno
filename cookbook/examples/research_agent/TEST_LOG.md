# Test Log - research_agent

Tested 2026-09-10. Published dependency: Agno 3.0.8, clean per-example uv environment,
Python 3.12.8. Source: Agno 3.0.9 at
`37fc4121e3cf8863a2957b838fbad7c920bffe0f`, selected explicitly with PYTHONPATH.
Live model: `openai:gpt-5.6`. All runtime data used isolated temporary directories.

### test_contracts.py

**Status:** PASS

**Description:** Scripted model drives the actual search/read tools. Citation URLs equal inspected URLs; results survive session storage; reading an undiscovered URL fails.

**Result:** 1 passed on published package and 1 passed on exact local source.
Deterministic checks use real Agno persistence and APIs; scripted responses do not
evaluate model judgment. Second Brain's explicit correction test does not test the
model-assisted supersession judge; that was exercised by the live demo.

---

### demo.py and restart checks

**Status:** PASS

**Description:** Bounded live-model smoke using exact local source.

**Result:** Live model over explicitly fictional fixtures inspected both source URLs and saved a brief with findings, disagreement about monthly versus quarterly frequency, uncertainty, and open questions. This does not establish live retrieval quality.
Model prose is paraphrased here. See the collection validation report for limits.

---

### research_agent.py startup

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

### RESEARCH_MODE=live demo.py

**Status:** PASS

**Description:** One bounded live-model run with real DDGS search and WebsiteTools
page reads on exact local source.

**Result:** Saved six findings citing three successfully inspected pages (Share
Oxford, Welsh Government, Miller Research). Several candidate pages returned 403;
accessible alternatives were used and failed reads were not cited. Citation-set
validation passed. This single smoke does not prove general retrieval reliability
or claim-by-claim citation entailment.

---
