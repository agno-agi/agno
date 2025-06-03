from agno.agent import Agent
from agno.tools.oxylabs import OxylabsTools

# Initialise the toolkit (credentials can come from env vars)
oxylabs_tools = OxylabsTools()  # picks up OXYLABS_USERNAME / OXYLABS_PASSWORD

agent = Agent(
    tools=[oxylabs_tools],
    show_tool_calls=True,  # display intermediate tool I/O
    markdown=True,  # pretty-print Markdown in the final answer
)

response = agent.run("""
1. Google-search “OpenAI GPT-4” and give me the first 3 organic results.
2. Fetch the Amazon product with ASIN B09JRKG3LC and show its title and price.
3. Scrape https://example.com and return the page <title>.
""")

print(response)


# LOW LEVEL EXAMPLE

# ------------------------------------------------------------------------------------------------
# Uncomment the following to use the OxylabsTools with your own credentials
# ------------------------------------------------------------------------------------------------

# # Initialize the OxylabsTools with your credentials (or set env vars)
# oxylabs_tools = OxylabsTools(
#     username="OXYLABS_USERNAME",  # or set OXYLABS_USERNAME env var
#     password="OXYLABS_PASSWORD",  # or set OXYLABS_PASSWORD env var
# )

# # Example: Google Search
# print("Google Search Result:")
# print(oxylabs_tools.google_search(query="OpenAI GPT-4", parse=True))

# # Example: Amazon Product
# print("Amazon Product Result:")
# print(oxylabs_tools.amazon_product(query="B09JRKG3LC", parse=True))

# # Example: Amazon Search
# print("Amazon Search Result:")
# print(oxylabs_tools.amazon_search(query="wireless mouse", parse=True))

# # Example: Universal Scraper
# print("Universal Scraper Result:")
# print(oxylabs_tools.universal(url="https://example.com", parse=True))
