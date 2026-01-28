"""Use context items with variable substitution in Agents and Teams."""

from agno.agent import Agent
from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

db = SqliteDb(db_file="tmp/context.db", context_table="context_items")
context_manager = ContextManager(db=db)

# Create context with variables
system_template = """You are {role} with expertise in {domain}.
Provide {output_style} responses that include:
1. Clear explanations
2. Practical examples
3. Best practices"""

context_manager.create(
    name="system_template",
    content=system_template,
    description="Flexible system prompt template",
)

# Use with Agent
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    system_message=context_manager.get(
        name="system_template",
        role="a technical educator",
        domain="web frameworks",
        output_style="concise and actionable",
    ),
)
agent.print_response("What is FastAPI?", stream=True, markdown=True, debug_mode=True)
