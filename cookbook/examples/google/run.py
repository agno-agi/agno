from pathlib import Path
from textwrap import dedent

from agno.os import AgentOS
from creative_studio_agent import creative_studio_agent
from product_comparison_agent import product_comparison_agent
from research_agent import research_agent
from visual_storyteller_agent import visual_storyteller_agent

config_path = str(Path(__file__).parent.joinpath("config.yaml"))

agent_os = AgentOS(
    id="google-examples",
    description=dedent("""\
        Google Examples AgentOS — showcasing Google-specific AI capabilities with Agno.
        Features NanoBanana image generation, Google Search grounding, URL context analysis,
        and creative multi-modal workflows.
        """),
    agents=[
        creative_studio_agent,
        research_agent,
        product_comparison_agent,
        visual_storyteller_agent,
    ],
    config=config_path,
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
