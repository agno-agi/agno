from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.media import File
from agno.models.openai.responses import OpenAIResponses

# Setup the database for the Agent Session to be stored
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

agent = Agent(
    model=OpenAIResponses(id="gpt-4o-mini"),
    db=db,
    tools=[{"type": "file_search"}, {"type": "web_search_preview"}],
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file and search the web for more information.",
    files=[File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")],
)

# Get the stored Agent session, to check the response citations
session = agent.get_session()
if session and session.runs and session.runs[-1].citations:
    print("Citations:")
    print(session.runs[-1].citations)
