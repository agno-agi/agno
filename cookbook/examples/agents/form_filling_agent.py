from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.browserbase import BrowserbaseTools

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[BrowserbaseTools()],
    instructions="You are a form filling agent. You will be given a form and you will need to fill it out.",
    markdown=True,
    # show_tool_calls=True,
    debug_mode=True,
)

agent.print_response("Navigate to https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do and fill out the COLA search form. Use these exact CSS selectors: fill 'searchCriteria.dateCompletedFrom' with '01/01/2024', fill 'searchCriteria.dateCompletedTo' with '12/31/2024', fill 'searchCriteria.productOrFancifulName' with 'Wine', click the Brand Name radio button with id 'brandname', and fill 'searchCriteria.originCode' with 'US'. Take a screenshot when done.")