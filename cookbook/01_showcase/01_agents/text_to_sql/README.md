# Text-to-SQL Agent

A self-learning SQL agent that queries Formula 1 data (1950-2020) and improves through accumulated knowledge. Customize and connect it to your own data to get one of the most powerful text-to-SQL agents on the market.

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

### 1. Clone the repo

```bash
git clone https://github.com/agno-agi/agno.git
cd agno
```

### 2. Create and activate a virtual environment

```bash
uv venv .venvs/text-to-sql --python 3.12
source .venvs/text-to-sql/bin/activate
```

### 3. Install Dependencies

```bash
uv pip install -r cookbook/01_showcase/01_agents/text_to_sql/requirements.in
```

### 4. Export API Keys

```bash
export OPENAI_API_KEY=your-openai-key
```

### 5. Start PostgreSQL

```bash
./cookbook/scripts/run_pgvector.sh
```

### 6. Check Setup

```bash
python cookbook/01_showcase/01_agents/text_to_sql/scripts/check_setup.py
```

### 7. Load Data and Knowledge

```bash
python cookbook/01_showcase/01_agents/text_to_sql/scripts/load_f1_data.py
python cookbook/01_showcase/01_agents/text_to_sql/scripts/load_knowledge.py
```

### 8. Run Examples

```bash
# Basic queries
python cookbook/01_showcase/01_agents/text_to_sql/examples/basic_queries.py

# Self-learning demonstration
python cookbook/01_showcase/01_agents/text_to_sql/examples/learning_loop.py

# Data quality edge cases
python cookbook/01_showcase/01_agents/text_to_sql/examples/edge_cases.py

# Evaluate accuracy
python cookbook/01_showcase/01_agents/text_to_sql/examples/evaluate.py
```

## Examples

| File | What You'll Learn |
|:-----|:------------------|
| `examples/basic_queries.py` | Simple aggregations, filtering, top-N queries |
| `examples/learning_loop.py` | Saving queries, knowledge retrieval, pattern reuse |
| `examples/edge_cases.py` | Multi-table joins, type handling, ambiguity |
| `examples/evaluate.py` | Automated accuracy testing |

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

## Learn More

- [Agno Documentation](https://docs.agno.com)
