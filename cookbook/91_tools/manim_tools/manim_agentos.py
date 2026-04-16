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
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.manim import ManimTools

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "tmp" / "render"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

manim_agent = Agent(
    name="Manim Animator",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ManimTools(
            output_dir=OUTPUT_DIR,
            timeout_seconds=180,
            quality="h",
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

agent_os = AgentOS(
    description="Manim animation agent - renders scenes and returns mp4s inline.",
    agents=[manim_agent],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="manim_agentos:app", reload=False)
