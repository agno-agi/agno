# Model Providers

Examples for all supported LLM providers in Agno.

## Providers

| Provider | Description | API Key |
|:---------|:------------|:--------|
| **OpenAI** | GPT-4, GPT-4o, o1, o3 | `OPENAI_API_KEY` |
| **Anthropic** | Claude 3.5, Claude Opus | `ANTHROPIC_API_KEY` |
| **Google** | Gemini Pro, Flash | `GOOGLE_API_KEY` |
| **AWS Bedrock** | Claude, Llama on AWS | AWS credentials |
| **Azure OpenAI** | OpenAI on Azure | `AZURE_*` |
| **Groq** | Fast Llama, Mixtral | `GROQ_API_KEY` |
| **DeepSeek** | DeepSeek R1 reasoning | `DEEPSEEK_API_KEY` |
| **Mistral** | Mistral, Mixtral | `MISTRAL_API_KEY` |
| **Cohere** | Command R+ | `CO_API_KEY` |
| **Ollama** | Local models | Local |
| **LM Studio** | Local GUI | Local |
| **llama.cpp** | Local GGUF | Local |

## Getting Started

```bash
# Install provider
uv pip install agno openai

# Set API key
export OPENAI_API_KEY=your-key

# Run example
python cookbook/92_models/openai/basic.py
```

## Common Patterns

Each provider folder contains:
- `basic.py` - Simple completion
- `streaming.py` - Streaming responses
- `tool_use.py` - Function calling
- `structured_output.py` - Pydantic output
