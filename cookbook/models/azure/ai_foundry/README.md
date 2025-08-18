# Azure AI Interface Cookbook

> Note: Fork and clone this repository if needed
>
> Note: This cookbook is for the Azure AI Interface model. It uses the `AzureAIFoundry` class with the `Phi-4` model. Please change the model ID to the one you want to use.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export environment variables

Navigate to the Azure AI Foundry on the [Azure Portal](https://portal.azure.com/) and create a service. Then, using the Azure AI Foundry portal, create a deployment and set your environment variables.

```shell
export AZURE_API_KEY=***
export AZURE_ENDPOINT="https://<your-host-name>.services.ai.azure.com/models"
export AZURE_API_VERSION="2024-05-01-preview"
```

You can get the endpoint from the Azure AI Foundry portal. Click on the deployed model and copy the "Target URI"

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
