from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from db import demo_db

product_comparison_agent = Agent(
    name="Product Comparison Agent",
    model=Gemini(
        id="gemini-3-pro-preview",
        url_context=True,
        search=True,
    ),
    description="You are a product comparison agent that analyzes URLs and searches for reviews to provide comprehensive comparisons.",
    instructions=dedent("""\
1. Analyze URLs and search for reviews to provide comprehensive comparisons.

2. Your output format must be:
    - **Quick Verdict** - One sentence recommendation
    - **Comparison Table** - Key specs side by side
    - **Pros & Cons** - For each option
    - **Best For** - Who should choose which option

3. Be decisive and provide a coherent chain of thought for your recommendations.

4. Keep your responses concise and to the point.
        """),
    db=demo_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)


if __name__ == "__main__":
    product_comparison_agent.print_response(
        "Compare the Iphone 15 and Samsung Galaxy S25",
        stream=True,
    )
