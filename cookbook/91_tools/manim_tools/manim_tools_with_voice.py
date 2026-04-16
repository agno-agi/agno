"""
Manim Tools with Voice (CLI + save-to-disk)
===========================================

Like `manim_tools.py` but with `enable_voiceover=True`. Renders a very short
narrated animation and writes the decoded mp4 to `tmp/saved/<id>.mp4` so you
can play it locally.

Prerequisites:
    pip install manim
    pip install "manim-voiceover[gtts]"
    ffmpeg on PATH
    sox on PATH (winget install ChrisBagwell.SoX / brew install sox / sudo apt install sox)

Run:
    .venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_tools_with_voice.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.manim import ManimTools

from manim_tools import save_base64_video_to_disk

HERE = Path(__file__).parent
TMP_DIR = HERE / "tmp"
WORK_DIR = TMP_DIR / "render"
SAVED_DIR = TMP_DIR / "saved"
WORK_DIR.mkdir(parents=True, exist_ok=True)
SAVED_DIR.mkdir(parents=True, exist_ok=True)

manim_agent = Agent(
    name="Manim Narrator",
    model=Claude(id="claude-opus-4-7"),
    tools=[
        ManimTools(
            output_dir=WORK_DIR,
            timeout_seconds=180,
            quality="m",
            enable_voiceover=True,
        )
    ],
    description="You render very short narrated Manim Community Edition animations.",
    instructions=[
        "Compose a single Python string with `from manim import *` and a VoiceoverScene subclass.",
        "Use `GTTSService` unless asked otherwise.",
        "Call `self.set_speech_service(GTTSService())` at the top of `construct`.",
        "Wrap each animation in `with self.voiceover(text=...) as tracker:` and pass `run_time=tracker.duration` on `self.play(...)`.",
        "Keep the TOTAL runtime under 10 seconds. One or two short lines of narration.",
        "Always call `render_scene` with the full scene code and the class name.",
        "If a render fails, read the stderr tail and fix the scene code before retrying.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    response = manim_agent.run(
        "Create a tiny narrated animation: show a circle appearing, with the narration "
        "'Hello from Agno'. Keep it under 10 seconds total."
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
