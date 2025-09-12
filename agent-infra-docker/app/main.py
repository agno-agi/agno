"""AgentOS Demo"""

import asyncio
from pathlib import Path

from agno.os import AgentOS

from agents.agno_assist import get_agno_assist
from agents.web_agent import get_web_agent

os_config_path = str(Path(__file__).parent.joinpath("config.yaml"))

web_agent = get_web_agent(model_id="gpt-5")
agno_assist = get_agno_assist(model_id="gpt-5")

# Create the AgentOS
agent_os = AgentOS(
    os_id="agentos-demo",
    agents=[web_agent, agno_assist],
    # Configuration for the AgentOS
    config=os_config_path,
)
app = agent_os.get_app()

if __name__ == "__main__":
    # Add knowledge to Agno Assist agent
    asyncio.run(
        agno_assist.knowledge.add_content_async(  # type: ignore
            name="Agno Docs",
            url="https://docs.agno.com/llms-full.txt",
        )
    )
    # Simple run to generate and record a session
    agent_os.serve(app="main:app", reload=True)
