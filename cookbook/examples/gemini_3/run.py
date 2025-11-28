from pathlib import Path
from textwrap import dedent

from agno.os import AgentOS
from creative_studio_agent import creative_studio_agent
from product_comparison_agent import product_comparison_agent
from research_agent import research_agent

config_path = str(Path(__file__).parent.joinpath("config.yaml"))

agent_os = AgentOS(
    id="gemini-3",
    description=dedent("""\
        Gemini 3 AgentOS — showcasing Gemini 3 specific capabilities with Agno.
        Features NanoBanana image generation, Gemini Search grounding, URL context analysis and more.
        """),
    agents=[
        creative_studio_agent,
        research_agent,
        product_comparison_agent,
    ],
    config=config_path,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
