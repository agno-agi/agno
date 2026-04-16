"""
Manim Tools
===========

Renders Manim Community Edition animations via an Agno agent. The rendered mp4
is attached to the run response as a base64-inlined Video so any consumer of
`RunOutput.videos` (AgentOS UI, WhatsApp interface, etc.) can play it directly.

This script also demonstrates how a consumer can decode the inlined base64
payload back into an mp4 file on disk.

Prerequisites:
    pip install manim
    ffmpeg must be on PATH

Run:
    .venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools.py
"""

import base64
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
            timeout_seconds=180,
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


def save_base64_video_to_disk(video: Video, dest_dir: Path) -> Path:
    """Decode a Video's inlined base64 payload and write it to an mp4 file.

    `Video.content` holds raw bytes in-memory, but is serialized as base64
    over the wire. `Video.to_base64()` produces that same base64 string,
    which a client can decode and save exactly like this.
    """
    b64 = video.to_base64()
    if not b64:
        raise ValueError("Video has no inlined content to save.")
    raw_bytes = base64.b64decode(b64)
    suffix = video.format or "mp4"
    dest = dest_dir / f"{video.id}.{suffix}"
    dest.write_bytes(raw_bytes)
    return dest


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
            inline_bytes = len(v.content) if v.content else 0
            print(f"  id={v.id} format={v.format} inline_bytes={inline_bytes}")
            saved_path = save_base64_video_to_disk(v, SAVED_DIR)
            print(
                f"  decoded base64 -> wrote {saved_path} ({saved_path.stat().st_size} bytes)"
            )
