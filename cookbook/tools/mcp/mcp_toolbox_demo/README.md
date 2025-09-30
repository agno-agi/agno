# MCP Toolbox Demo - Hotel Management Agent

This demo showcases how to set up and run an Agno Agent that can interact with a PostgreSQL database through the [MCP Toolbox for Databases](https://googleapis.github.io/genai-toolbox/getting-started/introduction/). The agent acts as a hotel assistant capable of searching, booking, and canceling hotel reservations.

MCP Toolbox for Databases (MCP Toolbox) provides a unified interface for AI agents to interact with databases.

In this demo, we have a collection of tools (defined in `config/tools.yaml`) that allow the agent to perform various hotel management tasks, such as searching for hotels, making bookings, and retrieving hotel information. The tools are groups into two toolsets:
- `hotel-management`: For searching and retrieving hotel information
- `booking-system`: For handling reservations and cancellations

Read more about the MCP Toolbox confiuration here: [MCP Toolbox Configuration](https://googleapis.github.io/genai-toolbox/getting-started/configure/).

## Prerequisites

- Docker or Podman installed on your system
- Docker Compose support
- Python >= 3.13 with `uv` package manager

## Project Overview

The demo includes:
- **PostgreSQL Database**: Pre-populated with sample hotel data
- **MCP Toolbox Server**: Provides database tools via HTTP API
- **Python Agent**: Interactive CLI agent for hotel management tasks

## Quick Start

### 1. Set Up the MCP Toolbox with Docker Compose

Start the MCP Toolbox and PostgreSQL database using Docker Compose (`docker-compose.yml`).

Navigate to the demo directory:
```bash
cd cookbook/tools/mcp/mcp_toolbox_demo
```

#### Start the services

```bash
# Start all services in detached mode
docker-compose up -d
```

**For Podman users:**
```bash
podman compose up -d
```

#### Verify the setup

Check that both containers are running:
```bash
docker-compose ps
```

Test the database connection:
```bash
docker-compose exec db psql -U toolbox_user -d toolbox_db -c "SELECT COUNT(*) FROM hotels;"
```
You should see a count of the hotels in the database.

### 2. Install Python Dependencies

```bash
# Install dependencies using uv
uv sync
```

### 3. Run the Hotel Management Agent

Setup OpenAI API key:
```bash
export OPENAI_API_KEY="your_openai_api_key"
```

Start the agent:
```bash
# Activate the virtual environment and run the agent or use uv
uv run agent.py
```

The agent will start an interactive CLI where you can:
- Search for hotels by location or price
- Make hotel bookings
- Cancel existing reservations
- Get hotel information and availability

## Usage Examples

Once the agent is running, try these commands:

```
> Find hotels in Basel with Basel in it's name.
> Can you book the Hyatt Regency for me?
> Show me all luxury hotels
> What are the available hotels in Zurich?
```

### 4. Run AgentOS
To run the AgentOS:

```bash
uv run agent_os.py
```

Connect AgentOS Control Plane to `http://localhost:7777` and interact with the agent via the web interface.

### 5. Run Workflows
To run Hotel booking workflow:

```bash
uv run hotel_management_workflows.py
```

This workflow searches for boutique hotels in Zurich, then books the first available hotel. Here is sample output:

```bash
$ uv run workflow_demo.py 
🏨 Hotel Search and Booking Workflow
Request: Find luxury hotels in Zurich and book the first available one
==================================================
INFO Executing async step (non-streaming): Search Hotels                                                                
INFO Executing async step (non-streaming): Book Hotel                                                                   
INFO Successfully created table 'agno_sessions'                                                                         

✅ Workflow Result:
Content: The hotel has been successfully booked!

- **Hotel Name**: The Ritz-Carlton Zurich
- **Hotel ID**: 4
```

### 6. Run Type-Safe Agent
To run the type-safe agent:
```bash
uv run hotel_management_typesafe.py
```

This agent uses Pydantic models to ensure type safety when interacting with the database.



## Service Configuration

### Available Services

- **MCP Toolbox API**: `http://localhost:5001`
- **PostgreSQL Database**: `localhost:5432`
  - Database: `toolbox_db`
  - User: `toolbox_user`
  - Password: `my-password`

>> Note: These are test credentials. Do not use in production.

### Agent Configuration

The agent is configured with two toolsets:
- `hotel-management`: Search and retrieve hotel information
- `booking-system`: Handle reservations and cancellations

## Troubleshooting

### Common Issues

1. **Port conflicts**: If port 5001 is in use, modify the docker-compose.yml port mapping
2. **Database connection errors**: Ensure the database container is healthy before starting the agent
3. **Python dependency errors**: Run `uv sync` to install all required packages


## Cleanup

To stop and remove all services:
```bash
docker-compose down -v
```