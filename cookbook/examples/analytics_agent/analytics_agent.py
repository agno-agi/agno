"""Runnable companion to the analytics agent guide."""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.sql import SQLTools

# ---------------------------------------------------------------------------
# Create the example
# ---------------------------------------------------------------------------

sql = SQLTools(db_url="sqlite:///file:analytics.db?mode=ro&uri=true")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6"),
    tools=[sql],
    instructions=[
        "Answer questions about the subscriptions database.",
        "Inspect table schemas before writing a query.",
        "Active MRR is SUM(mrr_usd) for rows whose status is active.",
        "mrr_usd is a monthly amount in whole US dollars.",
        "Include the SQL used and explain which records it includes.",
        "If the data cannot answer the question, explain what is missing.",
    ],
)

# ---------------------------------------------------------------------------
# Run the example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("What is our active MRR, and which accounts contribute to it?")
