from textwrap import dedent

from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.thinking import ThinkingTools
from agno.tools.yfinance import YFinanceTools

thinking_llama = Agent(
    model=Groq(id="meta-llama/llama-4-scout-17b-16e-instruct"),
    tools=[
        ThinkingTools(),
        YFinanceTools(
            stock_price=True,
            analyst_recommendations=True,
            company_info=True,
            company_news=True,
        ),
    ],
    instructions=dedent("""\
    ## General Instructions
    - Always start by using the think tool to map out the steps needed to complete the task.
    - After receiving tool results, use the think tool as a scratchpad to validate the results for correctness
    - Before responding to the user, use the think tool to jot down final thoughts and ideas.
    - Present final outputs in well-organized tables whenever possible.

    ## Using the think tool
    At every step, use the think tool as a scratchpad to:
    - Restate the object in your own words to ensure full comprehension.
    - List the  specific rules that apply to the current request
    - Check if all required information is collected and is valid
    - Verify that the planned action completes the task\
    """),
    show_tool_calls=True,
    markdown=True,
)
thinking_llama.print_response("Write a report comparing NVDA to TSLA", stream=True)
