# Reasoning

Reasoning gives Agents the ability to “think” before responding and “analyze” the results of their actions (i.e. tool calls), greatly improving the Agents’ ability to solve problems that require sequential tool calls.

Reasoning Agents go through an internal chain of thought before responding, working through different ideas, validating and correcting as needed. Agno supports 3 approaches to reasoning:

1. Reasoning Models
2. Reasoning Tools
3. Reasoning Agents and Teams

## Reasoning Models

Reasoning Models are pre-trained models that are used to reason about the world. You can try any supported Agno model and if that model has reasoning capabilities, it will be used to reason about the problem. 

See the [examples](./models/).

### Separate Reasoning Model

A powerful feature of Agno is the ability to use a separate reasoning model from the main model. This is useful when you want to use a more powerful reasoning model than the main model.

See the [examples](./models/openai/reasoning_gpt_4_1.py).

## Reasoning Tools

By giving a model a “think” tool, we can greatly improve its reasoning capabilities by providing a dedicated space for structured thinking. This is a simple, yet effective approach to add reasoning to non-reasoning models.

See the [examples](./tools/).

## Reasoning Agents and Teams

Reasoning Agents are a new type of multi-agent system developed by Agno that combines chain of thought reasoning with tool use.

You can enable reasoning on any Agent by setting reasoning=True.

When an Agent with reasoning=True is given a task, a separate “Reasoning Agent” first solves the problem using chain-of-thought. At each step, it calls tools to gather information, validate results, and iterate until it reaches a final answer. Once the Reasoning Agent has a final answer, it hands the results back to the original Agent to validate and provide a response.

See the [examples](./agents/).

