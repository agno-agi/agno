# Agents from Scratch

This is a step by step guide to building Agents from scratch, with Agno.

Each example builds on the previous one, introducing new concepts and capabilities progressively.

## Setup

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the required dependencies:

```bash
pip install openai duckduckgo-search lancedb tantivy elevenlabs sqlalchemy agno
```

Export your OpenAI API key:

```bash
export OPENAI_API_KEY=your_api_key
```

If you want to use the ElevenLabs API, export your API key:

```bash
export ELEVENLABS_API_KEY=your_api_key
```

## Run the Playground

We recommend testing the Agents in the Agent UI, which is a web application that allows you to chat with your Agents.

### Authenticate with Agno

```bash
ag setup
```

### Run the Playground

```bash
python cookbook/agents_from_scratch/playground.py
```

## Run the Agents in the CLI

You may also run the Agents in the CLI, which is useful for testing and debugging.

```bash
python cookbook/agents_from_scratch/simple_agent.py
```

```bash
python cookbook/agents_from_scratch/agent_with_tools.py
```

> Remember to set `load_knowledge = True` in the `agent_with_knowledge.py` file to load the knowledge base.

```bash
python cookbook/agents_from_scratch/agent_with_knowledge.py
```

```bash
python cookbook/agents_from_scratch/agent_with_storage.py
```

```bash
python cookbook/agents_from_scratch/agno_assist.py
```
