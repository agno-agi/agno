# Model Providers

Agno supports **43+ LLM providers** through a unified `Model` interface. Every provider is a drop-in replacement — swap one line to change the model.

**Directory:** `libs/agno/agno/models/`

---

## Quick swap — same agent, different model

```python
# OpenAI
from agno.models.openai import OpenAIChat
model = OpenAIChat(id="gpt-4o")

# Anthropic
from agno.models.anthropic import Claude
model = Claude(id="claude-opus-4-5")

# Google Gemini
from agno.models.google import Gemini
model = Gemini(id="gemini-2.0-flash-exp")

# Local with Ollama
from agno.models.ollama import Ollama
model = Ollama(id="llama3.2")

# All work identically in an agent:
agent = Agent(model=model, tools=[...])
```

---

## Full provider table

### Major cloud providers

| Provider | Import | Example `id` values | Notes |
|----------|--------|---------------------|-------|
| **OpenAI** | `agno.models.openai.OpenAIChat` | `gpt-4o`, `gpt-4o-mini`, `gpt-5`, `o1`, `o3-mini` | Default choice; full tool support |
| **OpenAI Responses** | `agno.models.openai.OpenAIResponses` | `gpt-5-mini`, `gpt-4o` | New Responses API format |
| **Anthropic** | `agno.models.anthropic.Claude` | `claude-opus-4-5`, `claude-sonnet-4-5`, `claude-haiku-4-5` | Extended thinking support |
| **Google Gemini** | `agno.models.google.Gemini` | `gemini-2.0-flash-exp`, `gemini-1.5-pro` | Native multimodal |
| **Google Vertex AI** | `agno.models.vertexai.Gemini` | `gemini-1.5-pro`, `gemini-1.5-flash` | GCP-managed, enterprise SLA |
| **AWS Bedrock** | `agno.models.aws.Claude` | `anthropic.claude-3-5-sonnet-20241022-v2:0` | IAM auth, no API keys |
| **Azure OpenAI** | `agno.models.azure.AzureOpenAIChat` | `gpt-4o` (deployment name) | Azure tenant isolation |
| **Azure AI Foundry** | `agno.models.azure.AzureAIFoundry` | Model deployment names | Azure AI Studio models |

### Mid-tier cloud providers

| Provider | Import | Example `id` values | Notes |
|----------|--------|---------------------|-------|
| **Mistral** | `agno.models.mistral.MistralChat` | `mistral-large-latest`, `mistral-small-latest` | European GDPR-friendly |
| **Groq** | `agno.models.groq.Groq` | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768` | Fastest inference available |
| **Cohere** | `agno.models.cohere.CohereChat` | `command-r-plus`, `command-r` | Strong RAG/tool use |
| **xAI (Grok)** | `agno.models.xai.xAI` | `grok-3`, `grok-2` | Real-time web knowledge |
| **DeepSeek** | `agno.models.deepseek.DeepSeekChat` | `deepseek-chat`, `deepseek-reasoner` | Reasoning specialist, cost-effective |
| **Perplexity** | `agno.models.perplexity.Perplexity` | `sonar-pro`, `sonar` | Built-in web search |
| **Cerebras** | `agno.models.cerebras.CerebrasChat` | `llama3.1-70b` | Fast inference on custom hardware |
| **Together AI** | `agno.models.together.Together` | `meta-llama/Llama-3-70b-chat-hf` | Open-source model hosting |
| **Fireworks** | `agno.models.fireworks.Fireworks` | `accounts/fireworks/models/llama-v3-70b` | Fast open-source inference |
| **SambaNova** | `agno.models.sambanova.SambaNova` | `Meta-Llama-3.1-405B-Instruct` | LPU inference hardware |
| **NVIDIA** | `agno.models.nvidia.Nvidia` | `meta/llama-3.1-70b-instruct` | NVIDIA API gateway |
| **IBM WatsonX** | `agno.models.ibm.WatsonX` | `ibm/granite-3-8b-instruct` | Enterprise IBM stack |

### Local / self-hosted

| Provider | Import | Notes |
|----------|--------|-------|
| **Ollama** | `agno.models.ollama.Ollama` | Run any GGUF/Ollama model locally; no API key needed |
| **LLaMA.cpp** | `agno.models.llama_cpp.LlamaCpp` | Direct `.gguf` file inference |
| **LM Studio** | `agno.models.lmstudio.LMStudio` | LM Studio local server |
| **vLLM** | `agno.models.vllm.vLLM` | High-throughput production inference on own hardware |
| **HuggingFace** | `agno.models.huggingface.HuggingFace` | HF Inference Endpoints |

### Aggregators / routers

| Provider | Import | Notes |
|----------|--------|-------|
| **OpenRouter** | `agno.models.openrouter.OpenRouter` | 200+ models from one endpoint |
| **LiteLLM** | `agno.models.litellm.LiteLLM` | 100+ providers via LiteLLM proxy |
| **Portkey** | `agno.models.portkey.Portkey` | Enterprise router with fallbacks, caching, observability |
| **Requesty** | `agno.models.requesty.Requesty` | Model abstraction layer |

### Specialised / regional

| Provider | Import | Notes |
|----------|--------|-------|
| **DashScope (Alibaba)** | `agno.models.dashscope.DashScope` | Qwen models |
| **Moonshot** | `agno.models.moonshot.Moonshot` | Chinese LLM provider |
| **InternLM** | `agno.models.internlm.InternLM` | Shanghai AI Lab models |
| **Nebius** | `agno.models.nebius.Nebius` | Nebius cloud |
| **SiliconFlow** | `agno.models.siliconflow.SiliconFlow` | Chinese inference cloud |
| **Deepinfra** | `agno.models.deepinfra.DeepInfra` | Fast open-source hosting |
| **CometAPI** | `agno.models.cometapi.CometAPI` | API aggregator |
| **N1N** | `agno.models.n1n.N1N` | N1N API |
| **Nexus** | `agno.models.nexus.Nexus` | Nexus platform |
| **Vercel AI** | `agno.models.vercel.Vercel` | Vercel AI SDK |
| **AimlAPI** | `agno.models.aimlapi.AimlAPI` | AIML API router |
| **LangDB** | `agno.models.langdb.LangDB` | Databricks endpoint |

---

## Provider-specific features

### Reasoning models (extended thinking)

```python
# OpenAI o1/o3 — native chain-of-thought
from agno.models.openai import OpenAIChat
agent = Agent(model=OpenAIChat(id="o1"), reasoning=True)

