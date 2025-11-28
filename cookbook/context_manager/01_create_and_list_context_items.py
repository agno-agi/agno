"""Create and list context items with variable substitution."""

from agno.context.manager import ContextManager
from agno.db.sqlite import SqliteDb
from rich.pretty import pprint

db = SqliteDb(db_file="tmp/context.db", context_table="context_items")
context_manager = ContextManager(db=db)

# Create context with variables using {variable} syntax
personalized_prompt = """You are {role} who specializes in {specialty}.
Your task is to help with {task_type} while maintaining a {tone} tone."""

context_manager.create(
    name="personalized_assistant",
    content=personalized_prompt,
    description="Customizable assistant prompt with variables",
)

# Get context with variable substitution
prompt = context_manager.get(
    name="personalized_assistant",
    role="a senior engineer",
    specialty="Python and AI systems",
    task_type="code reviews",
    tone="professional and helpful",
)

print(prompt)

# Create another context item
code_review = """Review the following code for:
- Security vulnerabilities
- Performance issues
- Best practices"""

context_manager.create(
    name="code_review_template",
    content=code_review,
    description="Code review template",
)

# List all items
all_items = context_manager.list()
pprint(all_items)

# Delete and clear
# context_manager.delete(name="personalized_assistant")
# all_items = context_manager.list()
# pprint(all_items)

# context_manager.clear()
# List after operations
# all_items = context_manager.list()
# pprint(all_items)
