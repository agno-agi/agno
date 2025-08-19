# Search Types

Search strategies determine how your agents find relevant information in knowledge bases. The right approach balances semantic understanding, keyword precision, and performance for optimal retrieval quality.

## Agent Integration

All search types work seamlessly with Agno agents. The search strategy determines how your agent finds relevant information:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,  # Your knowledge base with chosen search type
    search_knowledge=True,
)

agent.print_response("Ask anything - the search type determines how I find answers")
```

This pattern works with all search types shown below - just replace `knowledge` with your configured knowledge base.

## Search Implementations

### 1. Vector Search (`vector_search.py`)

**How it works**: Converts queries and documents into vector embeddings, then finds semantically similar content using cosine similarity or other distance metrics.

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector, SearchType

# Configure vector search
vector_db = PgVector(
    table_name="recipes",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    search_type=SearchType.vector  # Pure vector search
)

knowledge = Knowledge(
    name="Vector Search Knowledge Base",
    vector_db=vector_db,
)

# Add content for vector search
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"type": "recipe", "cuisine": "thai"}
)

# Vector search examples
print("=== Vector Search Examples ===")

# Semantic queries that vector search handles well
queries = [
    "How to prepare spicy coconut soup?",           # Concept: spicy + coconut + soup
    "What ingredients make food taste creamy?",     # Concept: creaminess
    "Traditional cooking methods from Thailand",     # Concept: traditional + Thai
    "Vegetarian protein alternatives",             # Concept: vegetarian + protein
]

for query in queries:
    results = knowledge.search(query, limit=3)
    print(f"\nQuery: {query}")
    print(f"Results: {len(results)} relevant documents found")
    # Results will include semantically related content even if exact words don't match
```

**Use cases**:
- **Conceptual queries**: "How to improve team productivity?" 
- **Synonym matching**: "automobile" matches "car" content
- **Cross-lingual understanding**: English query finds content in other languages
- **Contextual search**: Understanding query intent beyond keywords

### 2. Keyword Search (`keyword_search.py`)

**How it works**: Traditional text-based search using inverted indexes, TF-IDF scoring, and boolean operators.

```python
from agno.vectordb.pgvector import PgVector, SearchType

# Configure keyword search
keyword_db = PgVector(
    table_name="recipes",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", 
    search_type=SearchType.keyword  # Pure keyword search
)

knowledge = Knowledge(
    name="Keyword Search Knowledge Base",
    vector_db=keyword_db,
)

# Add the same content for comparison
knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"type": "recipe", "cuisine": "thai"}
)

print("=== Keyword Search Examples ===")

# Queries where keyword search excels
queries = [
    "Tom Yum Goong recipe",                    # Specific dish name
    "coconut milk AND lemongrass",            # Boolean operators
    "\"fish sauce\" OR \"soy sauce\"",        # Exact phrases with alternatives
    "ingredients: galangal, lime leaves",     # Specific ingredient lists
]

for query in queries:
    results = knowledge.search(query, limit=3)
    print(f"\nQuery: {query}")
    print(f"Results: {len(results)} matching documents")
    # Results will match exact terms and phrases precisely
```

**Advanced keyword search techniques**:
```python
# Boolean operators and phrase matching
advanced_queries = [
    'recipe AND (chicken OR beef) NOT pork',     # Boolean logic
    '"green curry paste" AND coconut',          # Exact phrase + keyword
    'ingredient*',                              # Wildcard matching
    'spic* OR hot*',                           # Multiple wildcards
]

# Field-specific search (if supported)
field_queries = [
    'title:curry',                             # Search in title field only
    'ingredients:coconut AND title:soup',       # Multiple field constraints
]
```

**Use cases**:
- **Entity matching**: Product codes, names, IDs
- **Technical documentation**: API endpoints, function names
- **Legal and compliance**: Specific terms, regulations, codes
- **Precise phrase searches**: Quotes, specific instructions

### 3. Hybrid Search (`hybrid_search.py`)

**How it works**: Combines vector and keyword search results using weighted scoring, reciprocal rank fusion, or learned ranking models.

```python
from agno.vectordb.pgvector import PgVector, SearchType

# Configure hybrid search  
hybrid_db = PgVector(
    table_name="recipes",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    search_type=SearchType.hybrid,  # Combines vector + keyword
    # Optional: Configure hybrid parameters
    hybrid_alpha=0.7,  # 0.7 vector weight, 0.3 keyword weight
)

knowledge = Knowledge(
    name="Hybrid Search Knowledge Base", 
    vector_db=hybrid_db,
)

knowledge.add_content(
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"type": "recipe", "cuisine": "thai"}
)

print("=== Hybrid Search Examples ===")

# Queries that benefit from hybrid approach
queries = [
    "Tom Yum Goong preparation steps",         # Exact name + concept
    "spicy coconut soup with lemongrass",     # Keywords + semantic intent
    "traditional Thai cooking techniques",     # Concepts + specific terms
    "how to balance sweet and sour flavors",  # Semantic query + specific terms
]

for query in queries:
    results = knowledge.search(query, limit=3)
    print(f"\nQuery: {query}")
    print(f"Results: {len(results)} hybrid-ranked documents")
    # Results combine semantic relevance with keyword matching
```

**Hybrid search configuration**:
```python
# Fine-tune hybrid search parameters
optimized_hybrid_db = PgVector(
    table_name="optimized_recipes",
    db_url=db_url,
    search_type=SearchType.hybrid,
    hybrid_alpha=0.6,           # Adjust vector vs keyword balance
    keyword_boost=1.2,          # Boost keyword scores
    vector_boost=0.8,           # Adjust vector scores
    min_keyword_score=0.1,      # Minimum keyword relevance threshold
    reciprocal_rank_k=60,       # RRF parameter for score fusion
)
```
