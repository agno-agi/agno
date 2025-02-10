from typing import List, Optional

import typer
from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=PgVector(
        table_name="recipes", db_url=db_url, search_type=SearchType.hybrid
    ),
)
# Load the knowledge base: Comment after first run
knowledge_base.load(upsert=True)

storage = PostgresAgentStorage(table_name="pdf_agent", db_url=db_url)


def pdf_agent(new: bool = False, user: str = "user"):
    session_id: Optional[str] = None

    if not new:
        existing_sessions: List[str] = storage.get_all_session_ids(user)
        if len(existing_sessions) > 0:
            session_id = existing_sessions[0]

    agent = Agent(
        session_id=session_id,
        user_id=user,
        knowledge=knowledge_base,
        storage=storage,
        # Show tool calls in the response
        show_tool_calls=True,
        # Enable the agent to read the chat history
        read_chat_history=True,
        # We can also automatically add the chat history to the messages sent to the model
        # But giving the model the chat history is not always useful, so we give it a tool instead
        # to only use when needed.
        # add_history_to_messages=True,
        # Number of historical responses to add to the messages.
        # num_history_responses=3,
    )
    if session_id is None:
        session_id = agent.session_id
        print(f"Started Session: {session_id}\n")
    else:
        print(f"Continuing Session: {session_id}\n")

    # Runs the agent as a cli app
    agent.cli_app(markdown=True)


if __name__ == "__main__":
    typer.run(pdf_agent)
