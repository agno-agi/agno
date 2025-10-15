from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.tools.playwright import PlaywrightTools

agent = Agent(
    model=Claude(id="claude-sonnet-4-5-20250929"),
    tools=[PlaywrightTools(headless=False, timeout=10000)],
    role="Your task is to use your web browsing capabilities to find information and take actions on the web.",
    markdown=True,
    exponential_backoff=True,
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    max_tool_calls_in_context=2,  # Keep only the last 2 tool calls in context
    add_history_to_context=True,
    session_id="playwright_personality_session2",
)

agent.print_response(
    input="Look for a personality test with less than 10 questions on the web and take it. Summarize the results of the test and provide a link to the test you took.",
    debug_mode=True,
)
