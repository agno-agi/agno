"""Run `pip install ddgs` to install dependencies."""

from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.tools.duckduckgo import DuckDuckGoTools

"""
DeepSeek model's thinking mode now supports tool calls. 
Before outputting the final answer, the model can engage in multiple turns of reasoning and tool calls to improve the quality of the response. 
"""

agent = Agent(
    model=DeepSeek(id="deepseek-reasoner"),
    tools=[DuckDuckGoTools()],
    markdown=True,
    stream=True,
)

agent.print_response("Whats happening in France?", show_full_reasoning=True)
