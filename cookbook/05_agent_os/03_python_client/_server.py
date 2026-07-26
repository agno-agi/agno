"""Serve the AgentOS used by every Python client example in this folder.

The server exposes one agent, one team, one workflow, and one knowledge base
on port 7778. Set OS_SECURITY_KEY before starting it to enable Bearer auth.

Prerequisites: OPENAI_API_KEY for model, embedding, and evaluation calls.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/_server.py
Try: open http://localhost:7778/docs after the server starts.
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings
from agno.team import Team
from agno.tools.calculator import CalculatorTools
from agno.vectordb.chroma import ChromaDb
from agno.workflow import Step, Workflow

# ---------------------------------------------------------------------------
# Create the AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/python_client.db")

knowledge = Knowledge(
    name="Python Client Knowledge",
    contents_db=db,
    vector_db=ChromaDb(
        collection="python_client_knowledge",
        path="tmp/python_client_chromadb",
        persistent_client=True,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

assistant = Agent(
    id="assistant",
    name="Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Answer clearly and concisely.",
        "Use the calculator for arithmetic.",
        "Search the knowledge base when the user asks about uploaded content.",
    ],
    tools=[CalculatorTools()],
    knowledge=knowledge,
    search_knowledge=True,
)

research_team = Team(
    id="research-team",
    name="Research Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[assistant],
    instructions="Delegate questions to the assistant and return a concise answer.",
)

qa_workflow = Workflow(
    id="qa-workflow",
    name="QA Workflow",
    steps=[Step(name="Answer", agent=assistant)],
)

agent_os = AgentOS(
    id="python-client-demo",
    name="Python Client Demo",
    description="AgentOS server for the Python client cookbook.",
    db=db,
    agents=[assistant],
    teams=[research_team],
    workflows=[qa_workflow],
    knowledge=[knowledge],
    settings=AgnoAPISettings(os_security_key=os.getenv("OS_SECURITY_KEY")),
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run the Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7778)
