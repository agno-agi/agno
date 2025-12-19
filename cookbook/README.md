# Agno Cookbooks

Welcome to Agno's cookbook collection! Here you will find hundreds of examples on how to use the framework to build what you want.

## Setup

### Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### Install libraries

```shell
pip install -U openai agno
```

### Export your keys

```shell
export OPENAI_API_KEY=***
```

Note: We have just added OpenAI library and API key as an example. You will need to install and export the API keys for the examples you want to run.

## Run a cookbook

```shell
python cookbook/.../example.py
```

The full folder is organized in sections focused on a specific concept or feature:

---

## 00_getting_started

The getting started guide walks through the basics of building with Agno. Cookbooks build on each other, introducing new concepts and capabilities.

## 01_demo

The demo folder contains a complete example of a multi-agent system using Agno's AgentOS. It is a good example to run after getting familiar with the framework in the getting started guide.

## 02_examples

Collection of real world examples you can build using Agno Agents, Teams and Workflows.

## 03_agents

An Agent is the core piece of the Agno framework. It is the atomic component that can be used to build your AI system.

You can find a comprehensive set of examples in this folder, organized by feature:

- **agentic_search** - Agentic RAG and search patterns
- **async** - Asynchronous agent operations
- **caching** - Model response caching
- **context_compression** - Tool call compression strategies
- **context_management** - Instructions, few-shot learning, dynamic context
- **culture** - Cultural knowledge management
- **custom_logging** - Logging configuration
- **dependencies** - Dependency injection
- **events** - Agent event handling
- **guardrails** - Input/output validation
- **hooks** - Pre/post processing hooks
- **human_in_the_loop** - Human oversight patterns
- **input_and_output** - Structured inputs, outputs, and parsing
- **multimodal** - Audio, image, and video processing
- **rag** - Retrieval-augmented generation
- **session** - Session persistence and history
- **state** - Session state management

## 04_teams

A Team is a collection of Agents (or other sub-teams) that work together to accomplish tasks.

You can find a comprehensive set of examples in this folder, organized by feature:

- **async_flows** - Asynchronous team operations
- **basic_flows** - Basic team coordination
- **context_compression** - Team-level context compression
- **context_management** - Team context and instructions
- **dependencies** - Team dependency injection
- **distributed_rag** - Distributed RAG patterns
- **guardrails** - Team-level validation
- **hooks** - Team pre/post processing hooks
- **knowledge** - Team knowledge management
- **memory** - Team memory patterns
- **metrics** - Team performance metrics
- **multimodal** - Team multimodal processing
- **reasoning** - Team reasoning patterns
- **search_coordination** - Coordinated search strategies
- **session** - Team session management
- **state** - Team state management
- **streaming** - Team streaming responses
- **structured_input_output** - Team structured I/O
- **tools** - Team tool usage

## 05_workflows

Agno Workflows are designed to automate complex processes by defining a series of steps that are executed in sequence. Each step can be executed by an agent, a team, or a custom function.

Workflows are our higher-level abstraction, useful for building complex AI systems. In this folder you will find a comprehensive guide showcasing the building blocks of Workflows and what can be achieved using them.

## 06_agent_os

AgentOS is a critical piece of the Agno SDK for building, deploying, and managing Agent Systems. It provides a unified platform to create intelligent agents, organize them into teams, orchestrate complex workflows, and deploy them across various interfaces like web APIs, Slack, WhatsApp, and more.

## 07_database

Examples on how to use all our Database implementations with your Agents, Teams, and Workflows:

- **dynamodb** - AWS DynamoDB
- **firestore** - Google Cloud Firestore
- **gcs** - Google Cloud Storage JSON
- **in_memory** - In-memory database
- **json_db** - JSON file storage
- **mongo** - MongoDB (sync and async)
- **mysql** - MySQL
- **postgres** - PostgreSQL (recommended for production)
- **redis** - Redis
- **singlestore** - SingleStore
- **sqlite** - SQLite (recommended for development)
- **surrealdb** - SurrealDB

## 08_knowledge

Knowledge is the way to provide your Agents with information they can search at runtime to make better decisions and generate better answers.

This section covers:

