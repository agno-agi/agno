"""
Example script demonstrating the use of Neo4jTools with an Agno agent.
This script sets up an agent that can interact with a Neo4j database using natural language queries,
such as listing node labels or executing Cypher queries.

Requirements:
- A running Neo4j instance.
- The `neo4j` Python driver installed.
- Connection parameters (URI, username, password) set via environment variables or in the script.

Usage:
Run the script to create an agent and test queries like "What are the node labels in my graph?".
"""

import os
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.neo4j import Neo4jTools
from dotenv import load_dotenv

load_dotenv()

# Optionally load from environment or hardcode here
uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USERNAME", "neo4j")
password = os.getenv("NEO4J_PASSWORD", "your-password")

# Instantiate the toolkit
neo4j_toolkit = Neo4jTools(
    uri=uri,
    user=user,
    password=password,
    list_labels=True,
    list_relationships=True,
    get_schema=True,
    run_cypher=True,
)

description = """You are a Neo4j expert assistant who can help with all operations in a Neo4j database by understanding natural language context and translating it into Cypher queries."""

instructions = [
    "Analyze the user's context and convert it into Cypher queries that respect the database's current schema.",
    "Before performing any operation, query the current schema (e.g., check for existing nodes or relationships).",
    "If the necessary schema elements are missing, dynamically create or extend the schema using best practices, ensuring data integrity and consistency.",
    "If properties are required or provided for nodes or relationships, ensure that they are added correctly do not overwrite existing ones and do not create duplicates and do not create extra nodes.",
    "Optionally, use or implement a dedicated function to retrieve the current schema (e.g., via a 'get_schema' function).",
    "Ensure that all operations maintain data integrity and follow best practices.",
    "Intelligently create relationships if bi-directional relationships are required, and understand the users intent and create relationships accordingly.",
    "Intelligently handle queries that involve multiple nodes and relationships, understand has to be nodes, properties, and relationships and maintain best practices.",
    "Handle errors gracefully and provide clear feedback to the user.",
]

# Example: Use with AGNO Agent
agent = Agent(
    model=OpenAIChat(id="gpt-4"),
    tools=[neo4j_toolkit],
    show_tool_calls=True,
    markdown=True,
    description=description,
    instructions=instructions,
    debug_mode=True,
)

# Agent handles tool usage automatically via LLM reasoning
response = agent.run("What are the node labels in my graph?")
print(response.content)
