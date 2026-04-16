# Manim Tools

Renders Manim Community Edition animations with an Agno agent and attaches the mp4 to the run response so AgentOS (or any consumer of `RunOutput.videos`) can play it.

## Prerequisites

- Python with `manim` installed: `.venvs/demo/bin/pip install manim`
- `ffmpeg` on PATH
- LaTeX is optional (only if your scenes use `MathTex` or `Tex`)

## Files

- `manim_tools.py` - CLI demo. Runs a single prompt and prints attached video metadata. Good for smoke testing.
- `manim_agentos.py` - Same agent wrapped in AgentOS for end-to-end UI testing.

## Run

```bash
.venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools.py
.venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_agentos.py
```

## Delivery

Every render is returned as `Video(content=bytes)`. Agno base64-encodes `content` at serialization time, so AgentOS and other interfaces receive a self-contained inlined video - no static file route required. Large scenes will make the SSE payload large; trim the runtime or quality if that becomes a problem.

`manim_tools.py` also shows the opposite direction: take a returned `Video`, call `video.to_base64()`, decode it, and write it to disk as an mp4. See `save_base64_video_to_disk`.

## Notes

- All on-disk artifacts land under `tmp/` (covered by the repo's global `tmp` gitignore rule): manim's intermediate output in `tmp/render/`, and the CLI demo's decoded copies in `tmp/saved/<video-id>.mp4`.
- Quality presets follow Manim CE: `l` = 480p15, `m` = 720p30, `h` = 1080p60, `k` = 2160p60.
- The LLM composes the Scene; it occasionally uses an API that doesn't exist in your installed Manim version. On failure, the tool returns the stderr tail so the agent can self-correct.
