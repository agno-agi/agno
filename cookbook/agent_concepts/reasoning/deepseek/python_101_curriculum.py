from agno.agent.agent import Agent
from agno.models.deepseek.deepseek import DeepSeek
from agno.models.openai.chat import OpenAIChat

task = "Craft a curriculum for Python 101"

reasoning_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    reasoning_model=DeepSeek(id="deepseek-reasoner"),
    markdown=True,
)
reasoning_agent.print_response(task, stream=True)
