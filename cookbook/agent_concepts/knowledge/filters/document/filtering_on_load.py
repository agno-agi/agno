from agno.agent import Agent
from agno.document import Document
from agno.knowledge.document import DocumentKnowledgeBase
from agno.vectordb.lancedb import LanceDb

# Initialize LanceDB
# By default, it stores data in /tmp/lancedb
vector_db = LanceDb(
    table_name="documents",
    uri="tmp/lancedb",  # You can change this path to store data elsewhere
)

# Create sample documents with different metadata
sample_documents = [
    Document(
        name="user_profile_jordan",
        id="doc_1",
        content="Jordan Mitchell is a Senior Software Engineer with 8 years of experience in full-stack development. Expertise in Python, JavaScript, React, and Node.js. Led multiple projects and mentored junior developers.",
    ),
    Document(
        name="user_profile_taylor",
        id="doc_2",
        content="Taylor Brooks is a Product Manager with 5 years of experience in agile development and product strategy. Skilled in user research, roadmap planning, and cross-functional team leadership.",
    ),
    Document(
        name="user_profile_morgan",
        id="doc_3",
        content="Morgan Lee is a UX Designer with 6 years of experience in user interface design and user experience research. Proficient in Figma, Adobe Creative Suite, and user testing methodologies.",
    ),
    Document(
        name="company_policy_remote",
        id="doc_4",
        content="Remote Work Policy: Employees are allowed to work from home up to 3 days per week. All remote work must be approved by direct supervisor and requires secure VPN connection.",
    ),
    Document(
        name="company_policy_vacation",
        id="doc_5",
        content="Vacation Policy: Full-time employees accrue 2.5 days of vacation per month. Maximum accrual is 30 days. Vacation requests must be submitted at least 2 weeks in advance.",
    ),
]

# Step 1: Initialize knowledge base and load documents with metadata
# ------------------------------------------------------------------------------
# When loading the knowledge base, we can attach metadata that will be used for filtering
# This metadata can include user IDs, document types, dates, or any other attributes

# Initialize the DocumentKnowledgeBase
knowledge_base = DocumentKnowledgeBase(
    vector_db=vector_db,
    num_documents=5,
)

# Load first document with Jordan Mitchell metadata
knowledge_base.load_document(
    document=sample_documents[0],
    metadata={"user_id": "jordan_mitchell", "year": 2025, "status": "active"},
    recreate=True,  # Set to True only for the first run, then set to False
)

# Load second document with Taylor Brooks metadata
knowledge_base.load_document(
    document=sample_documents[1],
    metadata={"user_id": "taylor_brooks", "year": 2025, "status": "active"},
)

# Load third document with Morgan Lee metadata
knowledge_base.load_document(
    document=sample_documents[2],
    metadata={"user_id": "morgan_lee", "year": 2025, "status": "active"},
)

# Load fourth document with HR department metadata
knowledge_base.load_document(
    document=sample_documents[3],
    metadata={"created_by": "hr_department", "year": 2025, "status": "current"},
)

# Load fifth document with HR department metadata
knowledge_base.load_document(
    document=sample_documents[4],
    metadata={"created_by": "hr_department", "year": 2025, "status": "current"},
)

# Step 2: Query the knowledge base with different filter combinations
# ------------------------------------------------------------------------------

# Initialize the Agent with the knowledge base and filters
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    knowledge_filters={"user_id": "jordan_mitchell"},
)
agent.print_response(
    "Tell me about Jordan Mitchell's experience and skills",
    markdown=True,
)
