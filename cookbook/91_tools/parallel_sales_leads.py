"""Parallel Sales Lead Monitoring — track funding and enrich prospects.

Setup:
    pip install parallel-web
    export PARALLEL_API_KEY=<your-api-key>
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Sales intelligence agent with monitoring for lead signals
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[
        ParallelTools(
            enable_search=True,
            enable_extract=True,
            enable_task=True,
            enable_monitor=True,
            default_monitor_frequency="12h",
        )
    ],
    markdown=True,
    instructions=[
        "You are a sales intelligence agent.",
        "When monitoring, focus on funding announcements and hiring signals.",
        "When enriching leads, gather: company size, tech stack, recent news, key contacts.",
    ],
)

# Set up funding announcement monitoring
agent.print_response(
    "Create a monitor to track 'Series A funding announcements fintech startups'. "
    "Check every 12 hours. Then list my active monitors.",
    stream=True,
)


# Uncomment to enrich a specific prospect:
# agent.print_response(
#     "Enrich this prospect: Ramp (ramp.com). Find: "
#     "Company size and growth rate, "
#     "Recent funding and valuation, "
#     "Key decision makers in engineering and product, "
#     "Tech stack and integrations they use.",
#     stream=True,
# )


# Uncomment for ICP monitoring:
# agent.print_response(
#     "Set up monitors for my ideal customer profile: "
#     "1. 'AI startups hiring senior engineers' "
#     "2. 'Series B funding developer tools' "
#     "3. 'New CTO appointments tech companies' "
#     "Check each every 6 hours.",
#     stream=True,
# )


# Uncomment for competitive deal tracking:
# agent.print_response(
#     "Research recent customer wins announced by Datadog, New Relic, and Splunk. "
#     "For each deal, find: customer name, deal size if available, and use case.",
#     stream=True,
# )
