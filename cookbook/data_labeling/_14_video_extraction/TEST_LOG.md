# Test Log - _14_video_extraction

Tested 2026-05-19 against `gemini-3.5-flash` (Gemini), agno 2.6.8.

### action_timestamps.py

**Status:** PASS

**Description:** Extract a list of `Event`s with action descriptions and `[start, end]` second timestamps.

**Result:** Three events returned with monotonically increasing timestamps.

---

### basic.py

**Status:** PASS

**Description:** Extract a `VideoSummary` (overall summary, dominant subject, scenes list).

**Result:** Two-sentence summary plus three scene phrases; matches what's on screen.

---

### scene_descriptions.py

**Status:** PASS

**Description:** Extract a list of `Scene` objects with name, description, and visible objects.

**Result:** One scene returned with detailed description and visible objects list.

---
