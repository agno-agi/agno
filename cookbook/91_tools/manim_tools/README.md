# Manim Tools

Renders Manim Community Edition animations with an Agno agent and attaches the mp4 to the run response so AgentOS (or any consumer of `RunOutput.videos`) can play it.

## Prerequisites

- Python with `manim` installed: `.venvs/demo/bin/pip install manim`
- `ffmpeg` on PATH
- LaTeX is optional (only if your scenes use `MathTex` or `Tex`)

### Voiceover (only if `enable_voiceover=True`)

Pass `voice_service="gtts"` (default, free) or `voice_service="elevenlabs"` (paid, higher quality) to `ManimTools(...)`. The toolkit validates the import at construction time and feeds the LLM instructions tailored to the chosen service.

- `manim-voiceover` with a speech service extra:
  ```bash
  pip install "manim-voiceover[gtts]"         # free, Google TTS (default)
  pip install "manim-voiceover[elevenlabs]"   # paid, ElevenLabs
  # other extras: [openai], [azure], [coqui], [recorder]
  ```
- **ElevenLabs env var.** `manim-voiceover`'s `ElevenLabsService` reads `ELEVEN_API_KEY` - *not* `ELEVEN_LABS_API_KEY` that Agno's separate `ElevenLabsTools` uses. Set `ELEVEN_API_KEY` before running an ElevenLabs-backed scene.
- **SoX** on PATH (used by `manim_voiceover` to trim silence and normalize audio). The toolkit prints a warning at startup if it's missing; voiceover renders still work without it but audio quality is degraded.
  ```bash
  winget install ChrisBagwell.SoX    # Windows
  brew install sox                   # macOS
  sudo apt install sox               # Debian / Ubuntu
  ```
  After installing on Windows, reload the VSCode window (`Ctrl+Shift+P` -> `Developer: Reload Window`) so the integrated terminal picks up the new PATH.

## Files

- `manim_tools.py` - CLI demo without voice. Runs a single prompt, saves the mp4 to `tmp/saved/<id>.mp4`. Good for smoke testing.
- `manim_tools_with_voice.py` - CLI demo with `enable_voiceover=True, voice_service="gtts"`. Free Google TTS narration. Requires `manim-voiceover[gtts]` and SoX.
- `manim_tools_with_voice_elevenlabs.py` - CLI demo with `voice_service="elevenlabs"`. Higher-quality narration. Requires `manim-voiceover[elevenlabs]`, SoX, and `ELEVEN_API_KEY`.
- `manim_agentos.py` - Voice-enabled agent plus web research tools, wrapped in AgentOS for end-to-end UI testing.

## Run

```bash
.venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools.py
.venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools_with_voice.py
.venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools_with_voice_elevenlabs.py
.venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_agentos.py
```

## Delivery

Renders under `max_inline_bytes` (default **25 MB**) come back as `Video(content=bytes)`. Agno base64-encodes `content` at serialization time, so AgentOS and other interfaces receive a self-contained inlined video - no static file route required.

Renders over that cap are persisted to `output_dir` and returned as `Video(filepath=...)` instead. Consumers still get a `Video` artifact; they load bytes lazily from disk via `video.get_content_bytes()` / `aget_content_bytes()` (see `libs/agno/agno/media.py`). This avoids blowing up the SSE payload on a long 1080p render while keeping a uniform API.

`manim_tools.py` also shows the opposite direction: handle both delivery modes and write the mp4 to disk. See `save_video_to_disk` (decodes `Video.content` for inline, copies from `Video.filepath` for the over-cap case).

## Safety bounds

| Param | Default | What it does |
|---|---|---|
| `timeout_seconds` | `900` (15 min) | Hard subprocess timeout for each render. Voiceover renders can be slow - bump higher if you're generating long narrated scenes. |
| `max_duration_seconds` | `120.0` | Rejects renders whose output mp4 runs longer than this (probed via `ffprobe`). The error message tells the agent to shorten the scene and retry. If `ffprobe` isn't on PATH, the check is skipped with a warning. |
| `max_inline_bytes` | `25 * 1024 * 1024` | Size threshold for inline-bytes vs. filepath delivery (see above). |

## Notes

- `ManimTools` writes each render's scene `.py` and `media_{run_id}/` subtree under its `output_dir`, reads the mp4 bytes, then deletes those artifacts (`delete_after_render=True` by default). Pass `delete_after_render=False` if you want to inspect them on disk.
- The CLI demo's decoded mp4s (`tmp/saved/<video-id>.mp4`) are written by the cookbook itself, not the toolkit - they persist on purpose so you can play the result after the run.
- `tmp/` is covered by the repo's global `tmp` gitignore rule.
- Quality presets follow Manim CE: `l` = 480p15, `m` = 720p30, `h` = 1080p60, `k` = 2160p60.
- The LLM composes the Scene; it occasionally uses an API that doesn't exist in your installed Manim version. On failure, the tool returns the stderr tail so the agent can self-correct.
