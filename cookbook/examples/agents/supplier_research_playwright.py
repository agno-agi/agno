from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.firecrawl import FirecrawlTools
from agno.tools.playwright import PlaywrightTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        DuckDuckGoTools(),
        PlaywrightTools(headless=False, timeout=6000),
        FirecrawlTools(),
    ],
    instructions="""You are an Advanced Sales Research Agent for the alcohol industry.

    Your goal: Conduct comprehensive supplier research with detailed COLA registry analysis.

    ## Advanced COLA Registry Workflow:

     ### Step 1: Initial Search
     - Navigate to: https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do
     - Fill search form and fill in company name
       * input[name="searchCriteria.productOrFancifulName"] (brand name)
     - Submit with: input[type="submit"]
     - WAIT after submission: The form will auto-redirect to the results page
       * Wait for results table to load completely before proceeding
       * Verify you're on the results page by checking the URL or page content

     ### Step 2: Results Analysis
     - Wait for the results table to load using selector: table (or tr containing TTB IDs)
     - Extract all the links from the first column TTB ID column of the search results table

    ### Step 3: FIREcrawl Search
    - Use the Firecrawl tool the COLA link extracted from step 2
    - Extract all the data
     """,
    markdown=True,
    # show_tool_calls=True,
    debug_mode=True,
    add_datetime_to_instructions=True,
)
if __name__ == "__main__":
    company_name = "Sazerac"
    agent.print_response("Search for: " + company_name)
