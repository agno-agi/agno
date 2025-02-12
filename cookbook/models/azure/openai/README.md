# Azure OpenAI Cookbook

> Note: Fork and clone this repository if needed

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export environment variables

Navigate to the AzureOpenAI on the [Azure Portal](https://portal.azure.com/) and create a service. Then, using the Azure AI Foundry portal, create a deployment and set your environment variables.

```shell
export AZURE_OPENAI_API_KEY=***
export AZURE_OPENAI_ENDPOINT="https://<your-resource-name>.openai.azure.com/openai/deployments/<your-deployment-name>"
export AZURE_API_VERSION="2024-10-21"  # Optional
export AZURE_DEPLOYMENT=***  # Optional
```

### 3. Install libraries

```shell
pip install -U openai duckduckgo-search duckdb yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/azure/openai/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/azure/openai/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Search

```shell
python cookbook/models/azure/openai/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/azure/openai/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/azure/openai/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/azure/openai/knowledge.py
```
