"""
Text-to-SQL Agent
=================

A self-learning SQL agent that queries Formula 1 data (1950-2020).

Run:
    python agent.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.tools.sql import SQLTools
from agno.vectordb.pgvector import PgVector, SearchType
from semantic_model import SEMANTIC_MODEL_STR
from tools.save_query import save_validated_query, set_knowledge

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

sql_agent_db = PostgresDb(db_url=DB_URL)

sql_agent_knowledge = Knowledge(
    name="SQL Agent Knowledge",
    vector_db=PgVector(
        db_url=DB_URL,
        table_name="sql_agent_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=5,
    contents_db=sql_agent_db,
)

set_knowledge(sql_agent_knowledge)

system_message = f"""\
You are a Text-to-SQL agent with access to a PostgreSQL database containing Formula 1 data (1950-2020).

WORKFLOW
--------
1. Identify relevant tables from the semantic model
2. Search the knowledge base before writing SQL
3. Follow data_quality_notes exactly (type mismatches, date formats, etc.)
4. Execute the query and validate results
5. After success, ask if the user wants to save the query to the knowledge base

DATA QUALITY NOTES
------------------
- position: INTEGER in constructors_championship, TEXT elsewhere
- date in race_wins: TEXT format 'DD Mon YYYY' - use TO_DATE() to parse
- position in race_results: may contain 'Ret', 'DSQ', 'DNS', 'NC'
- Column names vary: driver_tag vs name_tag across tables

SQL RULES
---------
- Always search knowledge base first
- Always show the SQL query used
- Default LIMIT 50
- Never SELECT *
- Include ORDER BY for top-N queries
- Never run destructive queries

<semantic_model>
{SEMANTIC_MODEL_STR}
</semantic_model>
"""

sql_agent = Agent(
    name="SQL Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    db=sql_agent_db,
    knowledge=sql_agent_knowledge,
    system_message=system_message,
    tools=[
        SQLTools(db_url=DB_URL),
        ReasoningTools(add_instructions=True),
        save_validated_query,
    ],
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    search_knowledge=True,
    add_history_to_context=True,
    num_history_runs=5,
    read_chat_history=True,
    read_tool_call_history=True,
    markdown=True,
)

if __name__ == "__main__":
    sql_agent.cli_app(stream=True)
