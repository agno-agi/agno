from agno.agent import Agent
from agno.db.json import JsonDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


vector_db = PgVector(table_name="vectors", db_url=db_url)
secondary_vector_db = PgVector(table_name="more_vectors", db_url=db_url)
contents_db = JsonDb(db_path="./agno_json_data", knowledge_table="main_knowledge")
secondary_contents_db = JsonDb(
    db_path="./agno_json_data_2", knowledge_table="secondary_knowledge"
)

# Create knowledge bases
knowledge_base = Knowledge(
    name="Main Knowledge Base",
    description="A simple knowledge base",
    contents_db=contents_db,
    vector_db=vector_db,
)

main_agent = Agent(
    name="Main Agent",
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge_base,
    add_datetime_to_context=True,
    markdown=True,
    db=contents_db,
)

agent_os = AgentOS(
    description="Example app for basic agent with knowledge capabilities",
    id="knowledge-demo",
    agents=[main_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    """ Run your AgentOS:
    Now you can interact with your knowledge base using the API. Examples:
    - http://localhost:8001/knowledge/{id}/documents
    - http://localhost:8001/knowledge/{id}/documents/123
    - http://localhost:8001/knowledge/{id}/documents?agent_id=123
    - http://localhost:8001/knowledge/{id}/documents?limit=10&page=0&sort_by=created_at&sort_order=desc
    """
    agent_os.serve(app="multiple_knowledge_bases:app", reload=True)
