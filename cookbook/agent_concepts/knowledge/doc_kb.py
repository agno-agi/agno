from agno.agent import Agent
from agno.document.base import Document
from agno.knowledge.document import DocumentKnowledgeBase
from agno.vectordb.pgvector import PgVector

fun_facts = """
- Earth is the third planet from the Sun and the only known astronomical object to support life.
- Approximately 71% of Earth's surface is covered by water, with the Pacific Ocean being the largest.
- The Earth's atmosphere is composed mainly of nitrogen (78%) and oxygen (21%), with traces of other gases.
- Earth rotates on its axis once every 24 hours, leading to the cycle of day and night.
- The planet has one natural satellite, the Moon, which influences tides and stabilizes Earth's axial tilt.
- Earth's tectonic plates are constantly shifting, leading to geological activities like earthquakes and volcanic eruptions.
- The highest point on Earth is Mount Everest, standing at 8,848 meters (29,029 feet) above sea level.
- The deepest part of the ocean is the Mariana Trench, reaching depths of over 11,000 meters (36,000 feet).
- Earth has a diverse range of ecosystems, from rainforests and deserts to coral reefs and tundras.
- The planet's magnetic field protects life by deflecting harmful solar radiation and cosmic rays.
"""


# Load documents from the data/docs directory
documents = [Document(content=fun_facts)]

# Database connection URL
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the loaded documents
knowledge_base = DocumentKnowledgeBase(
    documents=documents,
    vector_db=PgVector(
        table_name="documents",
        db_url=db_url,
    ),
)

# Load the knowledge base
knowledge_base.load(recreate=False)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
)

# Ask the agent about the knowledge base
agent.print_response(
    "Ask me about something from the knowledge base about earth", markdown=True
)
