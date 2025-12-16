from pathlib import Path

from agents.creative_studio_agent import creative_studio_agent
from agents.product_comparison_agent import product_comparison_agent
from agents.self_learning_research_agent import self_learning_research_agent
from agents.simple_research_agent import simple_research_agent
from agno.os import AgentOS

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    id="gemini-agentos",
    agents=[
        simple_research_agent,
        self_learning_research_agent,
        product_comparison_agent,
        creative_studio_agent,
    ],
    config=config_path,
    tracing=True,
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="run:app", reload=True)
