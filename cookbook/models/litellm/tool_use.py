from agno.agent import Agent
from agno.models.litellm import LiteLLMSDK
from agno.tools.yfinance import YFinanceTools

openai_agent = Agent(
    model=LiteLLMSDK(
        id="gpt-4o",
        name="LiteLLM",
    ),
    markdown=True,
    tools=[YFinanceTools()],
)

# Ask a question that would likely trigger tool use
openai_agent.print_response("How is TSLA stock doing right now?")
