from agno.agent import Agent
from agno.models.litellm import LiteLLM
from agno.tools.yfinance import YFinanceTools

openai_agent = Agent(
    model=LiteLLM(
        id="gpt-4o", 
        name="OpenAI via LiteLLM",
    ),
    markdown=True,
)

openai_agent.print_response("Tell me a 2 line horror story")
