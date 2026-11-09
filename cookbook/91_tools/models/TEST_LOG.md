# Test Log

## Latest Verification — 2026-09-21

**Environment:** `.venv/bin/python` (Python 3.13), editable `libs/agno` 3.0.10 on branch `feat/aimlapi-tools`

**Model:** `gpt-5.6-luna` via `AIMLAPI`

**Key:** `AIMLAPI_API_KEY` (live gateway, `https://api.aimlapi.com`)

---

### aimlapi_tools.py

**Status:** PASS

**Description:** One agent with `AIMLAPITools` (image + speech + transcription, `base_dir=tmp`), a second agent with only the video tool. Examples 1–3 run through `agent.run`, example 4 through `agenerate_video` directly.

**Result:**
- Example 1 — `generate_image` called once; `image/png`, format `png`, 1.9 MB written to `tmp/`.
- Example 2 — `generate_speech` called once; `audio/mpeg`, format `mp3`, 44 KB.
- Example 3 — `transcribe_audio` on the file from example 2 (path relative to `base_dir`); transcript `the quick brown fox jumps over the lazy dog`, exact.
- Path guard — asking for `../../.zshrc` answers `Failed to transcribe audio: ... is outside the allowed directory tmp`; nothing is uploaded.
- Example 4 — `agenerate_video` (`bytedance/seedance-2-5`, 480p, 4 s): `video/mp4`, format `mp4`, 2.0 MB after 179 s of polling.

Unit tests: `pytest libs/agno/tests/unit/tools/models/test_aimlapi.py` — 31 passed.

---

### Pending

**Status:** NOT RUN

**Description:** The other examples in this directory have not been executed yet in this workspace.

**Result:** Add individual run results after executing them.

---
