# Agent Examples

A curated collection of production-ready AI agents, teams, and workflows built with Agno. Browse real-world implementations across diverse use cases.

## Browse by Category

| Category | Description | Examples |
| :--- | :--- | ---: |
| [**Agents**](01_agents/) | Individual agents for specific tasks | 38 |
| [**Teams**](02_teams/) | Multi-agent collaboration patterns | 13 |
| [**Workflows**](03_workflows/) | Sequential multi-step pipelines | 5 |
| [**Gemini**](04_gemini/) | Gemini-native features and patterns | 6 |
| [**Streamlit Apps**](05_streamlit_apps/) | Agent UIs with Streamlit | varies |
| [**Spotify Agent**](06_spotify_agent/) | Music assistant integration | 2 |

---

## Featured Examples

### Startup Analyst Agent

> *Comprehensive due diligence in one prompt.*

Analyze any startup with automated web scraping, market research, and competitive intelligence. Perfect for investors and entrepreneurs.

```python
startup_analyst.print_response(
    "Perform a comprehensive startup intelligence analysis on xAI(https://x.ai)"
)
```

[View Code](01_agents/startup_analyst_agent.py) | Uses: ScrapeGraph, GPT-4o

---

### Tic-Tac-Toe Team

> *Watch two LLMs compete against each other.*

A fun demonstration of multi-agent coordination where GPT-4o plays against Gemini in a game of tic-tac-toe.

```python
agent_team.print_response(
    "Run a full Tic Tac Toe game."
)
```

[View Code](02_teams/tic_tac_toe_team.py) | Uses: GPT-4o, Gemini

---

### Startup Idea Validator

> *From idea to market validation in minutes.*

A 4-phase workflow that takes a startup idea through clarification, market research, competitor analysis, and generates a comprehensive validation report.

```python
result = await startup_validation_workflow.arun(
    input="Please validate this startup idea",
    startup_idea="A marketplace for leather Christmas ornaments"
)
```

[View Code](03_workflows/startup_idea_validator.py) | Uses: GPT-4o-mini, DuckDuckGo

---

### Translation Agent with Voice

> *Translate text and generate localized voice notes.*

An emotion-aware translator that converts text to another language, analyzes sentiment, and generates a voice note using Cartesia TTS.

```python
response = agent.run(
    "Convert 'hello! how are you?' to French and create a voice note"
)
```

[View Code](01_agents/translation_agent.py) | Uses: Gemini, Cartesia

---

## Agents Overview

### Research & Analysis

| Agent | Description | Key Tools |
| :--- | :--- | :--- |
| [**Deep Research (Exa)**](01_agents/deep_research_agent_exa.py) | Advanced research with citations | Exa Research |
| [**Media Trend Analysis**](01_agents/media_trend_analysis_agent.py) | Track media trends and sentiment | Exa, Firecrawl |
| [**Competitor Analysis**](01_agents/competitor_analysis_agent.py) | Competitive intelligence | Firecrawl, Reasoning |
| [**Social Media Agent**](01_agents/social_media_agent.py) | X/Twitter brand intelligence | XTools |
| [**Startup Analyst**](01_agents/startup_analyst_agent.py) | Comprehensive due diligence | ScrapeGraph |

### Multi-Modal & Creative

| Agent | Description | Key Tools |
| :--- | :--- | :--- |
| [**Recipe RAG + Image**](01_agents/recipe_rag_image.py) | RAG with image generation | Knowledge, OpenAI |
| [**Translation + Voice**](01_agents/translation_agent.py) | Translate with voice synthesis | Cartesia |

### Knowledge & RAG

| Agent | Description | Key Tools |
| :--- | :--- | :--- |
| [**Deep Knowledge**](01_agents/deep_knowledge.py) | Iterative knowledge search | PgVector |
| [**Agno Assist**](01_agents/agno_assist.py) | Documentation assistant | LanceDb |
| [**Legal Consultant**](01_agents/legal_consultant.py) | Legal document RAG | PgVector |

### Integrations

| Agent | Description | Key Tools |
| :--- | :--- | :--- |
| [**Airbnb MCP**](01_agents/airbnb_mcp.py) | Search Airbnb listings | MCP, Groq |
| [**Spotify Agent**](06_spotify_agent/spotify_agent.py) | Music management | SpotifyTools |
| [**README Generator**](01_agents/readme_generator.py) | Generate READMEs | GitHub, LocalFS |

---

## Teams Overview

| Team | Description | Agents |
| :--- | :--- | ---: |
| [**SkyPlanner MCP**](02_teams/skyplanner_mcp_team.py) | Travel planning with MCP servers | 4 |
| [**Tic-Tac-Toe**](02_teams/tic_tac_toe_team.py) | LLMs play games | 2 |
| [**Autonomous Startup**](02_teams/autonomous_startup_team.py) | Autonomous startup team | varies |
| [**News Agency**](02_teams/news_agency_team.py) | News research and writing | varies |
| [**Content Team**](02_teams/content_team.py) | Content creation pipeline | varies |

---

## Workflows Overview

| Workflow | Description | Phases |
| :--- | :--- | ---: |
| [**Startup Validator**](03_workflows/startup_idea_validator.py) | Idea to validation report | 4 |
| [**Investment Report**](03_workflows/investment_report_generator.py) | Financial analysis pipeline | varies |
| [**Employee Recruiter**](03_workflows/employee_recruiter.py) | Recruitment workflow | varies |
| [**Blog Post Generator**](03_workflows/blog_post_generator.py) | Content generation | varies |

---

## Getting Started

### 1. Set up the environment

```bash
# Use the demo environment (recommended)
source .venvs/demo/bin/activate

# Or create a new one
uv venv .examples --python 3.12
source .examples/bin/activate
uv pip install -r cookbook/02_examples/requirements.txt
```

### 2. Start PostgreSQL

Many examples use PostgreSQL for persistence:

```bash
./cookbook/scripts/run_pgvector.sh
```

### 3. Set API keys

```bash
export OPENAI_API_KEY=your-key
export GOOGLE_API_KEY=your-key
# Add others as needed for specific examples
```

### 4. Run an example

```bash
python cookbook/02_examples/01_agents/startup_analyst_agent.py
```

---

## Learn More

- [Agno Documentation](https://docs.agno.com/)
- [Getting Started Tutorial](../00_getting_started/)
- [Gemini Examples](04_gemini/) - Well-documented subfolder
