# API Route Cookbook

This cookbook demonstrates how to use [API Route](https://www.api-route.com) with the Agno framework. API Route is a unified AI model router and gateway providing access to Claude, GPT, Gemini, DeepSeek, Llama, and more through an OpenAI-compatible endpoint.

## Quick Start

### 1. Export your `APIROUTE_API_KEY`

Get your API key from [API Route](https://www.api-route.com).

```shell
export APIROUTE_API_KEY=sk-***
```

### 2. Run basic Agent

```shell
python cookbook/90_models/apiroute/basic.py
```

### 3. Run Agent with Tools

```shell
python cookbook/90_models/apiroute/tool_use.py
```

### 4. Run Agent with Structured Output

```shell
python cookbook/90_models/apiroute/structured_output.py
```

## Configuration

| Parameter | Environment Variable | Default | Description |
|-----------|---------------------|---------|-------------|
| `api_key` | `APIROUTE_API_KEY` | None | Your API Route API key |
| `id` | - | `claude-3-7-sonnet-20250219` | Model ID to use |
| `base_url` | - | `https://global.api-route.com/v1` | Base URL for API Route |
