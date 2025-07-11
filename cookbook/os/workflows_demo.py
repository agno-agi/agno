"""Simple example creating a session and using the AgentOS with a SessionManager to expose it"""

from agno.db.postgres.postgres import PostgresDb
from agno.os import AgentOS
from workflows.blog_post_generator import blog_generator_workflow

# Setup the database
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(
    db_url=db_url,
    session_table="sessions",
    user_memory_table="user_memory",
    eval_table="eval_runs",
    metrics_table="metrics",
    knowledge_table="knowledge_documents",
)


# Setup the Agno API App
agent_os = AgentOS(
    name="Workflows Demo",
    description="Demo app for workflows",
    os_id="demo",
    workflows=[blog_generator_workflow],
)
app = agent_os.get_app()


if __name__ == "__main__":
    """
    # Example topics
    The Rise of Artificial General Intelligence: Latest Breakthroughs
    How Quantum Computing is Revolutionizing Cybersecurity
    Sustainable Living in 2024: Practical Tips for Reducing Carbon Footprint
    The Future of Work: AI and Human Collaboration
    Space Tourism: From Science Fiction to Reality
    Mindfulness and Mental Health in the Digital Age
    The Evolution of Electric Vehicles: Current State and Future Trends
    Why Cats Secretly Run the Internet
    The Science Behind Why Pizza Tastes Better at 2 AM
    How Rubber Ducks Revolutionized Software Development
    """
    
    # Simple run to generate and record a session
    agent_os.serve(app="workflows_demo:app", reload=True)
    
