"""
Setting Up Authentication for Trello Tools
Step 1: Get Your API Key
1. Visit the Trello Power-Ups Administration Page https://trello.com/power-ups/admin
2. (Optional) Create a Workspace
3. Create a Power Up (this is required. Its like a "App" connector)
   - If you don't already have a power-ups, create one by clicking the "New" button.
   - If you have an existing Power-Up, select it from the list.
Step 2: Generate API Key and Secret
1. On the left sidebar, click on the "API Key" option.
2. Generate a new API Key:
   - Click the button to generate your API Key.
   - Copy the generated API Key and Secret. Store as TRELLO_API_KEY and TRELLO_API_SECRET.
Step 3: Generate a Token
1. On the same page where your API Key is shown, locate the option to manually generate a Token.
2. Authorize your Trello account:
   - Follow the on-screen instructions to authorize the application.
3. Copy the generated Token. Store as TRELLO_TOKEN.
"""

from agno.agent import Agent
from agno.tools.trello import TrelloTools

agent = Agent(
    instructions=[
        "You are a Trello management assistant that helps organize and manage Trello boards, lists, and cards",
        "Help users with tasks like:",
        "- Creating and organizing boards, lists, and cards",
        "- Moving cards between lists",
        "- Retrieving board and list information",
        "- Managing card details and descriptions",
        "Always confirm successful operations and provide relevant board/list/card IDs and URLs",
        "When errors occur, provide clear explanations and suggest solutions",
    ],
    tools=[TrelloTools()],
    show_tool_calls=True,
)

agent.print_response(
    "Create a board called ai-agent and inside it create list called 'todo' and 'doing' and inside each of them create card called 'create agent'",
    stream=True,
)
