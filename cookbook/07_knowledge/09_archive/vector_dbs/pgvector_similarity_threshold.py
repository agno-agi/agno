from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_db = PgVector(
    table_name="vectors",
    db_url=db_url,
    similarity_threshold=0.2,
)

knowledge = Knowledge(
    name="Thai Recipes",
    description="Knowledge base with Thai recipes",
    vector_db=vector_db,
)

knowledge.insert(
    name="thai_curry",
    text_content="Thai green curry is a spicy dish made with coconut milk and green chilies.",
    skip_if_exists=True,
)
knowledge.insert(
    name="pad_thai",
    text_content="Pad Thai is a stir-fried rice noodle dish commonly served as street food in Thailand.",
    skip_if_exists=True,
)
knowledge.insert(
    name="weather",
    text_content="The weather forecast shows sunny skies with temperatures around 75 degrees.",
    skip_if_exists=True,
)

query = "What is the weather in Tokyo?"

results = vector_db.search(query, limit=5)
print(f"Query: '{query}'")
print(f"Chunks retrieved: {len(results)}")
for i, doc in enumerate(results):
    score = doc.meta_data.get("similarity_score", 0)
    print(f"{i + 1}. score={score:.3f}, {doc.content}")
