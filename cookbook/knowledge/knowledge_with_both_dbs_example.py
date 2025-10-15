"""
Updated script with logging of all chunks from the LanceDB.

After loading the DataFrame, this prints:
- The schema (columns)
- All rows for inspection
- Specifically, all text chunks (assuming 'text' column; adjust if different)
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.lancedb import LanceDb, SearchType

# Create knowledge with BOTH vector_db and contents_db
knowledge = Knowledge(
    name="agno_knowledge_base",
    description="Knowledge base with both vector and content storage",
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="testpostgres",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
)

# Add content to the knowledge base
knowledge.add_content(
    text_content="Agno is a powerful framework for building AI agents with Python."
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions="Use the knowledge base to answer questions accurately.",
    markdown=True,
)

agent.print_response("What is Agno?", markdown=True)


import lance
import pandas as pd


def load_lance_db(path: str) -> pd.DataFrame:
    """
    Load a Lance database file from the given path and return it as a Pandas DataFrame.

    Args:
        path (str): The file path to the .lance file.

    Returns:
        pd.DataFrame: The content of the Lance dataset.

    Raises:
        ValueError: If the path is invalid or the dataset cannot be loaded.
    """
    try:
        dataset = lance.dataset(path)
        df = dataset.to_table().to_pandas()
        return df
    except Exception as e:
        raise ValueError(f"Failed to load Lance DB from {path}: {str(e)}")


print(knowledge.vector_db)

# Load the dataset
df = load_lance_db("tmp/lancedb/testpostgres.lance")

# LOG ALL CHUNKS
print("\n=== SCHEMA (Columns) ===")
print(df.columns.tolist())

print("\n=== ALL ROWS (Full DataFrame) ===")
print(df.to_string(index=False))  # Prints all rows without index for clean log

# Assuming chunks are in a 'text' column (common in vector DBs); adjust column name if needed
text_col = "text"  # Change to actual column, e.g., 'content' or 'metadata__text'
if text_col in df.columns:
    print(f"\n=== ALL TEXT CHUNKS (from '{text_col}' column) ===")
    for idx, chunk in enumerate(df[text_col], 1):
        print(f"Chunk {idx}: {chunk}")
else:
    print(f"\n=== NO '{text_col}' COLUMN FOUND. Available: {df.columns.tolist()} ===")
    # Fallback: Print all string columns
    string_cols = [col for col in df.columns if df[col].dtype == "object"]
    for col in string_cols:
        print(f"\n--- Chunks from '{col}' column ---")
        for idx, chunk in enumerate(df[col], 1):
            if isinstance(chunk, str):
                print(f"Chunk {idx}: {chunk}")
