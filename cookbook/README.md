# Agno Cookbooks

## Getting Started

The getting started guide walks through the basics of building Agents with Agno. Recipes build on each other, introducing new concepts and capabilities.

## Agent Concepts

The concepts cookbook walks through the core concepts of Agno.

- [Async](./agent_concepts/async)
- [RAG](./agent_concepts/rag)
- [Knowledge](./agent_concepts/knowledge)
- [Memory](./agent_concepts/memory)
- [Storage](storage)
- [Tools](./tools)
- [Reasoning](./reasoning)
- [Vector DBs](./agent_concepts/knowledge/vector_dbs)
- [Multi-modal Agents](./agent_concepts/multimodal)
- [Agent Teams](./teams)
- [Other](./agent_concepts/other)

## Examples

The examples cookbook contains real world examples of building agents with Agno.

## Playground

The playground cookbook contains examples of interacting with agents using the Agno Agent UI.

## Workflows

The workflows cookbook contains examples of building workflows with Agno.

## Scripts

Just a place to store setup scripts like `run_pgvector.sh` etc

## Setup

### Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### Install libraries

```shell
pip install -U openai agno  # And all other packages you might need
```

### Export your keys

```shell
export OPENAI_API_KEY=***
export GOOGLE_API_KEY=***
```

## Run a cookbook

```shell
python cookbook/.../example.py
```
