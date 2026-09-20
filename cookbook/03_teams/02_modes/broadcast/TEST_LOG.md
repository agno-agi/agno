# Test Log: cookbook/03_teams/02_modes/broadcast


### 01_basic.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### 02_debate.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### 03_research_sweep.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### 05_jev_panel_judge.py

**Status:** PASS

**Description:** Broadcast team led by Jev with three OpenAI reviewers and a `Verdict` output_schema (Literal, two bools, IntEnum score). Run with `.venv/Scripts/python.exe` (Windows, Python 3.12, typesafe-sdk 0.7.0), live TypeSafe and OpenAI APIs, 2026-09-21.

**Result:** All three members answered the proposal. Jev returned `recommendation=trial` (confidence 1.0), `panel_agrees` 0.93, `risk_raised` 0.94 and `case_strength=strong`. The broadcast turn made no Jev request; the judging turn made one.

---
