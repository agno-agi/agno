"""Optimize context items using a model."""

from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

db = SqliteDb(db_file="tmp/context.db", context_table="context_items")

# Create context manager with a model for optimization
context_manager = ContextManager(
    db=db,
    model=OpenAIChat(id="gpt-4o"),
)

# Create a context item
original_prompt = """You are a helpful assistant.
Help users with their questions.
Be nice and friendly.
Answer clearly."""

context_manager.create(
    name="basic_prompt",
    content=original_prompt,
    description="Simple assistant prompt",
)

print("Original prompt:")
print(context_manager.get(name="basic_prompt"))

# Optimize the context (creates new version by default)
optimized = context_manager.optimize(
    name="basic_prompt",
    create_new_version=True,
    new_metadata={"optimized": True, "version": 2},
)

print("\nOptimized prompt:")
print(optimized)

# Optimize with custom instructions
custom_optimized = context_manager.optimize(
    name="basic_prompt",
    optimization_instructions="Make this prompt more professional and structured for technical audiences",
    create_new_version=False,
    new_metadata={"optimized": True, "version": 3, "style": "technical"},
)

print("\nCustom optimized prompt:")
print(custom_optimized)

# List all versions
all_items = context_manager.list()
pprint(all_items)
print(f"\nTotal prompts: {len(all_items)}")
