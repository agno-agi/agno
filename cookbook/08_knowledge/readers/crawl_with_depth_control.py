"""This cookbook shows how to use WebsiteReader with different depth configurations.

Control crawl depth when scraping websites:
- max_depth=0: Only the starting URL (no link following)
- max_depth=1: Starting URL + direct links
- max_depth=N: Follow links N levels deep

Run: `python cookbook/08_knowledge/readers/crawl_with_depth_control.py`
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.website_reader import WebsiteReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create readers with different depth configurations
shallow_reader = WebsiteReader(max_depth=0, max_links=3)
deep_reader = WebsiteReader(max_depth=2, max_links=10)

print("WebsiteReader depth configurations:")
print(f"  Shallow reader: max_depth={shallow_reader.max_depth}")
print(f"  Deep reader: max_depth={deep_reader.max_depth}")

# Create knowledge base
knowledge = Knowledge(
    vector_db=PgVector(table_name="crawl_depth_example", db_url=db_url),
)

# Shallow crawl - just the main page (good for landing pages)
print("\nAdding docs page with shallow crawl (depth=0)...")
knowledge.insert(
    url="https://docs.agno.com/introduction",
    reader=WebsiteReader(max_depth=0, max_links=3),
)

# Deeper crawl - follow links (good for comprehensive documentation)
print("Adding agents docs with deeper crawl (depth=1)...")
knowledge.insert(
    url="https://docs.agno.com/agents/introduction",
    reader=WebsiteReader(max_depth=1, max_links=5),
)

# Create agent and query
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

print("\nQuerying the knowledge base...")
agent.print_response(
    "What topics are covered in the documentation?",
    markdown=True,
)
