# Test Log — embedders

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| openai_embedder.py | PASS | Generated 1536-dim embeddings, inserted CV into PgVector |
| aws_bedrock_embedder.py | SKIP | Missing: AWS credentials |
| aws_bedrock_embedder_v4.py | SKIP | Missing: AWS credentials |
| azure_embedder.py | SKIP | Missing: Azure OpenAI credentials |
| cohere_embedder.py | SKIP | Missing: Cohere API key |
| fireworks_embedder.py | SKIP | Missing: Fireworks API key |
| gemini_embedder.py | SKIP | Missing: Gemini API key |
| huggingface_embedder.py | SKIP | Missing: Large model download required |
| jina_embedder.py | SKIP | Missing: Jina API key |
| langdb_embedder.py | SKIP | Missing: LangDB API key |
| mistral_embedder.py | SKIP | Missing: Mistral API key |
| nebius_embedder.py | SKIP | Missing: Nebius API key |
| ollama_embedder.py | SKIP | Missing: Local Ollama server |
| qdrant_fastembed.py | SKIP | Missing: fastembed package |
| sentence_transformer_embedder.py | SKIP | Missing: sentence-transformers package |
| together_embedder.py | SKIP | Missing: Together API key |
| voyageai_embedder.py | SKIP | Missing: VoyageAI API key |
| vllm_embedder_local.py | SKIP | Missing: Local vLLM server |
| vllm_embedder_remote.py | SKIP | Missing: Remote vLLM server |

## Summary

| Status | Count |
|--------|-------|
| PASS   | 1     |
| SKIP   | 18    |

Only openai_embedder tested per instructions. Others skipped (API keys/services not available).
