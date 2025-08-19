# Agent Levels 

Progressive agent complexity examples showing how to build Agno agents from basic implementations to advanced workflows.

## Examples

### Level 1: [Basic Agent](./level_1_agent.py)
Simple agent with tools - demonstrates basic agent creation with YFinance tools for stock price queries.

### Level 2: [Agent with Knowledge](./level_2_agent.py) 
Agent with knowledge base and storage - adds LanceDB vector database and knowledge search capabilities.

### Level 3: [Agent with Memory](./level_3_agent.py)
Agent with reasoning and user memories - incorporates ReasoningTools and persistent user memory storage.

### Level 4: [Agent Team](./level_4_team.py)
Coordinated team of specialized agents - combines web search and finance agents working together.

### Level 5: [Workflow](./level_5_workflow.py)
Complete workflow orchestration - demonstrates complex multi-step workflows with research teams and content planning.

## Setup

Install required dependencies:

```bash
pip install agno yfinance lancedb
```

Export your API keys:

```bash
export OPENAI_API_KEY=your_openai_key
export ANTHROPIC_API_KEY=your_anthropic_key
```

**Note:** These examples use both OpenAI and Claude models, but feel free to use any model you want.

## Run Examples

```bash
python cookbook/agent_levels/level_1_agent.py
```

Each level can be run independently, but they're designed to be explored in sequence for the best learning experience.