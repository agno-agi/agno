# Agent Playground

Agno provides a beautiful Agent UI for interacting with your agents.

## Setup

### Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### Export your API keys

```shell
export OPENAI_API_KEY=***
# If you need Exa search
export EXA_API_KEY=***
...
```

### Install libraries

```shell
pip install -U openai exa_py duckduckgo-search yfinance pypdf sqlalchemy 'fastapi[standard]' youtube-transcript-api agno
```

### Authenticate with agno.app

```
ag auth
```

## Connect your Agents to the Agent UI

```shell
python cookbook/playground/demo.py
```

## Test Multimodal Agents

```shell
python cookbook/playground/multimodal_agents.py
```

## Fully local Ollama Agents

### Pull llama3.1:8b

```shell
ollama pull llama3.1:8b
```

### Connect Ollama agents to the Agent UI

```shell
python cookbook/playground/ollama_agents.py
```

## xAi Grok Agents

```shell
python cookbook/playground/grok_agents.py
```

## Groq Agents

```shell
python cookbook/playground/groq_agents.py
```

## Gemini Agents

```shell
python cookbook/playground/gemini_agents.py
```
