from agno.agent import Agent
from agno.context import ContextManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools.hackernews import HackerNewsTools


# Initialize database context manager
db = SqliteDb(db_file="tmp/context.db")
context = ContextManager(db=db)


# Create a content
content_researcher = context.create(
    name="instructions_researcher",
    content=(
        "You are {role} specializing in {domain}.\n\n"
        "Research focus: {focus}\n\n"
        "{instructions}"
    ),
    label="production",
    description="Research agent instructions",
)
print(f"Created content: instructions_researcher (label: production, id: {content_researcher})\n")


# Get the content (non-strict mode by default)
prompt = context.get(
    context_name="instructions_researcher",
    label="production",
    role="a tech researcher",
    domain="emerging technologies",
    focus="RAG systems",
    instructions="Focus on popular stories from the last 24 hours.",
)
print(f"Rendered content:\n{prompt}\n")


# List all content items
content_items = context.list()
print(f"Total content items: {len(content_items)}\n")
for item in content_items:
    print(f"{item.name} (label: {item.label})\n")


# Update content
context.update(
    context_name="instructions_researcher",
    label="production",
    content="You are {role} working on {project}. {task} Priority: {priority}",
    description="Updated with priority field",
)


# Get updated content
updated_prompt = context.get(
    context_name="instructions_researcher",
    label="production",
    role="a data analyst",
    project="sales analysis",
    task="Create quarterly report",
    priority="high",
)
print(f"Updated rendered content:\n{updated_prompt}\n")

# Test non-strict mode (missing variables)
non_strict_prompt = context.get(
    context_name="instructions_researcher",
    label="production",
    role="a data analyst",
    project="sales analysis",
)
print(f"Testing prompt in non strict mode (placeholders remain):\n{non_strict_prompt}\n")

# Test strict mode
context_strict_mode = ContextManager(db=db, strict_mode=True)

context_strict_mode.create(
    name="strict_template",
    content="Name: {name}, Email: {email}",
    label="strict",
)

# This works - all variables provided
strict_prompt = context_strict_mode.get(
    context_name="strict_template",
    label="strict",
    name="John Doe",
    email="john@example.com",
)
print(f"Strict mode (all variables): {strict_prompt}\n")


# This fails - missing variables
try:
    strict_prompt = context_strict_mode.get(
        context_name="strict_template",
        label="strict",
        name="John Doe",
        # Missing: email
    )
    print(f"Strict mode (missing variables): {strict_prompt}\n")
except ValueError as e:
    print(f"Error: {e}\n")


# Optimization example
# Add model to existing context manager for optimization
context.model = OpenAIChat(id="gpt-4o-mini")
context.optimization_instructions = "Make the content more concise and smooth while keeping all variables intact."


original_content_id = context.create(
    name="agent_instructions",
    content=(
        "You are {role} who works in the field of {domain}. "
        "Your primary responsibility is to {task}. "
        "When analyzing data, you should focus on {focus}. "
        "Please provide {output_format} as your response."
    ),
    label="v1",
)
# Get without variables to show the template
original_content = context.get(context_name="agent_instructions", label="v1")
print(f"Original content: agent_instructions (label: v1, id: {original_content_id})\n{original_content}\n")


optimized_content = context.optimize(
    context_name="agent_instructions",
    label="v1",
    create_new_version=True,
    new_label="v1_optimized",
)
print(f"Optimized content: agent_instructions (label: v1_optimized)\n{optimized_content}\n")


# List all versions including optimized
all_versions = context.list()
print(f"Total versions after optimization: {len(all_versions)}\n")
for versions in all_versions:
    print(f"{versions.name} (label: {versions.label}, version: {versions.version}, parent: {versions.parent_id})\n")


# Using content with agents (using optimized prompt)
agent_instructions = context.get(
    context_name="agent_instructions",
    label="v1_optimized",
    role="a HackerNews research assistant",
    domain="technology news",
    task="finding and summarizing AI-related stories",
    focus="relevance and recency",
    output_format="a summary of the top 3 stories",
)

agent = Agent(
    name="HN Researcher",
    instructions=agent_instructions,
    tools=[HackerNewsTools()],
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)
print(f"\nAgent instructions:\n{agent_instructions}\n")

# Run the agent
agent_response = agent.run("Find the top 3 AI stories on HackerNews")
print(f"Agent response:\n{agent_response.content}\n")

context_list = context_strict_mode.list()
print(f"Prompts in context_strict_mode: {len(context_list)}\n")

# Delete content
context_strict_mode.delete(context_name="strict_template", label="strict")
print("Deleted strict_template from context_strict_mode\n")

# Verify deletion from both contexts
context_list = context_strict_mode.list()
print(f"Remaining in context_strict_mode after deletion: {len(context_list)}\n")
