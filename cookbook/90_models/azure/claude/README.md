# Azure AI Foundry Claude

[Anthropic on Azure AI Foundry](https://docs.anthropic.com/en/docs/partner-models/azure-ai)

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your Azure credentials

```shell
export ANTHROPIC_FOUNDRY_API_KEY=***
export ANTHROPIC_FOUNDRY_RESOURCE=your-resource-name
```

Or use a base URL directly instead of resource:

```shell
export ANTHROPIC_FOUNDRY_BASE_URL=https://your-resource.services.ai.azure.com
```

### 3. Install libraries

```shell
uv pip install -U anthropic agno
```

### 4. Run basic agent

```shell
python cookbook/90_models/azure/claude/basic.py
```

### 5. Run Agent with Tools

```shell
uv pip install -U ddgs
python cookbook/90_models/azure/claude/tool_use.py
```

### 6. Run Agent with Extended Thinking

```shell
python cookbook/90_models/azure/claude/thinking.py
```
