"""
Knowledge Base + Storage - Recipe Assistant with RAG
=====================================================
Give an agent persistent storage and a searchable knowledge base.

Key concepts:
- Knowledge: A searchable collection of documents stored in a vector database
- search_knowledge=True: Agent automatically searches knowledge before answering
- SqliteDb: Lightweight local database for conversation history (no Postgres needed)
- ChromaDb: Local vector database for embedding and searching documents
- Hybrid search: Combines semantic similarity with keyword matching for better results
- GeminiEmbedder: Uses Gemini's embedding model for vectorizing documents

Example prompts to try:
- "What Thai dishes can I make with chicken and coconut milk?"
- "How about a vegetarian option from the same cookbook?"
- "What desserts do you have in your knowledge base?"
"""

from pathlib import Path

from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.models.google import Gemini
from agno.vectordb.chroma import ChromaDb, SearchType
from db import gemini_agents_db

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

knowledge = Knowledge(
    name="Recipe Knowledge",
    vector_db=ChromaDb(
        collection="thai-recipes",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        # Hybrid search combines vector similarity + keyword matching
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(),
    ),
    # Store metadata about contents in the agent database
    contents_db=gemini_agents_db,
)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a recipe assistant with access to a Thai cookbook.

## Workflow

1. Search your knowledge base for relevant recipes
2. Answer the user's question based on what you find
3. Suggest variations or substitutions when appropriate

## Rules

- Always search knowledge before answering
- Mention specific recipe names from the cookbook
- Suggest ingredient substitutions for dietary restrictions\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
recipe_agent = Agent(
    name="Recipe Assistant",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    knowledge=knowledge,
    # Agent automatically searches knowledge when relevant
    search_knowledge=True,
    db=gemini_agents_db,
    # Include last 3 conversation turns for context
    add_history_to_context=True,
    num_history_runs=3,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Step 1: Load recipe knowledge into the knowledge base
    print("Loading recipe knowledge...")
    knowledge.insert(
        text_content="""\
## Thai Recipe Collection

### Tom Kha Gai (Chicken Coconut Soup)
Ingredients: chicken breast, coconut milk, galangal, lemongrass, kaffir lime leaves,
fish sauce, lime juice, mushrooms, chili. Creamy and aromatic, balances sour and savory.

### Green Curry (Gaeng Keow Wan)
Ingredients: green curry paste, coconut milk, chicken or tofu, Thai basil, bamboo shoots,
eggplant, fish sauce, palm sugar. Rich and fragrant with a moderate heat level.

### Pad Thai
Ingredients: rice noodles, shrimp or chicken, eggs, bean sprouts, peanuts, lime,
tamarind paste, fish sauce, sugar. The classic Thai stir-fried noodle dish.

### Som Tum (Green Papaya Salad)
Ingredients: green papaya, cherry tomatoes, green beans, peanuts, dried shrimp,
garlic, chili, lime juice, fish sauce, palm sugar. Refreshing and spicy.

### Massaman Curry
Ingredients: massaman curry paste, coconut milk, beef or chicken, potatoes, onions,
peanuts, tamarind, cinnamon, cardamom. A mild, rich curry with Indian influences.

### Mango Sticky Rice (Khao Niew Mamuang)
Ingredients: glutinous rice, ripe mango, coconut milk, sugar, salt.
A beloved Thai dessert, sweet and creamy.
""",
    )

    # Step 2: Ask questions about the recipes
    print("\n--- Session 1: First question ---\n")
    recipe_agent.print_response(
        "What Thai dishes can I make with chicken and coconut milk?",
        user_id="foodie@example.com",
        session_id="session_1",
        stream=True,
    )

    # Step 3: Follow-up in the same session (agent has context)
    print("\n--- Session 1: Follow-up ---\n")
    recipe_agent.print_response(
        "How about a vegetarian option from the same cookbook?",
        user_id="foodie@example.com",
        session_id="session_1",
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Loading knowledge from different sources:

1. From a URL
   knowledge.insert(url="https://example.com/docs.pdf")

2. From a local file
   knowledge.insert(path="path/to/document.pdf")

3. From text directly (this example)
   knowledge.insert(text_content="Your content here...")

4. Named content (prevents duplicates)
   knowledge.insert(name="recipes-v1", text_content="...")

Knowledge vs File Search (step 15):

Knowledge (this example):
- Local vector DB (ChromaDb, PgVector)
- You control embedding, chunking, search
- Hybrid search (semantic + keyword)
- Best for: production, large datasets, custom logic

File Search (step 15):
- Fully managed by Google
- Automatic chunking and embedding
- Built-in citations
- Best for: quick prototyping, small datasets
"""
