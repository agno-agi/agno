# Observability

**Observability** enables monitoring, tracking, and analyzing your Agno agents in production. This directory contains cookbooks that demonstrate how to integrate various observability platforms with your agents.

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

# Opik via OpenInference
pip install opik opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-agno

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

### OpenTelemetry via OpenInference

OpenTelemetry provides standardized observability that works across multiple platforms. Install the base requirements:

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp openinference-instrumentation-agno
```

| Platform | Description | Additional Dependencies |
|----------|-------------|------------------------|
| **Langfuse** | Comprehensive tracing and analytics | `pip install langfuse` |
| **Opik** | Open-source tracing, evaluations, optimization and debugging for LLM/agent workflows | `pip install opik` |
| **Arize Phoenix** | Open-source observability with real-time monitoring | `pip install arize-phoenix` |
| **LangSmith** | LangChain's monitoring and debugging platform | `pip install langsmith` |

**Files:**
- **[Langfuse via OpenInference](./langfuse_via_openinference.py)** - Langfuse integration
- **[Opik via OpenInference](./opik_via_openinference.py)** - Opik integration
- **[Arize Phoenix via OpenInference](./arize_phoenix_via_openinference.py)** - Phoenix integration  
- **[LangSmith via OpenInference](./langsmith_via_openinference.py)** - LangSmith integration

### Platform-Specific Integrations

Direct integrations with platform-specific SDKs:

| Platform | Description | Installation | File |
|----------|-------------|--------------|------|
| **AgentOps** | Simple agent monitoring with automatic session tracking | `pip install agentops` | **[AgentOps](./agent_ops.py)** |
| **Weave** | Weights & Biases experiment tracking and monitoring | `pip install weave` | **[Weave](./weave_op.py)** |

### Teams Examples

|  | Description | Files |
|----------|-------------|-------|
| **Teams** | Multi-agent observability examples | **[Langfuse Team](./teams/langfuse_via_openinference_team.py)**<br>**[Langfuse Async Team](./teams/langfuse_via_openinference_async_team.py)** |

## Setup Instructions

Each platform requires API keys and specific configuration. See individual files for detailed setup steps and authentication requirements.
