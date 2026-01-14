# Showcase

Curated collection of impressive Agno examples demonstrating real-world AI agent capabilities.

These examples are selected for their **wow factor** - they demonstrate what's possible with Agno in production scenarios.

---

## 01_agents/

Standalone agents showcasing advanced capabilities.

| Example | Description | Key Features |
|:--------|:------------|:-------------|
| `startup_analyst_agent.py` | Due diligence research on startups | ScrapeGraph, structured output |
| `deep_research_agent_exa.py` | Research with citations | Exa search, citations |
| `social_media_agent.py` | X/Twitter brand intelligence | X API, sentiment analysis |
| `translation_agent.py` | Multi-language voice synthesis | Cartesia TTS |
| `recipe_rag_image.py` | Recipe search with image generation | RAG, DALL-E |
| `airbnb_mcp.py` | Airbnb search via MCP | MCP, Llama 4 |
| `deep_knowledge.py` | Iterative knowledge base search | PgVector, agentic RAG |
| `reasoning_finance_agent.py` | Financial analysis with reasoning | Extended thinking |
| `self_learning_agent.py` | Agent that learns and saves insights | Learning Machine |
| `self_learning_research_agent.py` | Tracks consensus over time | Learning, memory |
| `deep_knowledge_agent.py` | Deep reasoning with knowledge | Iterative search |
| `finance_agent.py` | Comprehensive financial analysis | YFinance, tools |
| `sql/` | Text-to-SQL with F1 data | Semantic model, self-learning |

## 02_teams/

Multi-agent teams working together.

| Example | Description | Key Features |
|:--------|:------------|:-------------|
| `tic_tac_toe_team.py` | GPT-4o vs Gemini playing games | Multi-model, game logic |
| `skyplanner_mcp_team.py` | Trip planning with MCP servers | Multiple MCP servers |
| `autonomous_startup_team.py` | Autonomous startup simulation | Autonomous mode |
| `news_agency_team.py` | News research and writing team | Coordination |
| `ai_customer_support_team.py` | Customer support automation | Routing, escalation |
| `finance_team.py` | Finance + research combined | Team coordination |

## 03_workflows/

Multi-step workflows with structured execution.

| Example | Description | Key Features |
|:--------|:------------|:-------------|
| `startup_idea_validator.py` | 4-phase startup validation | Structured phases |
| `investment_report_generator.py` | Financial analysis pipeline | Multi-step analysis |
| `employee_recruiter_async_stream.py` | Streaming recruitment workflow | Async, streaming |
| `research_workflow.py` | Parallel research with multiple agents | Parallel execution |

## 04_gemini/

Partner showcase demonstrating Agno + Google Gemini integration.

See `04_gemini/README.md` for details.

---

## Getting Started

```bash
# Activate the demo environment
source .venvs/demo/bin/activate

# Or use the Python directly
.venvs/demo/bin/python cookbook/01_showcase/01_agents/finance_agent.py
```

## API Keys Required

Different examples require different API keys:

| Key | Used By |
|:----|:--------|
| `GOOGLE_API_KEY` | Most agents (Gemini) |
| `OPENAI_API_KEY` | OpenAI-based agents |
| `EXA_API_KEY` | Research agents |
| `SGAI_API_KEY` | ScrapeGraph agents |
| `X_API_KEY` | Social media agent |
| `CARTESIA_API_KEY` | Translation agent |

---

## Notes

- These are **showcase** examples - meant to impress
- For feature documentation, see the numbered folders (02_agents, 03_teams, etc.)
- For getting started tutorials, see 00_getting_started/
