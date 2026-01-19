# Showcase

Curated collection of impressive Agno examples demonstrating real-world AI agent capabilities.

These examples are selected for their **wow factor** - they demonstrate what's possible with Agno in production scenarios.

---

## 01_agents/

Standalone agents showcasing advanced capabilities.

| Example | Description | Key Features | Impressiveness |
|:--------|:------------|:-------------|:---------------|
| `self_learning_agent.py` | Agent that learns and saves insights | Knowledge base, learning loop | High - unique capability |
| `self_learning_research_agent.py` | Tracks consensus over time | Longitudinal memory, claims | High - temporal tracking |
| `deep_knowledge_agent.py` | Deep reasoning with knowledge | ReasoningTools, PgVector | High - iterative search |
| `sql/sql_agent.py` | Text-to-SQL with F1 data | Semantic model, self-learning | Very High - production pattern |
| `startup_analyst_agent.py` | Due diligence research on startups | ScrapeGraph, structured output | High - real use case |
| `deep_research_agent_exa.py` | Research with citations | Exa search, citations | Medium - shows Exa |
| `social_media_agent.py` | X/Twitter brand intelligence | X API, sentiment analysis | High - unique integration |
| `translation_agent.py` | Multi-language voice synthesis | Cartesia TTS | High - multi-modal |
| `recipe_rag_image.py` | Recipe search with image generation | RAG, DALL-E | Medium - multi-modal RAG |
| `airbnb_mcp.py` | Airbnb search via MCP | MCP protocol, Llama 4 | High - MCP integration |

## 02_teams/

Multi-agent teams working together.

| Example | Description | Key Features | Impressiveness |
|:--------|:------------|:-------------|:---------------|
| `tic_tac_toe_team.py` | GPT-4o vs Gemini playing games | Multi-model, game logic | High - fun demo |
| `skyplanner_mcp_team.py` | Trip planning with MCP servers | Multiple MCP servers | Very High - complex MCP |
| `autonomous_startup_team.py` | Autonomous startup simulation | 6 agents, autonomous mode | Very High - complex coordination |
| `news_agency_team.py` | News research and writing team | Searcher, writer, editor | High - content pipeline |
| `ai_customer_support_team.py` | Customer support automation | Doc research, escalation, feedback | High - real use case |

## 03_workflows/

Multi-step workflows with structured execution.

| Example | Description | Key Features | Impressiveness |
|:--------|:------------|:-------------|:---------------|
| `startup_idea_validator.py` | 4-phase startup validation | Structured phases, Pydantic | Very High - end-to-end workflow |
| `investment_report_generator.py` | Financial analysis pipeline | Multi-step, file output | Very High - production pattern |
| `research_workflow.py` | Parallel research with multiple agents | Parallel execution, consolidation | Very High - parallel pattern |
| `employee_recruiter_async_stream.py` | Streaming recruitment workflow | Async streaming, PDF parsing | High - async pattern |

## 04_gemini/

Partner showcase demonstrating Agno + Google Gemini integration.

| Example | Description | Key Features | Impressiveness |
|:--------|:------------|:-------------|:---------------|
| `agents/self_learning_agent.py` | Self-learning with Gemini | GeminiEmbedder, learning | High - Gemini native |
| `agents/self_learning_research_agent.py` | Research tracking with Gemini | Claims, consensus | High - Gemini native |
| `agents/pal_agent.py` | Plan and Learn Agent | Step tracking, dynamic plans | Very High - unique pattern |
| `agents/creative_studio_agent.py` | Image generation with NanoBanana | Gemini + image gen | High - multi-modal |
| `agents/product_comparison_agent.py` | Product comparison | Gemini search, url_context | Medium - native features |

See `04_gemini/README.md` for details.

---

## Getting Started

```bash
# Activate the demo environment
source .venvs/demo/bin/activate

# Or use the Python directly
.venvs/demo/bin/python cookbook/01_showcase/01_agents/self_learning_agent.py
```

## API Keys Required

Different examples require different API keys:

| Key | Used By |
|:----|:--------|
| `GOOGLE_API_KEY` | Most agents (Gemini) |
| `OPENAI_API_KEY` | OpenAI-based agents, image gen |
| `EXA_API_KEY` | Research agents (Exa) |
| `SGAI_API_KEY` | ScrapeGraph agents |
| `X_API_KEY` | Social media agent |
| `CARTESIA_API_KEY` | Translation agent |
| `COHERE_API_KEY` | Recipe RAG (embedder) |

---

## Notes

- These are **showcase** examples - meant to impress and demonstrate production patterns
- For feature documentation, see the numbered folders (02_agents, 03_teams, etc.)
- For getting started tutorials, see `00_quickstart/`

## What Was Removed

The following files were removed as they were duplicates or too basic for a showcase:
- `finance_agent.py` - Duplicate of quickstart examples
- `deep_knowledge.py` - Duplicate of deep_knowledge_agent.py
- `reasoning_finance_agent.py` - Too basic (24 lines)
- `finance_team.py` - Broken imports
- `simple_research_agent.py` - Too basic for showcase
