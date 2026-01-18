"""
Example showing how to use JSON as output schema.

Also how to temporarily override the schema for a single run,
with automatic restoration afterwards.

Note: JSON schemas must be in the provider's expected format.
For example, OpenAI expects:
{"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from rich.pretty import pprint

person_schema = {
    "type": "json_schema",
    "json_schema": {
        "name": "PersonInfo",
        "schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Person's full name"},
                "age": {"type": "integer", "description": "Person's age"},
                "occupation": {"type": "string", "description": "Person's occupation"},
            },
            "required": ["name", "age", "occupation"],
            "additionalProperties": False,
        },
    },
}

book_schema = {
    "type": "json_schema",
    "json_schema": {
        "name": "BookInfo",
        "schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Book title"},
                "author": {"type": "string", "description": "Author name"},
                "year": {"type": "integer", "description": "Publication year"},
            },
            "required": ["title", "author", "year"],
            "additionalProperties": False,
        },
    },
}

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    output_schema=person_schema,
    markdown=False,
)

person_response = agent.run("Tell me about Albert Einstein", stream=False)
assert isinstance(person_response.content, dict)
pprint(person_response.content)

# schema override
print(f"Schema before override: {agent.output_schema['json_schema']['name']}")
book_response = agent.run(
    "Tell me about '1984' by George Orwell", output_schema=book_schema, stream=False
)
assert isinstance(book_response.content, dict)
pprint(book_response.content)
print(f"Schema after override: {agent.output_schema['json_schema']['name']}")
assert agent.output_schema == person_schema
