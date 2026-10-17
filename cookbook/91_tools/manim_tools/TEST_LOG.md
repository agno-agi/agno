# Test Log

## Unit tests — `libs/agno/tests/unit/tools/test_manim.py`

**Status:** PASS (16/16)

**Description:** Covers all branches of `ManimTools.render_scene`: invalid
quality on init and per-call, invalid `max_duration_seconds` /
`max_inline_bytes`, missing executable (`FileNotFoundError`), render timeout
(`subprocess.TimeoutExpired`), non-zero exit with stderr tail, success with
no mp4 on disk, happy-path inline delivery, happy-path filepath delivery when
size > `max_inline_bytes`, duration-cap rejection, duration probe missing
(warn-but-render), `delete_after_render=False` keeps artifacts, async variant
parity, `list_rendered_videos` empty→populated, `_build_cmd` emits
`-v WARNING` and `--progress_bar none`.

**Result:** `pytest libs/agno/tests/unit/tools/test_manim.py -v` → 16 passed
in ~15 s. Hermetic (subprocess mocked; manim itself only imported via
`pytest.importorskip`).

---

### manim_tools.py

**Status:** PENDING (requires manim + ffmpeg on the host)

**Description:** End-to-end smoke test — runs a short prompt, checks the
agent attaches a Video, persists it to `tmp/saved/<id>.mp4` via
`save_video_to_disk` (handles both `Video(content=bytes)` and
`Video(filepath=...)` delivery modes).

**Result:** Not yet run on this branch.

---

### manim_tools_with_voice.py

**Status:** PENDING (requires manim + manim-voiceover + ffmpeg + SoX)

**Description:** Voiceover variant. Exercises the 900 s default timeout
since narrated renders can take several minutes.

**Result:** Not yet run on this branch.

---

### manim_agentos.py

**Status:** PENDING (requires manim + manim-voiceover + ffmpeg + SoX; AgentOS UI check)

**Description:** Mounts the voice-enabled agent in AgentOS for UI
playback verification of the inline video.

**Result:** Not yet run on this branch.
