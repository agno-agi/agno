"""Use strict mode to enforce variable requirements."""

from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="tmp/context.db", context_table="context_items")

# Create context manager with strict mode
context_manager = ContextManager(db=db, strict_mode=True)

# Create context with required variables
template = """You are {role} specializing in {domain}.
Your expertise level is {level} and you provide {style} responses."""

context_manager.create(
    name="strict_template",
    content=template,
    description="Template requiring all variables",
)

# This works - all variables provided
prompt = context_manager.get(
    name="strict_template",
    role="an engineer",
    domain="databases",
    level="senior",
    style="detailed",
)
print(prompt)

# This will raise ValueError - missing variables (domain, level, style)
# prompt = context_manager.get(
#     name="strict_template",
#     role="an engineer",
# )

# Non-strict mode (default) - missing variables stay as placeholders
context_manager_flexible = ContextManager(db=db, strict_mode=False)
prompt = context_manager_flexible.get(
    name="strict_template",
    role="an engineer",
    # Missing variables will remain as {domain}, {level}, {style}
)
print(f"\nNon-strict mode with missing variables:\n{prompt}")
