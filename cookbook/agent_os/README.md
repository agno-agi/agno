# AgentOS

**AgentOS** is a comprehensive framework for building, deploying, and managing Agent Systems. It provides a unified platform to create intelligent agents, organize them into teams, orchestrate complex workflows, and deploy them across various interfaces like web APIs, Slack, WhatsApp, and more.

The `AgentOS` serves as an API client to the [AgentOS UI](https://os.agno.com).

## Key Features

- **🤖 Agents, Teams, Workflows**: Connect your agents, teams and workflows to the AgentOS UI.
- **🔧 UI Configuration**: Use the AgentOSConfig to configure the experience on the AgentOS UI.
- **📱 Multi-Interface**: Enable other interfaces like Slack, WhatsApp, and AGUI.
- **🔒 Security**: Optional authentication and access control.

## Quick Start

Here's a minimal example to get you started with AgentOS:

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS

# Setup database (you can also use SQLite for quick prototyping)
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Create an agent
agent = Agent(
    name="Assistant",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    instructions=["You are a helpful AI assistant"],
    enable_user_memories=True,
    markdown=True,
)

# Create AgentOS app
agent_os = AgentOS(
    description="My first AgentOS app",
    id="my-app",
    agents=[agent],
)

app = agent_os.get_app()

if __name__ == "__main__":
    # Start the server
    agent_os.serve(app="my_app:app", reload=True)
    # Visit http://localhost:7777 to interact with your agent
```

## Prerequisites

Install the required dependencies:

```bash
pip install -U agno fastapi uvicorn sqlalchemy pgvector psycopg openai
```

For additional tools and integrations:
```bash
pip install ddgs yfinance
```

## Getting Started

1. **Choose a database**: Start with SQLite for prototyping or PostgreSQL for production
2. **Create your first agent**: Define its role, instructions, and tools
3. **Set up AgentOS**: Initialize with your agents, teams, or workflows
4. **Deploy**: Run locally or deploy to your preferred platform
5. **Integrate**: Add interfaces like Slack, WhatsApp, etc.

## Documentation

For detailed documentation, visit the [Agno Documentation](https://docs.agno.com).

## Examples

This directory contains comprehensive examples demonstrating different aspects of AgentOS:

### Core Examples
- [`basic.py`](basic.py) - Minimal AgentOS setup with agent, team, and workflow
- [`demo.py`](demo.py) - Full-featured demo with multiple agents, tools, and knowledge base
- [`evals_demo.py`](evals_demo.py) - Agent evaluation and testing framework

### Customization Examples
- [`customize/custom_fastapi.py`](customize/custom_fastapi.py) - Custom FastAPI app for the AgentOS
- [`customize/custom_lifespan.py`](customize/custom_lifespan.py) - Custom lifespan for the AgentOS
- [`customize/override_routes.py`](customize/override_routes.py) - Override AgentOS routes with your own

### MCP Examples
- [`mcp/enable_mcp_example.py`](mcp/enable_mcp_example.py) - How to convert your AgentOS into an MCP server
- [`mcp/mcp_tools_example.py`](mcp/mcp_tools_example.py) - How to use MCP tools in your AgentOS
- [`mcp/mcp_tools_existing_lifespan.py`](mcp/mcp_tools_existing_lifespan.py) - MCP tools example with existing lifespan
- [`mcp/mcp_tools_advanced_example.py`](mcp/mcp_tools_advanced_example.py) - MCP tools example with multiple MCP servers

### Database Integrations
- [`dbs/postgres_demo.py`](dbs/postgres_demo.py) - Demo using PostgreSQL database
- [`dbs/sqlite_demo.py`](dbs/sqlite_demo.py) - Demo using SQLite database
- [`dbs/mongo_demo.py`](dbs/mongo_demo.py) - Demo using MongoDB database
- [`dbs/redis_demo.py`](dbs/redis_demo.py) - Demo using Redis database
- [`dbs/supabase_demo.py`](dbs/supabase_demo.py) - Demo using Supabase database
- [`dbs/neon_demo.py`](dbs/neon_demo.py) - Demo using Neon database
- [`dbs/firestore_demo.py`](dbs/firestore_demo.py) - Demo using Google Firestore database
- [`dbs/dynamo_demo.py`](dbs/dynamo_demo.py) - Demo using AWS DynamoDB database
- [`dbs/singlestore_demo.py`](dbs/singlestore_demo.py) - Demo using SingleStore database
- [`dbs/json_demo.py`](dbs/json_demo.py) - Demo using JSON file storage
- [`dbs/gcs_json_demo.py`](dbs/gcs_json_demo.py) - Demo using Google Cloud Storage JSON

### Workflow Examples
- [`workflow/basic_workflow.py`](workflow/basic_workflow.py) - Simple linear workflow
- [`workflow/basic_workflow_team.py`](workflow/basic_workflow_team.py) - Team-based workflow
- [`workflow/workflow_with_steps.py`](workflow/workflow_with_steps.py) - Multi-step workflow
- [`workflow/workflow_with_conditional.py`](workflow/workflow_with_conditional.py) - Conditional logic in workflows
- [`workflow/workflow_with_parallel.py`](workflow/workflow_with_parallel.py) - Parallel execution
- [`workflow/workflow_with_loop.py`](workflow/workflow_with_loop.py) - Workflow loops
- [`workflow/workflow_with_router.py`](workflow/workflow_with_router.py) - Dynamic routing
- [`workflow/workflow_with_nested_steps.py`](workflow/workflow_with_nested_steps.py) - Nested workflow steps
- [`workflow/workflow_with_custom_function.py`](workflow/workflow_with_custom_function.py) - Custom functions in workflows
- [`workflow/workflow_with_input_schema.py`](workflow/workflow_with_input_schema.py) - Input validation and schemas

### Interface Examples

#### Slack Integration
- [`interfaces/slack/basic.py`](interfaces/slack/basic.py) - Basic Slack bot
- [`interfaces/slack/agent_with_user_memory.py`](interfaces/slack/agent_with_user_memory.py) - Slack bot with persistent memory
- [`interfaces/slack/reasoning_agent.py`](interfaces/slack/reasoning_agent.py) - Advanced reasoning agent for Slack

#### WhatsApp Integration
- [`interfaces/whatsapp/basic.py`](interfaces/whatsapp/basic.py) - Basic WhatsApp bot
- [`interfaces/whatsapp/agent_with_user_memory.py`](interfaces/whatsapp/agent_with_user_memory.py) - WhatsApp bot with memory
- [`interfaces/whatsapp/agent_with_media.py`](interfaces/whatsapp/agent_with_media.py) - Media handling in WhatsApp
- [`interfaces/whatsapp/reasoning_agent.py`](interfaces/whatsapp/reasoning_agent.py) - Advanced WhatsApp reasoning agent
- [`interfaces/whatsapp/image_generation_model.py`](interfaces/whatsapp/image_generation_model.py) - Image generation capabilities
- [`interfaces/whatsapp/image_generation_tools.py`](interfaces/whatsapp/image_generation_tools.py) - Image generation tools

#### AGUI Integration
- [`interfaces/agui/basic.py`](interfaces/agui/basic.py) - Basic AGUI interface
- [`interfaces/agui/agent_with_tool.py`](interfaces/agui/agent_with_tool.py) - AGUI interface with tool integration
- [`interfaces/agui/research_team.py`](interfaces/agui/research_team.py) - Research team AGUI interface

### Advanced Examples
- [`advanced/demo.py`](advanced/demo.py) - Advanced AgentOS features
- [`advanced/teams_demo.py`](advanced/teams_demo.py) - Complex team coordination
- [`advanced/reasoning_demo.py`](advanced/reasoning_demo.py) - Advanced reasoning capabilities
- [`advanced/multiple_knowledge_bases.py`](advanced/multiple_knowledge_bases.py) - Multiple knowledge base management
- [`advanced/mcp_demo.py`](advanced/mcp_demo.py) - Model Context Protocol integration
