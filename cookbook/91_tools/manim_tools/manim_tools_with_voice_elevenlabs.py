"""
Manim Tools with Voice - ElevenLabs (CLI + save-to-disk)
========================================================

Like `manim_tools_with_voice.py` but wired to ElevenLabs
(`ElevenLabsService`) for higher-quality narration. Renders a short
narrated animation and writes the mp4 to `tmp/saved/<id>.mp4`. Handles
both inline and filepath-backed Videos.

Prerequisites:
    pip install manim
    pip install "manim-voiceover[elevenlabs]"
    ffmpeg on PATH
    sox on PATH (winget install ChrisBagwell.SoX / brew install sox / sudo apt install sox)

    export ELEVEN_API_KEY=sk-...
        (manim-voiceover reads ELEVEN_API_KEY - NOT the ELEVEN_LABS_API_KEY
        that Agno's separate ElevenLabsTools uses. Set this one for scenes.)

Run:
    .venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools_with_voice_elevenlabs.py
"""

import os
from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.manim import ManimTools

from manim_tools import save_video_to_disk

if not os.getenv("ELEVEN_API_KEY"):
    raise SystemExit(
        "ELEVEN_API_KEY is not set. manim-voiceover's ElevenLabsService "
        "reads ELEVEN_API_KEY (not ELEVEN_LABS_API_KEY). "
        "Export it before running this cookbook."
    )

HERE = Path(__file__).parent
TMP_DIR = HERE / "tmp"
WORK_DIR = TMP_DIR / "render"
SAVED_DIR = TMP_DIR / "saved"
WORK_DIR.mkdir(parents=True, exist_ok=True)
SAVED_DIR.mkdir(parents=True, exist_ok=True)

manim_agent = Agent(
    name="Manim Narrator (ElevenLabs)",
    model=OpenAIResponses(id="gpt-5.4"),
    send_media_to_model=False,
    tools=[
        ManimTools(
            output_dir=WORK_DIR,
            quality="m",
            enable_voiceover=True,
            voice_service="elevenlabs",
        )
    ],
    description="You render very short narrated Manim Community Edition animations with ElevenLabs voiceover.",
    instructions=[
        "Compose a single Python string with `from manim import *` and a VoiceoverScene subclass.",
        "Use the voice service the toolkit was configured with - its instructions tell you the exact import path and class name.",
        "Default to `ElevenLabsService(voice_id='21m00Tcm4TlvDq8ikWAM', transcription_model=None)` (canonical female Rachel). Use voice_id rather than voice_name - voice_name matches against the user's full ElevenLabs library and can pick a cloned voice with the same name. transcription_model=None skips local Whisper which is unnecessary for run_time=tracker.duration sync and adds several seconds per chunk.",
        "Wrap each animation in `with self.voiceover(text=...) as tracker:` and pass `run_time=tracker.duration` on `self.play(...)`.",
        "Keep the TOTAL runtime under 10 seconds. One or two short lines of narration.",
        "Always call `render_scene` with the full scene code and the class name.",
        "If a render fails, read the stderr tail and fix the scene code before retrying.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    response = manim_agent.run(
        "Create a short animation of a blue circle fading in, then morphing into a green square with text hello world then orange triangle with the text Agno Agi and the speech of all the words"
        "Keep it under 10 seconds. "
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
