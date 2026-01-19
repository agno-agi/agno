# Text-to-SQL Agent

A self-learning SQL agent that queries Formula 1 data (1950-2020) and improves through accumulated knowledge.

## What Makes This Different

Most Text-to-SQL tutorials show you how to generate SQL from natural language. This one goes further:

1. **Knowledge-Based Query Generation** - The agent searches a knowledge base before writing SQL, ensuring consistent patterns
2. **Data Quality Handling** - Instead of cleaning messy data, the agent learns to handle inconsistencies (mixed types, date formats, naming conventions)
3. **Self-Learning Loop** - Users can save validated queries, which the agent retrieves for similar future questions

## What You'll Learn

| Concept | Description |
|:--------|:------------|
| **Semantic Model** | Define table metadata to guide query generation |
| **Knowledge Base** | Store and retrieve query patterns and data quality notes |
| **Data Quality Handling** | Handle type mismatches and inconsistencies without ETL |
| **Self-Learning** | Save validated queries to improve future responses |
| **Agentic Memory** | Remember user preferences across sessions |

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.in
```

### 2. Set API Keys

```bash
export OPENAI_API_KEY=your-openai-key      # Required for embeddings
export ANTHROPIC_API_KEY=your-anthropic-key # Required for Claude
```

### 3. Start PostgreSQL

```bash
./cookbook/scripts/run_pgvector.sh
```

### 4. Check Setup

```bash
python scripts/check_setup.py
```

### 5. Load Data and Knowledge

```bash
python scripts/load_f1_data.py
python scripts/load_knowledge.py
```

### 6. Run Examples

```bash
# Basic queries
python examples/basic_queries.py

# Self-learning demonstration
python examples/learning_loop.py

# Data quality edge cases
python examples/edge_cases.py

# Evaluate accuracy
python examples/evaluate.py
```

## Examples

| File | What You'll Learn |
|:-----|:------------------|
| `examples/basic_queries.py` | Simple aggregations, filtering, top-N queries |
| `examples/learning_loop.py` | Saving queries, knowledge retrieval, pattern reuse |
| `examples/edge_cases.py` | Multi-table joins, type handling, ambiguity |
| `examples/evaluate.py` | Automated accuracy testing |

## Architecture

```
text_to_sql/
├── agent.py              # Main agent configuration
├── semantic_model.py     # Table metadata (built from knowledge/)
├── tools/
│   └── save_query.py     # Custom tool for saving validated queries
├── knowledge/            # Table schemas and sample queries
│   ├── *.json            # Table metadata with data_quality_notes
│   └── common_queries.sql # Validated SQL patterns
├── scripts/
│   ├── check_setup.py    # Verify prerequisites
│   ├── load_f1_data.py   # Download and load F1 data
│   └── load_knowledge.py # Load knowledge base
└── examples/
    ├── basic_queries.py
    ├── learning_loop.py
    ├── edge_cases.py
    └── evaluate.py
```

## Data Quality Issues (By Design)

The F1 dataset has intentional inconsistencies that mirror real-world data:

| Issue | Tables Affected | How Agent Handles It |
|:------|:----------------|:---------------------|
| `position` type mismatch | INTEGER in `constructors_championship`, TEXT in others | Knowledge base notes specify correct comparison |
| Date format | TEXT `'DD Mon YYYY'` in `race_wins` | Uses `TO_DATE(date, 'DD Mon YYYY')` |
| Non-numeric positions | `'Ret'`, `'DSQ'`, `'DNS'`, `'NC'` in `race_results` | Filters with `position IN ('1', '2', '3')` |
| Column naming | `driver_tag` vs `name_tag` across tables | Knowledge base documents the variation |

The key insight: **document the issues, don't fix the data**. The agent learns to handle them through its knowledge base.

## Key Concepts

### Semantic Model

The semantic model defines available tables and their use cases. It's built dynamically from the knowledge JSON files:

```python
SEMANTIC_MODEL = {
    "tables": [
        {
            "table_name": "race_wins",
            "table_description": "Race winners and venue info (1950 to 2020).",
            "use_cases": ["Win counts by driver/team", "Wins by circuit"],
            "data_quality_notes": ["date is TEXT - use TO_DATE()"]
        },
        # ... built from knowledge/*.json
    ],
}
```

### Knowledge Base

The knowledge base contains:

- **Table metadata** (JSON): Column descriptions, types, and `data_quality_notes`
- **Sample queries** (SQL): Validated patterns with explanations

Before writing SQL, the agent **always** searches the knowledge base:

```
User: "Who won the most races in 2019?"
Agent: [searches knowledge base]
       [finds race_wins.json with date parsing note]
       [finds common_queries.sql with similar pattern]
       [generates SQL using learned patterns]
```

### Self-Learning Workflow

```
1. User asks question
2. Agent searches knowledge base
3. Agent generates and executes SQL
4. Agent validates results
5. Agent asks: "Want to save this query?"
6. If yes → saves with data_quality_notes
7. Future similar questions retrieve the pattern
```

### Agent Configuration

```python
sql_agent = Agent(
    name="SQL Agent",
    model=Claude(id="claude-sonnet-4-5-20250929"),
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

| Table | Years | Key Columns | Data Quality Notes |
|:------|:------|:------------|:-------------------|
| `constructors_championship` | 1958-2020 | year, position (INT), team, points | position is INTEGER |
| `drivers_championship` | 1950-2020 | year, position (TEXT), name, team, points | position is TEXT |
| `fastest_laps` | 1950-2020 | year, venue, name, driver_tag, lap_time | Uses `driver_tag` |
| `race_results` | 1950-2020 | year, position (TEXT), name, name_tag, points | position may be 'Ret', 'DSQ' |
| `race_wins` | 1950-2020 | venue, date (TEXT), name, name_tag, team | date needs TO_DATE() |

## Example Prompts

**Simple Queries:**
- "Who won the most races in 2019?"
- "List the top 5 drivers with the most championship wins"
- "What teams competed in 2020?"

**Data Quality Challenges:**
- "How many retirements were there in 2020?" (handles position='Ret')
- "Compare constructor wins vs championship position" (handles INT vs TEXT)
- "Show race wins by year" (handles date parsing)

**Complex Queries:**
- "How many races did each world champion win in their championship year?"
- "Which team outperformed their championship position based on race wins?"
- "Who is the most successful F1 driver of all time?"

## Requirements

- Python 3.11+
- PostgreSQL with pgvector
- OpenAI API key (for embeddings)
- Anthropic API key (for Claude)

## Learn More

- [Agno Documentation](https://docs.agno.com)
- [Knowledge Base Guide](https://docs.agno.com/knowledge)
- [SQL Tools Reference](https://docs.agno.com/tools/sql)
