# Embedder Comparison

Comparison of supported embedding providers.

## Quick Recommendation

| Use Case | Recommended Embedder | Why |
|----------|---------------------|-----|
| General Purpose | OpenAI text-embedding-3-small | Good quality, low cost |
| High Quality | OpenAI text-embedding-3-large | Best quality, higher cost |
| Multilingual | Sentence Transformers (paraphrase-multilingual) | Local, free, many languages |
| Local/Private | Ollama or vLLM | No API calls, data stays local |
| AWS | AWS Bedrock | Native AWS integration |

## Provider Matrix

| Provider | Models | Dimensions | Local | Cost |
|----------|--------|------------|-------|------|
| OpenAI | text-embedding-3-small, text-embedding-3-large | 1536, 3072 | No | Low |
| Cohere | embed-english-v3.0, embed-multilingual-v3.0 | 1024 | No | Low |
| AWS Bedrock | titan-embed-text-v2, cohere.embed | Varies | No | Low |
| Azure OpenAI | text-embedding-3-small | 1536 | No | Low |
| Gemini | text-embedding-004 | 768 | No | Free tier |
| Mistral | mistral-embed | 1024 | No | Low |
| Voyage AI | voyage-3 | 1024 | No | Low |
| Fireworks | nomic-embed-text-v1.5 | 768 | No | Low |
| Together | togethercomputer/m2-bert | 768 | No | Low |
| Jina | jina-embeddings-v3 | 1024 | No | Low |
| HuggingFace | Various | Varies | Yes | Free |
| Sentence Transformers | Various | Varies | Yes | Free |
| Ollama | Various | Varies | Yes | Free |
| vLLM | Various | Varies | Yes | Free |

## Notes

- **Dimensions** affect storage size and search speed - smaller is faster but less precise
- **Local** embedders process data on your machine - no API calls needed
- All embedders use the same Knowledge API - switching only requires changing the embedder parameter
- For production, start with OpenAI text-embedding-3-small and upgrade only if quality demands it
