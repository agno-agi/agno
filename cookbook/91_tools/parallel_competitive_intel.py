"""Parallel Competitive Intelligence — automated competitor tracking.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Competitive intelligence agent with search, task, and monitor APIs
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_search=True,
            enable_task=True,
            enable_monitor=True,
            default_processor="standard",
            default_monitor_frequency="6h",
        )
    ],
    markdown=True,
    instructions=[
        "You are a competitive intelligence analyst.",
        "When researching competitors, gather: pricing, features, positioning, recent news.",
        "When setting up monitors, focus on product launches and strategic announcements.",
    ],
)

# Research a competitor landscape
agent.print_response(
    "Research the AI code editor market. Compare Cursor, GitHub Copilot, and Windsurf. "
    "For each, find: pricing tiers, key differentiators, recent product announcements, "
    "and target developer segments.",
    stream=True,
)


# Uncomment to set up ongoing competitor tracking:
# agent.print_response(
#     "Create monitors to track announcements from Cursor, GitHub Copilot, and Windsurf. "
#     "I want to know about new features, pricing changes, and partnerships.",
#     stream=True,
# )


# Uncomment for pricing intelligence:
# agent.print_response(
#     "Research and compare pricing strategies of the top 5 vector database providers: "
#     "Pinecone, Weaviate, Qdrant, Milvus, and Chroma. Include free tiers and enterprise pricing.",
#     stream=True,
# )