- **basic_operations** - Loading knowledge from various sources (paths, URLs, S3, GCS, YouTube)
- **chunking** - Document chunking strategies (semantic, recursive, fixed-size, agentic)
- **custom_retriever** - Custom retrieval implementations
- **embedders** - Embedding providers (OpenAI, Cohere, Gemini, Mistral, Ollama, and more)
- **filters** - Knowledge filtering and metadata queries
- **readers** - Document readers (PDF, CSV, JSON, DOCX, PPTX, web content)
- **search_type** - Vector, keyword, and hybrid search
- **vector_db** - Vector database integrations

## 09_memory

An Agent can store insights and facts about users that it learns through conversations. This is great for personalizing responses!

In this section you will find a guide to learn how Memory is setup and how much your Agent can do with it.

## 10_reasoning

Reasoning gives Agents the ability to plan before acting, and to analyze results after having generated them. This can greatly improve an Agent's capacity to solve problems. There are three ways to use reasoning:

### Reasoning models

Some models are pre-trained for reasoning. The most popular reasoning models are available for your Agno Agents out of the box.

### Reasoning tools

You can give your Agent tools that enable reasoning. This is the simplest way to achieve reasoning.

### Reasoning Agents

Reasoning Agents are a new type of multi-agent system developed by Agno that combines chain of thought reasoning with tool use.

You can enable reasoning on any Agent by setting `reasoning=True`.

When an Agent with `reasoning=True` is given a task, a separate "Reasoning Agent" first solves the problem using chain-of-thought. At each step, it calls tools to gather information, validate results, and iterate until it reaches a final answer. Once the Reasoning Agent has a final answer, it hands the results back to the original Agent to validate and provide a response.

## 11_models

Models are the brain of Agno Agents. In this folder you will find specific examples for each of the Models we support:

- AI/ML API
- Anthropic Claude
- AWS Bedrock
- Azure AI Foundry
- Cerebras
- Cohere
- Comet API
- DashScope
- DeepInfra
- DeepSeek
- Fireworks
- Google Gemini
- Google Vertex AI
- Groq
- Hugging Face
- IBM
- InternLM
- LangDB
- LiteLLM
- Llama CPP
- LM Studio
- Meta Llama
- Mistral
- Nebius
- Nexus
- NVIDIA
- Ollama
- OpenAI (Chat and Responses API)
- OpenRouter
- Perplexity
- Portkey
- Requesty
- Sambanova
- SiliconFlow
- Together
- Vercel
- vLLM
- xAI

## 12_evals

Section focused on evaluating your Agno Agents and Teams across key dimensions:

- **Accuracy**: How complete/correct/accurate is the Agent's response (LLM-as-a-judge)
- **Performance**: How fast does the Agent respond and what's the memory footprint?
- **Reliability**: Does the Agent make the expected tool calls?
- **Agent as Judge**: How accurate is the Agent's response, given a question and expected response

## 13_integrations

Examples for some of the main integrations you can use with your Agno code:

- **a2a** - Agent-to-Agent protocol
- **discord** - Discord bot integration
- **memory** - Memory integrations
- **observability** - Observability and tracing (Langfuse, Arize Phoenix, AgentOps, LangSmith, and more)

## 14_tools

Tools are utilities that allow Agents to perform tasks. Think searching the web, running SQL, sending emails or calling APIs.

In this folder you will find examples for our ToolKits and custom tool implementations:

- **async** - Async tool examples
- **exceptions** - Tool exception handling
- **mcp** - Model Context Protocol tools
- **models** - Model-specific tool examples
- **tool_decorator** - Using the `@tool` decorator
- **tool_hooks** - Tool hooks for pre/post processing

Plus examples for specific tools like Calculator, Discord, Docker, ElevenLabs, Email, Exa, MCP, Newspaper4k, OpenCV, SearXNG, SerpAPI, Slack, Trafilatura, Trello, WebBrowser, X (Twitter), and more.

## scripts

Utility scripts to make your work with Agno easier.

---

We are constantly adding new cookbooks to the repository. If you want to contribute, please check the [CONTRIBUTING.md](./CONTRIBUTING.md) file.
