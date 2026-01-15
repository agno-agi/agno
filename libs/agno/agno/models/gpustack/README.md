# GPUStack Provider for Agno

Native GPUStack API implementation for Agno, providing access to GPUStack's core AI model capabilities.

## Overview

This provider implements GPUStack's native API endpoints, offering:
- Chat completions
- Text embeddings
- Document reranking

## Installation

```bash
pip install agno[gpustack]
```

## Configuration

Set environment variables:
```bash
export GPUSTACK_SERVER_URL=http://localhost:9009
export GPUSTACK_API_KEY=your-api-key
```

## Usage Examples

### Chat Completions
```python
from agno.agent import Agent
from agno.models.gpustack import GPUStackChat

model = GPUStackChat(
    id="llama3",
    temperature=0.7,
    max_tokens=1000
)

agent = Agent(model=model)
response = agent.run("Explain quantum computing")
print(response.content)
```

### Embeddings
```python
from agno.models.gpustack import GPUStackEmbeddings

embeddings = GPUStackEmbeddings(id="bge-m3")
result = embeddings.embed("This is a test sentence")
vectors = embeddings.parse_embeddings_response(result)
```

### Document Reranking
```python
from agno.models.gpustack import GPUStackRerank

reranker = GPUStackRerank(id="bge-reranker-v2-m3")
documents = [
    "Python is a programming language",
    "GPUStack manages GPU clusters",
    "Machine learning uses GPUs"
]

result = reranker.rerank(
    query="GPU computing",
    documents=documents,
    top_n=2
)
```

### Unified Interface
```python
from agno.models.gpustack import GPUStack

# Create different model types with unified interface
chat = GPUStack(model_type="chat", id="llama3")
embeddings = GPUStack(model_type="embeddings", id="bge-m3")
reranker = GPUStack(model_type="rerank", id="bge-reranker-v2-m3")
```

## API Endpoints

The provider implements the following GPUStack API endpoints:

| Endpoint | Model Type | Description |
|----------|------------|-------------|
| `/v1/chat/completions` | Chat | Conversational AI |
| `/v1/completions` | Text | Text completion |
| `/v1/embeddings` | Embeddings | Text embeddings |
| `/v1/rerank` | Rerank | Document reranking |

## Error Handling

The provider includes comprehensive error handling:
- HTTP errors are caught and wrapped in `ModelProviderError`
- API errors are parsed from response bodies
- Detailed error messages include status codes and error types

## Advanced Features

### Streaming Support
Chat completions support streaming responses:
```python
for chunk in model.invoke_stream(messages):
    response = model.parse_provider_response_delta(chunk)
    if response.content:
        print(response.content, end="")
```

### Async Support
All models support async operations:
```python
result = await model.ainvoke(messages)
```

### Custom Parameters
Pass model-specific parameters:
```python
model = GPUStackChat(
    id="custom-model",
    timeout=60.0,
    max_retries=5
)
```

## Troubleshooting

1. **Connection Issues**: Verify GPUSTACK_SERVER_URL is accessible
2. **Authentication**: Ensure GPUSTACK_API_KEY is valid
3. **Model Not Found**: Check available models on your GPUStack instance
4. **Timeout Errors**: Increase timeout for large models/requests

## Links

- [GPUStack Documentation](https://docs.gpustack.ai/latest/)
- [GPUStack GitHub](https://github.com/gpustack/gpustack)
- [API Reference](http://your-gpustack-server/docs)