"""Create context items, use them with an Agent, then update and re-use."""

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
print()
agent.print_response("What is FastAPI?", stream=True, markdown=True)

# --- Update the prompt and re-use it ---

# Update the template to focus on security instead
context_manager.update(
    name="system_template",
    content="""You are {role} with expertise in {domain}.
Provide {output_style} responses focused on:
1. Security best practices
2. Common vulnerabilities
3. Mitigation strategies""",
    description="Security-focused system prompt template",
)

# Print the updated prompt
updated_prompt = context_manager.get(
    name="system_template",
    role="a security specialist",
    domain="web application security",
    output_style="detailed and practical",
)
print(updated_prompt)

# Create a new agent with the updated prompt
security_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    system_message=context_manager.get(
        name="system_template",
        role="a security specialist",
        domain="web application security",
        output_style="detailed and practical",
    ),
)
print()
security_agent.print_response("What are the top security concerns with FastAPI?", stream=True, markdown=True)
