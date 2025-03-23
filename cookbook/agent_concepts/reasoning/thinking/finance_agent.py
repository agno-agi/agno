from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.thinking import ThinkingTools
from agno.tools.yfinance import YFinanceTools

thinking_agent = Agent(
    model=Claude(id="claude-3-5-sonnet-20240620"),
    tools=[
        ThinkingTools(),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    system_message=dedent("""\
    <using_the_think_tool>
    Before taking any action, starting tool calls or responding to the user after receiving tool results, use the think tool as a scratchpad to:
    - List the specific rules that apply to the current request
    - Check if all required information is collected
    - Verify that the planned action complies with all policies
    - Iterate over tool results for correctness
    </using_the_think_tool>

    <formatting_instructions>
    - Use tables where possible
    - Return only the final answer, no other text. Use the think tool to jot down thoughts and ideas
    - Your output should be in markdown format
    </formatting_instructions>\
    """),
    show_tool_calls=True,
)
thinking_agent.print_response(
    "Write a report comparing NVDA to TSLA", stream=True, markdown=True
)
