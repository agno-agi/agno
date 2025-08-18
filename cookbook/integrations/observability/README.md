# Observability

**Observability** enables monitoring, tracking, and analyzing your Agno agents in production. This directory contains cookbooks that demonstrate how to integrate various observability platforms with your agents.

## Features

- **Metrics**: Measure agent performance, response times, and usage
- **Logging**: Capture detailed logs of agent conversations and tool usage
- **Monitoring**: Real-time visibility into agent health and behavior 
- **Analytics**: Analyze patterns and optimize agent performance 

## Getting Started

### 1. Setup Environment

```bash
pip install agno openai
```

### 2. Choose Your Platform

Install platform-specific dependencies:

```bash
# AgentOps
pip install agentops

# Langfuse via OpenInference  
pip install langfuse opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-agno

# Weave
pip install weave

# Arize Phoenix
pip install arize-phoenix openinference-instrumentation-agno

# LangSmith
pip install langsmith openinference-instrumentation-agno
```

### 3. Basic Agent Monitoring

```python
import agentops
from agno.agent import Agent
from agno.models.openai import OpenAIChat

# Initialize monitoring
agentops.init()

# Create monitored agent
agent = Agent(model=OpenAIChat(id="gpt-4o"))
response = agent.run("Your query here")
```

## Available Platforms

### AgentOps (`agent_ops.py`)
Simple agent monitoring with automatic session tracking.

### Langfuse (`langfuse_via_openinference.py`)
Comprehensive tracing and analytics via OpenInference instrumentation.

### Weave (`weave_op.py`) 
Weights & Biases integration for experiment tracking and monitoring.

### Arize Phoenix (`arize_phoenix_via_openinference.py`)
Open-source observability platform with real-time monitoring.

### LangSmith (`langsmith_via_openinference.py`)
LangChain's monitoring and debugging platform integration.

### Teams (`teams/`)
Observability examples for multi-agent teams and coordination.

## Setup Instructions

Each platform requires API keys and specific configuration. See individual files for detailed setup steps and authentication requirements.
