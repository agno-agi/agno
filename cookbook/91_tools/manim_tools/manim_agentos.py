"""
Manim Tools with AgentOS
========================

Same agent as `manim_tools.py`, mounted in AgentOS so the rendered mp4
plays inline in the AgentOS UI.

Run:
    .venvs/demo/bin/python cookbook/91_tools/manim_tools/manim_agentos.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.manim import ManimTools
from agno.tools.website import WebsiteTools
from agno.tools.websearch import WebSearchTools

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
        ),
        WebSearchTools(enable_search=True, enable_news=True),
        WebsiteTools(),
    ],
    description="You are an expert in Manim Community Edition. You research a topic, then write Scene subclasses that explain it with synchronized narration.",
    instructions=[
        "For any animation topic, first research it: use WebSearchTools to find authoritative sources, then use WebsiteTools.read_url to read specific pages in depth.",
        "Synthesize the key facts, then compose a single Python string containing `from manim import *` and a VoiceoverScene subclass.",
        "Use voiceover: subclass `VoiceoverScene`, import a service from `manim_voiceover.services` (default to `GTTSService`), call `self.set_speech_service(...)` at the top of `construct`, and wrap each animation in `with self.voiceover(text=...) as tracker:` using `run_time=tracker.duration`.",
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
