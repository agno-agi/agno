# Agno Cookbooks

Welcome to Agno's cookbook collection! Here you will find hundreds of examples on how to use the Agno framework to build what you want.

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

The full folder is organized in sections focused on a specific concept or features. These are the top level ones:

## Getting Started

The getting started guide walks through the basics of building with Agno. Cookbooks build on each other, introducing new concepts and capabilities.

## Agent Levels

Here you will find an introduction to Agents and to what they can do. Each level introduces a chore feature or abstractions for your AI system:

1. Agent with tools and instructions
2. Agent with knowledge and storage
3. Agent with memory and reasoning
4. A Team of Agents
5. A Workflow

## Agents From Scratch

Focused examples to showcase some of the main features you can use with Agno Agents:

- Knowledge
- Storage
- Tools

## Agents

A more complete set of cookbooks related to Agno Agents. Here you will find more specific and advanced examples of what Agno Agents can do:

- Agentic search: using RAG with an Agent
- Async: running Agents asynchronously
- Db: features related to long term storage
- Dependencies: adding logic that runs when the Agent does
- Events: handling events when streaming an Agent response
- Human in the loop: everything about our HITL flows
- Memory: a complete guide on User Memories
- Multimodal: handling media with your Agents
- Other: more examples of some of our features
- RAG: guide on using RAG with your Agents
- Session: guide on interacting with the current and previous Sessions
- State: examples on handling Session state data
- Tool concepts: comprehensive set of examples of Agents using Agno ToolKits and custom Tools

## Db

In this section you can see examples on how to use all our Db implementations with your Agents. These are all the supported ones:

- PostgresDB
- SqliteDB
- MongoDB
- MySQL
- Redis
- SingleStore
- FireStore
- JSON files
- GCS with JSON files

## Evals

Section focused on evaluating your Agno Agents and Teams across three key dimensions:

- Accuracy: How complete/correct/accurate is the Agent’s response (LLM-as-a-judge)
- Performance: How fast does the Agent respond and what’s the memory footprint?
- Reliability: Does the Agent make the expected tool calls?

## Examples

Collection of real world examples you can build using Agno Agents, Teams and Workflows.

## Integrations

Examples for some of the main integrations you can use with your Agno code.

## Knowledge

Knowledge is the way to provide your Agents with information they can search at runtime to make better decisions and generate better answers.

In this section you will find a comprehensive list of examples on how to manage your Knowledge setup, what sources are available, what databases can be used, etc.

## Memory

An Agent can store insights and facts about users that it learns through conversations with them. This is great to personalize responses!

Here you will find a guide to learn how Memory is setup and how much your Agent can do with it.

## Models

Models are the brain of Agno Agents. In this folder you will find specific examples for each of the Models we support:

- AI/ML API
- Anthropic
- AWS Bedrock
- Azure AI Foundry
- Claude via AWS Bedrock
- Cohere
- DeepSeek
- Fireworks
- Google Gemini
- Groq
- Hugging Face
- LiteLLM
- Mistral
- NVIDIA
- Nebius AI Studio
- Ollama
- OpenAI
- OpenAI Like
- OpenAI via Azure
- OpenRouter
- Perplexity
- Sambanova
- Together
- vLLM
- xAI
- LangDB

## Reasoning

Reasoning gives Agents the ability to plan before acting, and to analyze results after having generated them. This can greatly improve an Agent's capacity to solve problems. There are three ways to use reasoning:

### Reasoning models

Some models are pre-trained to reasoning. The most popular reasoning models are available for your Agno Agents out of the box.

See the [examples](./models/).

### Reasoning tools

You can give your Agent tools that enable reasoning. This is the simplest way to achieve reasoning.

See the [examples](./tools/).

### Reasoning Agents

Reasoning Agents are a new type of multi-agent system developed by Agno that combines chain of thought reasoning with tool use.

You can enable reasoning on any Agent by setting reasoning=True.

When an Agent with reasoning=True is given a task, a separate “Reasoning Agent” first solves the problem using chain-of-thought. At each step, it calls tools to gather information, validate results, and iterate until it reaches a final answer. Once the Reasoning Agent has a final answer, it hands the results back to the original Agent to validate and provide a response.

See the [examples](./agents/).


## Scripts

Some utility scripts to make your work with Agno easier.

## Teams

A Team is a collection of Agents (or other sub-teams) that work together to accomplish tasks. They are the main abstraction piece in the Agno framework after Agents.

You can find a comprehensive set of examples in this folder, divided by the main features you can use with your Teams.

## Tools

Tools are utilities that allow Agents to perform tasks. Think searching the web, running SQL, sending emails or calling APIs.

In this folder you will find examples for some of our ToolKits. An Agno ToolKit is the simplest way to give tools to your Agents and works out of the box.

You can also find examples to learn how to use custom tools, for any functionality we don't support out of the box yet.

## Workflows

Agno Workflows are designed to automate complex processes by defining a series of steps that are executed in sequence. Each step can be executed by an agent, a team, or a custom function.

Workflows are our higher-level abstraction, and are useful to build complex AI systems. In this folder you will find a comprehensive guide showcasing what are the building blocks of Workflows and how much can be achieved using them.

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
