"""
Manim Tools with AgentOS (ElevenLabs voiceover)
===============================================

Research-and-animate agent mounted in AgentOS with web tools and
ElevenLabs narration. The rendered mp4 plays inline in the AgentOS UI.

Prerequisites:
    pip install manim
    pip install "manim-voiceover[elevenlabs]"
    ffmpeg on PATH
    sox on PATH
    export ELEVEN_API_KEY=sk-...      (NOT ELEVEN_LABS_API_KEY)

Run:
    .venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_agentos.py
"""

import os
from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.manim import ManimTools
from agno.tools.website import WebsiteTools
from agno.tools.websearch import WebSearchTools

if not os.getenv("ELEVEN_API_KEY"):
    raise SystemExit(
        "ELEVEN_API_KEY is not set. manim-voiceover's ElevenLabsService "
        "reads ELEVEN_API_KEY (not ELEVEN_LABS_API_KEY). "
        "Export it before running this cookbook."
    )

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "tmp" / "render"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

manim_agent = Agent(
    name="Manim Animator",
    model=Claude(id="claude-opus-4-7"),
    tools=[
        ManimTools(
            output_dir=OUTPUT_DIR,
            quality="h",
            enable_voiceover=True,
            voice_service="elevenlabs",
        ),
        WebSearchTools(enable_search=True, enable_news=True),
        WebsiteTools(),
    ],
    description="You are an expert in Manim Community Edition. You research a topic, then write Scene subclasses that explain it with synchronized narration.",
    instructions=[
        "For any animation topic, first research it: use WebSearchTools to find authoritative sources, then use WebsiteTools.read_url to read specific pages in depth.",
        "Synthesize the key facts, then compose a single Python string containing `from manim import *` and a VoiceoverScene subclass.",
        "Use the voice service the toolkit was configured with - its instructions tell you the exact import path and class name.",
        "Default to `ElevenLabsService(voice_id='21m00Tcm4TlvDq8ikWAM', transcription_model=None)` (canonical female Rachel). Use voice_id rather than voice_name - voice_name matches against the user's full ElevenLabs library and can pick a cloned voice with the same name. transcription_model=None skips local Whisper which is unnecessary for run_time=tracker.duration sync and adds several seconds per chunk.",
        "Wrap each animation in `with self.voiceover(text=...) as tracker:` using `run_time=tracker.duration`.",
        "Keep scenes short (under ~30 seconds) unless asked for more. The narration text should be factually grounded in what you researched.",
        "Always call `render_scene` with the full scene code and the class name.",
        "If a render fails, read the stderr tail and fix the scene code before retrying.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Manim animation agent - renders scenes and returns mp4s inline.",
    agents=[manim_agent],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="manim_agentos:app", reload=False)
