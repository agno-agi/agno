"""AgentOS example with skills loaded from local filesystem.

This example shows how to create an agent with skills and serve it via AgentOS.

Run: python cookbook/06_agent_os/skills/agent_with_local_skill.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.skills import LocalSkills, Skills

# Get the skills directory (from the 15_skills cookbook)
skills_dir = Path(__file__).parent.parent.parent / "15_skills" / "skills"

# Create agent with skills
agent = Agent(
    name="Skilled Agent",
    model=OpenAIChat(id="gpt-4o"),
    skills=Skills(loaders=[LocalSkills(str(skills_dir))]),
    instructions=[
        "You are a helpful assistant with access to specialized skills.",
        "Use the get_skill_instructions tool to load skill guidance when needed.",
        "Use the get_skill_reference tool to access detailed documentation.",
    ],
    markdown=True,
    debug_mode=True,
)

# Create AgentOS
agent_os = AgentOS(
    id="skills-demo",
    description="Skills Demo - Agent with domain expertise from local skills",
    agents=[agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    """Run the AgentOS server.

    Visit http://localhost:7777/config to see available endpoints.
    """
    agent_os.serve(app="agent_with_local_skill:app", reload=True)
