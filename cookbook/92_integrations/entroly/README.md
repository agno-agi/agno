# Entroly — Context Compression for Agno Agents

Reduce LLM API costs by 70-95% when running Agno agents by routing requests through the [Entroly](https://github.com/juyterman1000/entroly) local proxy.

## What Entroly Does

Entroly sits between your Agno agents and the LLM provider, compressing context using knapsack optimization, entropy scoring, and cache alignment — without losing answer quality.

## Setup

```bash
pip install entroly
entroly proxy  # starts on http://localhost:9377
```

## Examples

- **[entroly_proxy_agent.py](./entroly_proxy_agent.py)** — Run an Agno agent through the Entroly proxy for automatic cost reduction
