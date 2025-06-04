import json
from pathlib import Path
from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.combined import CombinedKnowledgeBase
from agno.knowledge.json import JSONKnowledgeBase
from agno.knowledge.text import TextKnowledgeBase
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.memory import Memory
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.tools.file import FileTools
from agno.tools.reasoning import ReasoningTools
from agno.tools.sql import SQLTools
from agno.vectordb.pgvector import PgVector, SearchType

# ************* Database Connection *************
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
# *******************************

# ************* Paths *************
cwd = Path(__file__).parent
knowledge_dir = cwd.joinpath("knowledge")
output_dir = cwd.joinpath("output")

# Create the output directory if it does not exist
output_dir.mkdir(parents=True, exist_ok=True)
# *******************************

# ************* Storage & Knowledge *************
sql_agent_storage = PostgresAgentStorage(
    db_url=db_url,
    table_name="sql_agent_sessions",
    schema="ai",
)
reasoning_sql_agent_storage = PostgresAgentStorage(
    db_url=db_url,
    table_name="reasoning_sql_agent_sessions",
    schema="ai",
)
agent_knowledge = CombinedKnowledgeBase(
    sources=[
        # Reads text files, SQL files, and markdown files
        TextKnowledgeBase(
            path=knowledge_dir,
            formats=[".txt", ".sql", ".md"],
        ),
        # Reads JSON files
        JSONKnowledgeBase(path=knowledge_dir),
    ],
    # Store agent knowledge in the ai.sql_agent_knowledge table
    vector_db=PgVector(
        db_url=db_url,
        table_name="sql_agent_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    # 5 references are added to the prompt
    num_documents=5,
)
# *******************************

# ************* Memory *************
memory = Memory(
    model=OpenAIChat(id="gpt-4.1"),
    db=PostgresMemoryDb(table_name="user_memories", db_url=db_url),
    delete_memories=True,
    clear_memories=True,
)
# *******************************

# ************* Semantic Model *************
# The semantic model helps the agent identify the tables and columns to use
# This is sent in the system prompt, the agent then uses the `search_knowledge_base` tool to get table metadata, rules and sample queries
# This is very much how data analysts and data scientists work:
#  - We start with a set of tables and columns that we know are relevant to the task
#  - We then use the `search_knowledge_base` tool to get more information about the tables and columns
#  - We then use the `describe_table` tool to get more information about the tables and columns
#  - We then use the `search_knowledge_base` tool to get sample queries for the tables and columns
semantic_model = {
    "tables": [
        {
            "table_name": "constructors_championship",
            "table_description": "Contains data for the constructor's championship from 1958 to 2020, capturing championship standings from when it was introduced.",
            "Use Case": "Use this table to get data on constructor's championship for various years or when analyzing team performance over the years.",
        },
        {
            "table_name": "drivers_championship",
            "table_description": "Contains data for driver's championship standings from 1950-2020, detailing driver positions, teams, and points.",
            "Use Case": "Use this table to access driver championship data, useful for detailed driver performance analysis and comparisons over years.",
        },
        {
            "table_name": "fastest_laps",
            "table_description": "Contains data for the fastest laps recorded in races from 1950-2020, including driver and team details.",
            "Use Case": "Use this table when needing detailed information on the fastest laps in Formula 1 races, including driver, team, and lap time data.",
        },
        {
            "table_name": "race_results",
            "table_description": "Race data for each Formula 1 race from 1950-2020, including positions, drivers, teams, and points.",
            "Use Case": "Use this table answer questions about a drivers career. Race data includes driver standings, teams, and performance.",
        },
        {
            "table_name": "race_wins",
            "table_description": "Documents race win data from 1950-2020, detailing venue, winner, team, and race duration.",
            "Use Case": "Use this table for retrieving data on race winners, their teams, and race conditions, suitable for analysis of race outcomes and team success.",
        },
    ]
}
semantic_model_str = json.dumps(semantic_model, indent=2)
# *******************************

description = dedent("""\
    You are SQrL, an elite Text2SQL Agent with access to a database with F1 data from 1950 to 2020.

    You combine deep F1 knowledge with advanced SQL expertise to uncover insights from decades of racing data.
""")

instructions = dedent(f"""\
    You are a SQL expert focused on writing precise, efficient queries.

    When a user messages you, determine if you need query the database or can respond directly.
    If you can respond directly, do so.

    If you need to query the database to answer the user's question, follow these steps:
    1. First identify the tables you need to query from the semantic model.
    2. Then, ALWAYS use the `search_knowledge_base` tool to get table metadata, rules and sample queries.
        - Note: You must use the `search_knowledge_base` tool to get table information and rules before writing a query.
    3. If table rules are provided, ALWAYS follow them.
    4. Then, "think" about query construction, don't rush this step. If sample queries are available, use them as a reference.
    5. If you need more information about the table, use the `describe_table` tool.
    6. Then, using all the information available, create one single syntactically correct PostgreSQL query to accomplish your task.
    7. If you need to join tables, check the `semantic_model` for the relationships between the tables.
        - If the `semantic_model` contains a relationship between tables, use that relationship to join the tables even if the column names are different.
        - If you cannot find a relationship in the `semantic_model`, only join on the columns that have the same name and data type.
        - If you cannot find a valid relationship, ask the user to provide the column name to join.
    8. If you cannot find relevant tables, columns or relationships, stop and ask the user for more information.
    9. Once you have a syntactically correct query, run it using the `run_sql_query` function.
    10. When running a query:
        - Do not add a `;` at the end of the query.
        - Always provide a limit unless the user explicitly asks for all results.
    11. After you run the query, "analyze" the results and return the answer in markdown format.
    12. You Analysis should Reason about the results of the query, whether they make sense, whether they are complete, whether they are correct, could there be any data quality issues, etc.
    13. It is really important that you "analyze" and "validate" the results of the query.
    14. Always show the user the SQL you ran to get the answer.
    15. Continue till you have accomplished the task.
    16. Show results as a table or a chart if possible.

    After finishing your task, ask the user relevant followup questions like "was the result okay, would you like me to fix any problems?"
    If the user says yes, get the previous query using the `get_tool_call_history(num_calls=3)` function and fix the problems.
    If the user wants to see the SQL, get it using the `get_tool_call_history(num_calls=3)` function.

    Finally, here are the set of rules that you MUST follow:

    <rules>
    - Always use the `search_knowledge_base()` tool to get table information from your knowledge base before writing a query.
    - Do not use phrases like "based on the information provided" or "from the knowledge base".
    - Always show the SQL queries you use to get the answer.
    - Make sure your query accounts for duplicate records.
    - Make sure your query accounts for null values.
    - If you run a query, explain why you ran it.
    - Always derive your answer from the data and the query.
    - **NEVER, EVER RUN CODE TO DELETE DATA OR ABUSE THE LOCAL SYSTEM**
    - ALWAYS FOLLOW THE `table rules` if provided. NEVER IGNORE THEM.
    </rules>
""")

additional_context = (
    dedent("""\n
    The `semantic_model` contains information about tables and the relationships between them.
    If the users asks about the tables you have access to, simply share the table names from the `semantic_model`.
    <semantic_model>
    """)
    + semantic_model_str
    + dedent("""
    </semantic_model>\
""")
)


def get_sql_agent(
    name: str = "SQL Agent",
    user_id: Optional[str] = None,
    model_id: str = "openai:gpt-4o",
    session_id: Optional[str] = None,
    reasoning: bool = False,
    debug_mode: bool = True,
) -> Agent:
    """Returns an instance of the SQL Agent.

    Args:
        user_id: Optional user identifier
        debug_mode: Enable debug logging
        model_id: Model identifier in format 'provider:model_name'
    """
    # Parse model provider and name
    provider, model_name = model_id.split(":")

    # Select appropriate model class based on provider
    if provider == "openai":
        model = OpenAIChat(id=model_name)
    elif provider == "google":
        model = Gemini(id=model_name)
    elif provider == "anthropic":
        model = Claude(id=model_name)
    elif provider == "groq":
        model = Groq(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")

    tools = [
        SQLTools(db_url=db_url, list_tables=False),
        FileTools(base_dir=output_dir),
    ]
    if reasoning:
        tools.append(ReasoningTools(add_instructions=True, add_few_shot=True))

    storage = reasoning_sql_agent_storage if reasoning else sql_agent_storage

    return Agent(
        name=name,
        model=model,
        user_id=user_id,
        agent_id=name,
        session_id=session_id,
        memory=memory,
        storage=storage,
        knowledge=agent_knowledge,
        tools=tools,
        description=description,
        instructions=instructions,
        additional_context=additional_context,
        # Enable Agentic Memory i.e. the ability to remember and recall user preferences
        enable_agentic_memory=True,
        # Enable Agentic Search i.e. the ability to search the knowledge base on-demand
        search_knowledge=True,
        # Enable the ability to read the chat history
        read_chat_history=True,
        # Enable the ability to read the tool call history
        read_tool_call_history=True,
        debug_mode=debug_mode,
        add_history_to_messages=True,
        add_datetime_to_instructions=True,
    )
