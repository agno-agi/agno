# Test Log - _14_video_extraction

Tested 2026-07-18 against `gemini-3.5-flash`, agno 2.7.4.

### action_timestamps.py

**Status:** PASS

**Description:** Extracts an `Events` list from sample_seaview.mp4, each `Event` with an action name and start/end times in seconds. Exercises structured output (`output_schema`) over raw video bytes with Gemini.

**Result:** One event returned: `action='A scientist looking into a microscope'`, `start_seconds=0.0`, `end_seconds=9.0`. Timestamps monotonic and within the clip. Model call took ~6.8s (726 input / 54 output tokens).

---

### basic.py

**Status:** PASS

**Description:** Extracts a `VideoSummary` (overall summary, dominant subject, ordered scene phrases) from sample_seaview.mp4. Exercises clip-level summarization with a typed schema.

**Result:** `dominant_subject='Female scientist'`; two-sentence summary of a scientist in protective gear examining a sample through a microscope under blue and warm lighting; 3 scene phrases returned (side view at microscope, close-up adjusting focus, continued observation). Model call took ~7.6s (733 input / 117 output tokens).

---

### scene_descriptions.py

**Status:** PASS

**Description:** Extracts a `ScenesDocument` from sample_seaview.mp4, one `Scene` per detected scene with name, description, and up to five visible objects. Exercises per-scene structured indexing output.

**Result:** One scene returned: `name='Scientific Microscope Examination'` with a detailed description and 5 visible objects (`microscope`, `scientist`, `protective suit`, `safety glasses`, `gloves`). Model call took ~7.5s (726 input / 102 output tokens).

---
