from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from db import demo_db

product_comparison_agent = Agent(
    name="Product Comparison Agent",
    role="Compare products by analyzing URLs and searching for reviews",
    model=Gemini(
        id="gemini-2.5-flash",
        url_context=True,
        search=True,
    ),
    description="Compare products by analyzing URLs and searching for reviews.",
    instructions=dedent("""\
        Analyze URLs and search for reviews to provide comprehensive comparisons.

        Output format:
        1. **Quick Verdict** - One sentence recommendation
        2. **Comparison Table** - Key specs side by side
        3. **Pros & Cons** - For each option
        4. **Best For** - Who should choose which option

        Be decisive. Give clear recommendations, not just information.
        """),
    db=demo_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=3,
    enable_agentic_memory=True,
    enable_user_memories=True,
    markdown=True,
)


if __name__ == "__main__":
    product_comparison_agent.print_response(
        f"Compare the Iphone 15 and Samsung Galaxy S25",
        stream=True,
    )
