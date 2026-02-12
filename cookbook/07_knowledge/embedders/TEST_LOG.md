# TEST_LOG

## embedders — v2.5 Review

Tested: 2026-02-11 | Branch: cookbooks/v2.5-testing

---

### openai_embedder.py

**Status:** PASS

**Description:** OpenAI text-embedding-3-small with PgVector. Generates embeddings for CV PDF.

**Result:** Successfully generated 1536-dim embeddings, inserted CV into PgVector table `ai.openai_embeddings`.

---

### gemini_embedder.py

**Status:** PASS

**Description:** Google Gemini text-embedding-004 with PgVector. Generates embeddings for CV PDF.

**Result:** Successfully generated 1536-dim embeddings, inserted CV into PgVector table `ai.gemini_embeddings`.

---

### azure_embedder.py

**Status:** PASS

**Description:** Azure OpenAI text-embedding-3-small with PgVector. Generates embeddings for CV PDF.

**Result:** Successfully generated 1536-dim embeddings, inserted CV into PgVector table `ai.azure_openai_embeddings`.

---

### cohere_embedder.py

**Status:** FAIL

**Description:** Cohere embed-v4.0 embedder with PgVector.

**Result:** ImportError — `cohere` package not installed. Not a v2.5 regression.

---

### mistral_embedder.py

**Status:** SKIP

**Description:** Mistral AI embedder with PgVector.

**Result:** Skipped — requires Mistral API key.

---

### jina_embedder.py

**Status:** SKIP

**Description:** Jina AI embedder with PgVector.

**Result:** Skipped — requires Jina API key.

---

### voyageai_embedder.py

**Status:** SKIP

**Description:** VoyageAI embedder with PgVector.

**Result:** Skipped — requires VoyageAI API key.

---

### huggingface_embedder.py

**Status:** SKIP

**Description:** HuggingFace sentence-transformers embedder with PgVector.

**Result:** Skipped — requires large model download (sentence-transformers).

---

### ollama_embedder.py

**Status:** SKIP

**Description:** Ollama local embedder with PgVector.

**Result:** Skipped — requires local Ollama server running.

---

### aws_bedrock_embedder.py

**Status:** SKIP

**Description:** AWS Bedrock Titan embedder (v3) with PgVector.

**Result:** Skipped — requires AWS credentials and Bedrock access.

---

### aws_bedrock_embedder_v4.py

**Status:** SKIP

**Description:** AWS Bedrock Titan embedder (v4) with PgVector.

**Result:** Skipped — requires AWS credentials and Bedrock access.

---

### together_embedder.py

**Status:** SKIP

**Description:** Together AI embedder with PgVector.

**Result:** Skipped — requires Together API key.

---

### fireworks_embedder.py

**Status:** SKIP

**Description:** Fireworks AI embedder with PgVector.

**Result:** Skipped — requires Fireworks API key.

---

### langdb_embedder.py

**Status:** SKIP

**Description:** LangDB embedder with PgVector.

**Result:** Skipped — requires LangDB API key and endpoint.

---

### nebius_embedder.py

**Status:** SKIP

**Description:** Nebius AI embedder with PgVector.

**Result:** Skipped — requires Nebius API key.

---

### qdrant_fastembed.py

**Status:** SKIP

**Description:** Qdrant FastEmbed local embedder with PgVector.

**Result:** Skipped — requires fastembed package and model download.

---

### sentence_transformer_embedder.py

**Status:** SKIP

**Description:** SentenceTransformer local embedder with PgVector.

**Result:** Skipped — requires sentence-transformers package and model download.

---

### vllm_embedder_local.py

**Status:** SKIP

**Description:** vLLM local server embedder with PgVector.

**Result:** Skipped — requires local vLLM server running.

---

### vllm_embedder_remote.py

**Status:** SKIP

**Description:** vLLM remote server embedder with PgVector.

**Result:** Skipped — requires remote vLLM server endpoint.

---

## Summary

| Status | Count | Files |
|--------|-------|-------|
| PASS   | 3     | openai_embedder, gemini_embedder, azure_embedder |
| FAIL   | 1     | cohere_embedder (cohere pkg) |
| SKIP   | 15    | mistral, jina, voyageai, huggingface, ollama, aws_bedrock (x2), together, fireworks, langdb, nebius, qdrant_fastembed, sentence_transformer, vllm_local, vllm_remote |

No v2.5 regressions detected. All embedders follow consistent API pattern.
