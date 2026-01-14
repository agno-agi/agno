from pathlib import Path

from agent_search_over_knowledge import agent_with_knowledge
from agent_with_guardrails import agent_with_guardrails
from agent_with_memory import agent_with_memory
from agent_with_state_management import agent_with_state_management
from agent_with_storage import agent_with_storage
from agent_with_structured_output import agent_with_structured_output
from agent_with_tools import agent_with_tools
from agent_with_typed_input_output import agent_with_typed_input_output
from agno.os import AgentOS
from custom_tool_for_self_learning import self_learning_agent
from human_in_the_loop import human_in_the_loop_agent
from multi_agent_team import multi_agent_team
from sequential_workflow import sequential_workflow

# ============================================================================
# AgentOS Config
# ============================================================================
config_path = str(Path(__file__).parent.joinpath("config.yaml"))

# ============================================================================
# Create AgentOS
# ============================================================================
agent_os = AgentOS(
    id="Getting Started AgentOS",
    agents=[
        agent_with_tools,
        agent_with_storage,
        agent_with_knowledge,
        self_learning_agent,
        agent_with_structured_output,
        agent_with_typed_input_output,
        agent_with_memory,
        agent_with_state_management,
        human_in_the_loop_agent,
        agent_with_guardrails,
    ],
    teams=[multi_agent_team],
    workflows=[sequential_workflow],
    config=config_path,
    tracing=True,
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    agent_os.serve(app="run:app", reload=True)
