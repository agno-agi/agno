from phi.agent import Agent
from phi.model.azure import AzureOpenAIChat
from phi.tools.duckduckgo import DuckDuckGo

import os
from dotenv import load_dotenv

load_dotenv()

azure_model = AzureOpenAIChat(
    model = os.getenv("AZURE_OPENAI_MODEL_NAME"),
    api_key = os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT"),
)

agent = Agent(
    model=azure_model,
    tools=[DuckDuckGo()],
    show_tool_calls=True,
    # debug_mode=True,
)

agent.print_response("Whats happening in France?", markdown=True, stream=True)

