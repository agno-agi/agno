from agno.agent import Agent
from agno.tools.oxylabs import OxylabsTools

agent = Agent(
    tools=[OxylabsTools()],
    markdown=True,
)

# Example 1: Google Search
agent.print_response(
    "Let's search for 'latest iPhone reviews' and provide a summary of the top 3 results. ",
)

# Example 2: Amazon Product Search
# agent.print_response(
#     "Let's search for an Amazon product with ASIN 'B07FZ8S74R' (Echo Dot). ",
# )

# Example 3: Multi-Domain Amazon Search
# agent.print_response(
#     "Use search_amazon_products to search for 'gaming keyboards' on both:\n"
#     "1. Amazon US (domain='com')\n"
#     "2. Amazon UK (domain='co.uk')\n"
#     "Compare the top 3 results from each region including pricing and availability."
# )
