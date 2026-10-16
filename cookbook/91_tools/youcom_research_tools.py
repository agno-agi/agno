import os

from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.tools.youcom.research import YouResearchTools
from dotenv import load_dotenv

load_dotenv()

agent = Agent(
    id="You_Research_Agent",
    model=OpenAILike(
        id="gpt-5.4-mini",
        api_key=os.getenv("Azure_API_KEY"),
        base_url=os.getenv("Azure_Endpoint"),
        request_params={"parallel_tool_calls": False},
    ),
    tools=[
        YouResearchTools(
            format="markdown",
            show_results=True,
            research_effort="standard",
            timeout=150,  # Timemout should be set properly beacuse reasearch api's take time
        ),
    ],
    tool_call_limit=1,
    debug_mode=True,
    debug_level=2,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "Which global cities improved air quality the most over the past 10 years, and what measurable actions contributed?",
        markdown=True,
    )
