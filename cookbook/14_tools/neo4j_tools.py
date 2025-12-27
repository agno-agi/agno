"""
Example script demonstrating the use of Neo4jTools with an Agno agent.
This script sets up an agent that can interact with a Neo4j database using natural language queries,
such as listing node labels or executing Cypher queries.

## Setting up Neo4j Locally

### Option 1: Using Docker (Recommended)

1. **Install Docker** if you haven't already from https://www.docker.com/

2. **Run Neo4j in Docker:**
   ```bash
   docker run \
       --name neo4j \
       -p 7474:7474 -p 7687:7687 \
       -d \
       -v $HOME/neo4j/data:/data \
       -v $HOME/neo4j/logs:/logs \
       -v $HOME/neo4j/import:/var/lib/neo4j/import \
       -v $HOME/neo4j/plugins:/plugins \
       --env NEO4J_AUTH=neo4j/password \
       neo4j:latest
   ```

3. **Access Neo4j Browser:** Open http://localhost:7474 in your browser
   - Username: `neo4j`
   - Password: `password`

### Option 2: Native Installation

1. **Download Neo4j Desktop** from https://neo4j.com/download/
2. **Install and create a new database**
3. **Start the database** and note the connection details

### Option 3: Using Neo4j Community Edition

1. **Download** from https://neo4j.com/download-center/#community
2. **Extract and run:**
   ```bash
   tar -xf neo4j-community-*-unix.tar.gz
   cd neo4j-community-*
   ./bin/neo4j start
   ```

## Python Setup

1. **Install required packages:**
   ```bash
   pip install neo4j python-dotenv
   ```

2. **Set environment variables** (create a `.env` file in your project root):
   ```env
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USERNAME=neo4j
   NEO4J_PASSWORD=password
   ```

## Usage

1. **Ensure Neo4j is running** (check http://localhost:7474)
2. **Run this script** to create an agent that can interact with your Neo4j database
3. **Test with queries** like "What are the node labels in my graph?" or "Show me the database schema"

## Troubleshooting

- **Connection refused:** Make sure Neo4j is running on the correct port (7687)
- **Authentication failed:** Verify your username/password in the Neo4j browser first
- **Import errors:** Install the neo4j driver with `pip install neo4j`
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
password = os.getenv("NEO4J_PASSWORD", "password")

# Example 1: All functions enabled (default)
neo4j_toolkit_all = Neo4jTools(
    uri=uri,
    user=user,
    password=password,
    all=True,
)

# Example 2: Specific functions only
neo4j_toolkit_specific = Neo4jTools(
    uri=uri,
    user=user,
    password=password,
    enable_list_labels=True,
    enable_get_schema=True,
    enable_list_relationships=False,
    enable_run_cypher=False,
)

# Example 3: Default behavior
neo4j_toolkit = Neo4jTools(
    uri=uri,
    user=user,
    password=password,
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
    model=OpenAIChat(id="o3-mini"),
    tools=[neo4j_toolkit],
    markdown=True,
    description=description,
    instructions=instructions,
)

# Agent handles tool usage automatically via LLM reasoning
agent.print_response(
    "Add some nodes in my graph to represent a person with the name John Doe and a person with the name Jane Doe, and they belong to company 'X' and they are friends."
)

agent.print_response("What is the schema of my graph?")
