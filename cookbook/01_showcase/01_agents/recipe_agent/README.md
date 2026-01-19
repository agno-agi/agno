# Multi-Modal Recipe Agent

A multi-modal RAG agent that retrieves recipes from a knowledge base and generates step-by-step visual instruction manuals using image generation.

## Quick Start

### 1. Prerequisites

```bash
# Start PostgreSQL with PgVector
./cookbook/scripts/run_pgvector.sh

# Set API keys
export OPENAI_API_KEY=your-openai-api-key
export COHERE_API_KEY=your-cohere-api-key
```

### 2. Load Recipe Data

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/recipe_agent/scripts/load_recipes.py
```

### 3. Run Examples

```bash
# Basic recipe query
.venvs/demo/bin/python cookbook/01_showcase/01_agents/recipe_agent/examples/01_basic_recipe.py

# Visual guide with images
.venvs/demo/bin/python cookbook/01_showcase/01_agents/recipe_agent/examples/02_visual_guide.py
```

## Key Concepts

### Multi-Modal RAG

This agent combines:
- **RAG (Retrieval Augmented Generation)**: Searches a vector database for recipes
- **Image Generation**: Creates visual guides using DALL-E via OpenAITools

### Knowledge Base

Recipes are stored in PgVector with Cohere embeddings:

```python
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.vectordb.pgvector import PgVector

recipe_knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="recipe_documents",
        embedder=CohereEmbedder(id="embed-v4.0"),
    ),
)
```

### Visual Generation

The agent generates images for key cooking steps:

```python
from agent import get_visual_recipe

result = get_visual_recipe("Thai green curry")
print(result["recipe"])  # Recipe text
print(result["images"])  # List of saved image paths
```

## Architecture

```
User Query
    |
    v
[Recipe Agent (GPT-5.2)]
    |
    +---> Search Knowledge Base ---> PgVector (Cohere Embeddings)
    |
    +---> Generate Images ---> OpenAI DALL-E
    |
    v
Visual Recipe Guide (Text + Images)
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model and image generation
- `cohere` - Embeddings
- PostgreSQL with PgVector
