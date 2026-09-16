# Test Log - team_brain

## Python 3.14 requirements setup — 2026-09-16

**Status:** PASS

Installed `requirements.txt` in a fresh Python 3.14.5 environment, with pytest
installed separately. The existing contract suite passed on both published Agno
3.0.8 and source Agno 3.0.9 at `37fc4121e3cf8863a2957b838fbad7c920bffe0f`.
AgentOS startup and /health passed in both environments. The two-brain HTTP/MCP
suite also passed on both implementations; Research and Support's offline fixture
demos completed on both. No live-model rerun was needed for these unchanged agents.
Personal Agent's code and three prompts were rechecked against the current tutorial.

The older results below describe the original September 10 dependency setup.

Tested 2026-09-10. Published dependency: Agno 3.0.8, clean per-example uv environment,
Python 3.12.8. Source: Agno 3.0.9 at
`37fc4121e3cf8863a2957b838fbad7c920bffe0f`, selected explicitly with PYTHONPATH.
Live model: `openai:gpt-5.6`. All runtime data used isolated temporary directories.

### test_contracts.py

**Status:** PASS

**Description:** Missing local identity is refused. Two JSON records preserve Alice/Bob attribution through storage restart, even when a decision embeds a forged author string. Librarian tools cannot write.

**Result:** 1 passed on published package and 1 passed on exact local source.
Deterministic checks use real Agno persistence and APIs; scripted responses do not
evaluate model judgment. Second Brain's explicit correction test does not test the
model-assisted supersession judge; that was exercised by the live demo.

---

### demo.py and restart checks

**Status:** PASS

**Description:** Bounded live-model smoke using exact local source.

**Result:** Alice and Bob contributed two decisions; the live librarian read `decisions.jsonl` and correctly returned both decisions, reasons, and authors. Separate-process recall preserved both.
Model prose is paraphrased here. See the collection validation report for limits.

---

### team_brain.py startup

**Status:** PASS

**Description:** Documented uv entry point from a clean copied example directory.

**Result:** AgentOS /health returned HTTP 200 on a temporary loopback port using
both published package and local source. All server processes were stopped.
This is a local startup check, not a hosted integration check.

---

### ../test_mcp.py

**Status:** PASS

**Description:** Full local HTTP/ASGI stack, real generated RSA keys and signed
JWTs, MCP initialize/list/call, hidden identity schema, two verified users, rejected
spoofed user IDs, and missing/invalid credential rejection.

**Result:** The two-example suite passed 2 tests on each implementation. Team Brain
writes use the actual FileSystem; the model-facing arun boundary is stubbed for
transport checks. Separate live demos exercise the real agent. No hosted OAuth
provider or external MCP client account was connected.

---
