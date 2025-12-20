from pathlib import Path

from agno.os import AgentOS

from agent_with_tools import agent_with_tools

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    id="AgentOS Getting Started",
    agents=[agent_with_tools],
    config=config_path,
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
