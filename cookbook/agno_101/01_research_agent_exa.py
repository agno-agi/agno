from datetime import datetime

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.exa import ExaTools

# ************* Create Agent *************
research_agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    tools=[ExaTools(start_published_date=datetime.now().strftime("%Y-%m-%d"))],
    add_datetime_to_context=True,
    markdown=True,
)

# ************* Run Agent *************
research_agent.print_response("What's new in AI Agents?", stream=True)
