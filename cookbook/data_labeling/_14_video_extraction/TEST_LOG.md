# Test Log - _14_video_extraction

Tested 2026-05-17 against `gemini-3-flash-preview` (Gemini), agno 2.6.6. Input is `agno-public/demo/sample_seaview.mp4` (actually a scientist using a microscope).

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

### action_timestamps.py

**Status:** PASS

**Description:** Extract a list of `Event`s with action descriptions and `[start, end]` second timestamps.

**Result:** Three events returned with monotonically increasing timestamps.

---
