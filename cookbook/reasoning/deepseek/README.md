# Agentic Reasoning

Reasoning is an experimental feature that enables an Agent to think through a problem step-by-step before jumping into a response. The Agent works through different ideas, validating and correcting as needed. Once it reaches a final answer, it will validate and provide a response.

This cookbook demonstrates how to use DeepSeek to provide your Agent with reasoning.

> WARNING: Reasoning is an experimental feature and may not work as expected.

### Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### Install libraries

```shell
pip install -U openai agno
```

### Export your `OPENAI_API_KEY`

```shell
export OPENAI_API_KEY=***
```

### Export your `DEEPSEEK_API_KEY`

```shell
export OPENAI_API_KEY=***
```

### Run a reasoning agent that DOES NOT WORK

```shell
python cookbook/agent_concepts/reasoning/deepseek/strawberry.py
```

### Run other examples of reasoning agents

```shell
python cookbook/agent_concepts/reasoning/deepseek/logical_puzzle.py
```

```shell
python cookbook/agent_concepts/reasoning/deepseek/ethical_dilemma.py
```

### Run reasoning agent with tools

```shell
python cookbook/agent_concepts/reasoning/deepseek/finance_agent.py
```
