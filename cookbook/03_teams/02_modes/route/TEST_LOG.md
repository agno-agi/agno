# Test Log: cookbook/03_teams/02_modes/route


### 01_basic.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### 02_specialist_router.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### 03_with_fallback.py

**Status:** FAIL

**Description:** Validation issue: style

**Result:** Style: missing_docstring_underline | Run: completed

---

### 04_jev_router.py

**Status:** PASS

**Description:** Route-mode team led by `Jev(min_confidence=0.5, fallback_member="general")` with four OpenAI members; prints the chosen member, confidence and the probability of every option for four requests. Run with `.venv/Scripts/python.exe` (Windows, Python 3.12, typesafe-sdk 0.7.0), live TypeSafe and OpenAI APIs, 2026-09-21.

**Result:** All four requests reached the intended member: duplicate charge -> billing, late package -> orders (1.0), checkout 500 error -> tech-support (0.99), home-office tips -> general (1.0). The member reply was returned as written with nothing prepended, after a single Jev request per run. The team instructions were applied as routing guidance.

---
