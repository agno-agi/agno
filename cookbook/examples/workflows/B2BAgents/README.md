# B2B Pipeline Builder

Multi-agent B2B intelligence system built with Agno 2.0 Workflows for automated lead enrichment, ICP scoring, and personalized LinkedIn message generation.

## Overview

Three specialized AI agents execute sequentially:

1. **Data Enricher Agent** - Fetches and enriches lead profiles from Apollo API
2. **ICP Fit Scorer Agent** - Scores leads against Ideal Customer Profile criteria with weighted analysis
3. **LinkedIn Message Generator Agent** - Creates personalized LinkedIn outreach messages

## Features

- **Storage** - SQLite for sessions and memory
- **Multi-Agent** - Three sequential agents working together
- **Memory** - Shared memory across agents for learning from past patterns
- **Custom Tools** - Apollo API integration for lead enrichment
- **Agent OS** - Web UI and API access via AgentOS
- **Workflows** - Sequential workflow orchestration

## Setup

### Prerequisites

- Python 3.8+
- Apollo API key - Get from [Apollo.io](https://apollo.io)
- Google API key - Get from [Google AI Studio](https://makersuite.google.com/app/apikey)

### Installation

1. Create virtual environment and install dependencies:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. Configure environment variables:

```bash
cp .env.template .env
```

Edit `.env` and add your credentials:

- `APOLLO_API_KEY` - Your Apollo.io API key
- `GOOGLE_API_KEY` - Your Google API key for Gemini
- `SQLITE_DB_PATH` - SQLite database path (default: `tmp/agno_sessions.db`)

### Run the Application

```bash
python main.py
```

The system will start on port 7777.

## Usage

1. Start the application:

```bash
python main.py
```

2. Access the web UI at: `https://os.agno.com/` add the endpoint `http://localhost:7777` while creating your OS

3. Access API documentation at: `http://localhost:7777/docs`

### Example Queries

- "Get me 5 sales directors in London"
- "Get me 5 Marketing Managers in New York"
- Format: "Get me [number] [role/title] in [location]"

### Output

The workflow provides SDR-ready leads with:
- Contact data + enriched context (email, phone, company info)
- Scored fit vs ICP (0-100 with weighted analysis)
- Personalized LinkedIn messages ready to copy and send

## Project Structure

```
B2BAgents/
├── agents.py              # Agent definitions (Data Enricher, ICP Scorer, Message Generator)
├── tools.py               # Apollo API integration tools
├── main.py                # Application entry point and AgentOS setup
├── requirements.txt       # Python dependencies
├── .env.template         # Environment variable template
├── .env                  # Environment variables (gitignored)
├── .gitignore            # Git ignore file
├── .cursorrules          # Project rules (gitignored)
└── tmp/                  # Temporary files and SQLite database
    └── agno_sessions.db  # SQLite database for sessions and memory
```

## ICP Scoring Criteria

The ICP Scorer uses weighted criteria:

- **Role Level (35%)** - Director, VP, C-level are ideal
- **Company Size (30%)** - 50-500 employees is ideal
- **Tech Stack Match (25%)** - Match with product integrations
- **Location (10%)** - Target markets preferred

Leads scoring 70+ are flagged as "Fit", below 70 as "Misfit".

## Architecture

### Storage
- **SQLite** - Stores agent sessions and user memories

### Memory
All agents share memory through a common `MemoryManager`, allowing them to:
- Learn from past enrichment patterns
- Reference successful scoring results
- Remember effective message templates

### Workflow
Sequential execution:
1. Data Enrichment → 2. ICP Scoring → 3. Message Generation

Each step receives output from the previous step via workflow session state.



