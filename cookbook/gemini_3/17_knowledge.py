"""
17. Knowledge Base + Storage
============================
Add persistent storage and a searchable knowledge base.
The agent can recall conversations and use domain knowledge to answer questions.

This builds on earlier steps by adding:
- Storage: SqliteDb for conversation history across sessions
- Knowledge: ChromaDb with hybrid search for domain knowledge
- Embeddings: GeminiEmbedder for vector similarity

Run:
    python cookbook/gemini_3/17_knowledge.py

Example prompt:
    "What Thai dishes can I make with chicken and coconut milk?"
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.models.google import Gemini
from agno.vectordb.chroma import ChromaDb, SearchType

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Storage and Knowledge
# ---------------------------------------------------------------------------
db = SqliteDb(db_file=str(WORKSPACE / "gemini_agents.db"))

knowledge = Knowledge(
    name="Recipe Knowledge",
    vector_db=ChromaDb(
        collection="thai-recipes",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(),
    ),
    contents_db=db,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
recipe_agent = Agent(
    name="Recipe Assistant",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a recipe assistant with access to a Thai cookbook.

## Workflow

1. Search your knowledge base for relevant recipes
2. Answer the user's question based on what you find
3. Suggest variations or substitutions when appropriate

## Rules

- Always search knowledge before answering
- Mention specific recipe names from the cookbook
- Suggest ingredient substitutions for dietary restrictions\
""",
    knowledge=knowledge,
    search_knowledge=True,
    db=db,
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
