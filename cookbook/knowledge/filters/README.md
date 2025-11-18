# Filters

Filters help you selectively retrieve and process knowledge based on metadata, content patterns, or custom criteria for targeted information retrieval.

## Setup

```bash
pip install agno lancedb pandas
```

Set your API key:
```bash
export OPENAI_API_KEY=your_api_key
```

## Basic Integration

Filters integrate with the Knowledge system to enable targeted search:

```python
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

knowledge = Knowledge(vector_db=LanceDb(table_name="docs", uri="tmp/lancedb"))
knowledge.add_content(path="data.csv", metadata={"type": "sales", "quarter": "Q1"})

results = knowledge.search(
    query="revenue trends",
    filters={"quarter": "Q1"}
)
```

## Agent Integration

Agents can use filtered knowledge for targeted responses:

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    knowledge=knowledge,
    search_knowledge=True
)

# Agent automatically applies filters during knowledge search
response = agent.print_response(
    "What are the Q1 sales trends?",
    knowledge_filters={"quarter": "Q1"},
    markdown=True,
)
```

## Filter Expressions

For complex filtering logic, use `FilterExpr` objects from `agno.filters`:

```python
from agno.filters import EQ, IN, GT, LT, AND, OR, NOT

# Simple equality
filter = EQ("status", "published")

# Range queries
filter = AND(GT("views", 1000), LT("views", 10000))

# Complex logic
filter = OR(AND(EQ("type", "article"), GT("word_count", 500)), IN("priority", ["high", "urgent"]))

# Negation
filter = NOT(EQ("status", "archived"))

# Use with agent
agent.run("Query", knowledge_filters=[filter])
```

**Operators:**
- `EQ(key, value)` - Equality
- `IN(key, [values])` - Value in list
- `GT(key, value)` - Greater than
- `LT(key, value)` - Less than
- `AND(...)` - AND logic
- `OR(...)` - OR logic
- `NOT(...)` - NOT logic

## Supported Filter Types

- **[Agentic Filtering](./agentic_filtering.py)** - Agent integrated filtering
- **[Async Filtering](./async_filtering.py)** - Asynchronous filtering operations
- **[Basic Filtering](./filtering.py)** - Metadata-based filtering
- **[Filter Expressions](./filtering_with_conditions_on_agent.py)** - Complex filtering with FilterExpr
- **[API Filter Examples](../../agent_os/knowledge/knowledge_filters.py)** - Using filters through HTTP API
- **[Filtering on Load](./filtering_on_load.py)** - Set metadata during content loading
- **[Invalid Keys Handling](./filtering_with_invalid_keys.py)** - Filtering with error handling