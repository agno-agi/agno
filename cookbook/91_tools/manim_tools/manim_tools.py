"""
Manim Tools
===========

Renders Manim Community Edition animations via an Agno agent. Small renders
come back as `Video(content=bytes)` (base64-inlined at serialization); larger
renders come back as `Video(filepath=...)` so the SSE payload stays sane.

This script demonstrates handling both delivery modes: it decodes inline
bytes or copies the on-disk mp4 into `tmp/saved/<id>.mp4`.

Prerequisites:
    pip install manim
    ffmpeg must be on PATH

Run:
    .venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools.py
"""

import base64
import shutil
from pathlib import Path

from agno.agent import Agent
from agno.media import Video
from agno.models.openai import OpenAIResponses
from agno.tools.manim import ManimTools

HERE = Path(__file__).parent
TMP_DIR = HERE / "tmp"
WORK_DIR = TMP_DIR / "render"
SAVED_DIR = TMP_DIR / "saved"
WORK_DIR.mkdir(parents=True, exist_ok=True)
SAVED_DIR.mkdir(parents=True, exist_ok=True)

manim_agent = Agent(
    name="Manim Animator",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ManimTools(
            output_dir=WORK_DIR,
            quality="m",
        )
    ],
    description="You are an expert in Manim Community Edition. You write Scene subclasses in Python and render them into short animation videos.",
    instructions=[
        "When the user asks for an animation, compose a single Python string containing `from manim import *` and a Scene subclass.",
        "Keep scenes short (under ~10 seconds) unless asked for more.",
        "Always call `render_scene` with the full scene code and the class name.",
        "If a render fails, read the stderr tail and fix the scene code before retrying.",
    ],
    markdown=True,
)


def save_video_to_disk(video: Video, dest_dir: Path) -> Path:
    """Persist a Video to `dest_dir/<id>.<ext>`, regardless of delivery mode.

    `ManimTools` returns `Video(content=bytes)` for small renders (base64-
    inlined at serialization) and `Video(filepath=...)` for large renders
    that exceed `max_inline_bytes`. Consumers should handle both.

    Inline: decode `video.to_base64()` and write the bytes.
    Filepath: copy the on-disk mp4 (it already lives under `output_dir`).
    URL: fall back to `video.get_content_bytes()` which fetches remotely.
    """
    suffix = video.format or "mp4"
    dest = dest_dir / f"{video.id}.{suffix}"

    if video.content is not None:
        b64 = video.to_base64()
        assert b64 is not None
        dest.write_bytes(base64.b64decode(b64))
        return dest

    if video.filepath is not None:
        shutil.copyfile(str(video.filepath), dest)
        return dest

    raw = video.get_content_bytes()
    if raw is None:
        raise ValueError(
            f"Video {video.id!r} has no resolvable content (no content/filepath/url)."
        )
    dest.write_bytes(raw)
    return dest


# Backwards-compat alias for downstream scripts that still import the old name.
save_base64_video_to_disk = save_video_to_disk


if __name__ == "__main__":
    response = manim_agent.run(
        "Create a short animation of a blue circle fading in, then morphing into a green square with text hello world then orange triangle with the text Agno Agi"
        "Keep it under 10 seconds."
    )
    print("\n--- agent message ---")
    print(response.content)

    print("\n--- attached videos ---")
    if not response.videos:
        print("  (none)")
    else:
        for v in response.videos:
            delivery = (
                "inline"
                if v.content is not None
                else ("filepath" if v.filepath else "url")
            )
            inline_bytes = len(v.content) if v.content else 0
            print(
                f"  id={v.id} format={v.format} delivery={delivery} "
                f"inline_bytes={inline_bytes} filepath={v.filepath}"
            )
            saved_path = save_video_to_disk(v, SAVED_DIR)
            print(f"  saved -> {saved_path} ({saved_path.stat().st_size} bytes)")
