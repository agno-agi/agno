from pathlib import Path

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.skills import LocalSkills, Skills

# Get the skills directory relative to this file
skills_dir = Path(__file__).parent / "skills"

# Create agent with skills
agent = Agent(
    name="Skilled Agent",
    model=OpenAIChat(id="gpt-4o"),
    skills=Skills(loaders=[LocalSkills(str(skills_dir))]),
    instructions=[
        "You are a helpful assistant that can use the skills to help the user.",
    ],
    markdown=True,
)

# Create AgentOS
agent_os = AgentOS(
    id="skills-cookbook",
    description="Skills Cookbook - Agent with domain expertise",
    agents=[agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="app:app", reload=True)
