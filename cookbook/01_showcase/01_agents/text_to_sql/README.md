# Text-to-SQL Agent

A production-ready Text-to-SQL tutorial demonstrating a self-learning SQL agent that queries Formula 1 data (1950-2020) and improves through accumulated knowledge.

## What You'll Learn

| Concept | Description |
|:--------|:------------|
| **Semantic Model** | Define table metadata to guide query generation |
| **Knowledge Base** | Store and retrieve query patterns for consistency |
| **Self-Learning** | Save validated queries to improve future responses |
| **Agentic Memory** | Remember user preferences across sessions |
| **Reasoning Tools** | Step-by-step query construction and validation |

## Quick Start

### 1. Start PostgreSQL

```bash
./cookbook/scripts/run_pgvector.sh
```

### 2. Load F1 Data

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/text_to_sql/scripts/load_f1_data.py
```

### 3. Load Knowledge Base

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/text_to_sql/scripts/load_knowledge.py
```

### 4. Run Examples

```bash
# Basic queries
.venvs/demo/bin/python cookbook/01_showcase/01_agents/text_to_sql/examples/01_basic_queries.py

# Self-learning demonstration
.venvs/demo/bin/python cookbook/01_showcase/01_agents/text_to_sql/examples/02_learning_loop.py

# Complex queries and edge cases
.venvs/demo/bin/python cookbook/01_showcase/01_agents/text_to_sql/examples/03_edge_cases.py
```

## Examples

| # | File | What You'll Learn |
|:--|:-----|:------------------|
| 01 | `examples/01_basic_queries.py` | Simple aggregations, filtering, top-N queries |
| 02 | `examples/02_learning_loop.py` | Saving queries, knowledge retrieval |
| 03 | `examples/03_edge_cases.py` | Multi-table joins, time-series, ambiguity |

## Architecture

```
text_to_sql/
├── agent.py              # Main agent configuration
├── semantic_model.py     # Table metadata definitions
├── tools/
│   └── save_query.py     # Custom tool for saving queries
├── knowledge/            # Table schemas and sample queries
├── scripts/
│   ├── load_f1_data.py   # Download and load F1 data
│   └── load_knowledge.py # Load knowledge base
└── examples/
    ├── 01_basic_queries.py
    ├── 02_learning_loop.py
    └── 03_edge_cases.py
```

## Key Concepts

### Semantic Model

The semantic model defines available tables and their use cases:

```python
SEMANTIC_MODEL = {
    "tables": [
        {
            "table_name": "race_wins",
            "table_description": "Race winners and venue info (1950 to 2020).",
            "use_cases": [
                "Win counts by driver/team",
                "Wins by circuit or country",
            ],
        },
        # ... more tables
    ],
}
```

The agent uses this to identify relevant tables before writing SQL.

### Knowledge-Based Query Generation

The knowledge base contains:
- **Table metadata** (JSON): Column descriptions, data types, tips
- **Sample queries** (SQL): Validated query patterns with explanations

Before writing SQL, the agent always searches the knowledge base for relevant patterns.

### Self-Learning Workflow

1. User asks a question
2. Agent generates and executes SQL
3. Agent validates results and asks if user wants to save
4. If confirmed, query is saved with metadata:
   - Name and description
   - Original question
   - SQL query
   - Notes and caveats
5. Future similar questions retrieve the saved pattern

### Agent Configuration

```python
sql_agent = Agent(
    name="SQL Agent",
    model=Claude(id="claude-sonnet-4-5"),
    knowledge=sql_agent_knowledge,
    tools=[
        SQLTools(db_url=DB_URL),
        ReasoningTools(add_instructions=True),
        save_validated_query,
    ],
    enable_agentic_memory=True,
    search_knowledge=True,
    read_tool_call_history=True,
)
```

## Available Tables

| Table | Years | Description |
|:------|:------|:------------|
| `constructors_championship` | 1958-2020 | Constructor championship standings |
| `drivers_championship` | 1950-2020 | Driver championship standings |
| `fastest_laps` | 1950-2020 | Fastest lap records per race |
| `race_results` | 1950-2020 | Per-race results with positions and points |
| `race_wins` | 1950-2020 | Race winners and venue info |

## Example Prompts

**Simple Queries:**
- "Who won the most races in 2019?"
- "List the top 5 drivers with the most championship wins"
- "What teams competed in 2020?"

**Complex Queries:**
- "Compare Ferrari vs Mercedes points from 2015-2020"
- "How many races did each world champion win in their championship year?"
- "Which team outperformed their championship position based on race wins?"

**Analytical Queries:**
- "Who is the most successful F1 driver of all time?"
- "Show me drivers who improved their championship position year over year"

## Requirements

- Python 3.11+
- PostgreSQL with pgvector
- OpenAI API key (for embeddings)
- Anthropic API key (for Claude)

## Environment Variables

```bash
export OPENAI_API_KEY=your-openai-key
export ANTHROPIC_API_KEY=your-anthropic-key
```

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [Knowledge Base Guide](https://docs.agno.com/knowledge)
- [SQL Tools Reference](https://docs.agno.com/tools/sql)
