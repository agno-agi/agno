"""AgentOS example with skills loaded from local filesystem.

This example shows how to create an agent with skills and serve it via AgentOS.

Run: python cookbook/06_agent_os/skills/agent_with_local_skill.py
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.skills import LocalSkills, Skills

# Get the skills directory (from the 03_agents/skills cookbook)
skills_dir = Path(__file__).parent.parent.parent / "03_agents" / "skills" / "sample_skills"

# Create an agent with skills
agent = Agent(
    name="Skilled Agent",
    model=OpenAIChat(id="gpt-4o"),
    skills=Skills(loaders=[LocalSkills(str(skills_dir))]),
    instructions=[
        "You are a helpful assistant with access to specialized skills.",
    ],
    markdown=True,
)

# Create AgentOS
agent_os = AgentOS(
    id="skills-demo",
    description="Skills Demo - Agent with domain expertise from local skills",
    agents=[agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="agent_with_local_skill:app", reload=True)
