"""Use context items with variable substitution in Teams."""

from agno.agent import Agent
from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team.team import Team

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

# Create team members with context-based system messages
researcher = Agent(
    name="Researcher",
    model=OpenAIChat(id="gpt-4o"),
    system_message=context_manager.get(
        name="system_template",
        role="a research analyst",
        domain="AI technologies",
        output_style="detailed and well-researched",
    ),
)

writer = Agent(
    name="Writer",
    model=OpenAIChat(id="gpt-4o"),
    system_message=context_manager.get(
        name="system_template",
        role="a technical writer",
        domain="software documentation",
        output_style="clear and structured",
    ),
)

team = Team(
    name="Content Team",
    model=OpenAIChat(id="gpt-4o"),
    members=[researcher, writer],
)

team.print_response(
    "Explain context managers in AI", stream=True, markdown=True, debug_mode=True
)