# Anthropic extended thinking
from agno.models.anthropic import Claude
agent = Agent(model=Claude(id="claude-opus-4-5"), reasoning=True)

# DeepSeek R1 — open-source reasoning
from agno.models.deepseek import DeepSeekChat
agent = Agent(model=DeepSeekChat(id="deepseek-reasoner"), reasoning=True)
```

### Vision / multimodal

```python
from agno.media import Image
from agno.models.openai import OpenAIChat

agent = Agent(model=OpenAIChat(id="gpt-4o"))
agent.run(
    "Describe what you see",
    images=[Image(url="https://example.com/photo.jpg")],
)
```

### Streaming

All providers that support it expose the same streaming interface:

```python
for chunk in agent.run("Tell me about Paris", stream=True):
    print(chunk.content, end="")
```

### Structured output

Pydantic-based structured output works with any provider that supports JSON mode or tool-calling:

```python
from pydantic import BaseModel
class Person(BaseModel):
    name: str
    age: int

agent = Agent(model=OpenAIChat(id="gpt-4o"), output_schema=Person)
result = agent.run("Extract: John Smith is 32 years old")
person: Person = result.content
```

---

## Model base class capabilities

All models inherit from `agno.models.base.Model` and expose:

| Method | Description |
|--------|-------------|
| `response(messages)` | Synchronous single call |
| `async_response(messages)` | Async single call |
| `stream(messages)` | Sync streaming generator |
| `async_stream(messages)` | Async streaming generator |

Tracked per call:
- Input tokens, output tokens, cached tokens, reasoning tokens
- Cost in USD (where provider exposes pricing)
- Time-to-first-token and total latency

---

## Configuring API keys

Keys are read from environment variables or passed directly:

```python
import os
os.environ["OPENAI_API_KEY"] = "sk-..."
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."
os.environ["GOOGLE_API_KEY"] = "AIza..."

# Or pass directly (not recommended in production)
from agno.models.openai import OpenAIChat
model = OpenAIChat(id="gpt-4o", api_key="sk-...")
```

---

## Switching providers — zero code change to agent logic

```python
# Development: cheap, fast
model = OpenAIChat(id="gpt-4o-mini")

# Production: high quality
model = Claude(id="claude-opus-4-5")

# Cost-saving: open source
model = Ollama(id="llama3.2")

# Same agent either way:
agent = Agent(model=model, tools=[my_tools], instructions="...")
```
