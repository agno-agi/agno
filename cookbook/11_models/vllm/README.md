# vLLM Cookbook

vLLM is a fast and easy-to-use library for running LLM models locally.

## Setup

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Install vLLM package

```shell
pip install vllm
```

### 3. Serve a model (this downloads the model to your local machine the first time you run it)

```shell
vllm serve Qwen/Qwen2.5-7B-Instruct \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --dtype float16 \
    --max-model-len 2048 \
    --gpu-memory-utilization 0.9
```

## Using vLLM for Embeddings (Local Mode)

vLLM embedders can load and run embedding models locally without requiring a server.

### Setup for Local Embeddings

1. **Install vLLM** (if not already installed):
   ```bash
   pip install vllm
   ```

2. **Choose an embedding model**:

   Recommended models:
   - `intfloat/e5-mistral-7b-instruct` (4096 dimensions, 7B parameters)
   - `BAAI/bge-large-en-v1.5` (1024 dimensions, 335M parameters)
   - `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, 22M parameters)

3. **GPU Requirements**:
   - e5-mistral-7b-instruct: ~14GB VRAM
   - bge-large: ~2GB VRAM
   - all-MiniLM-L6-v2: ~500MB VRAM

4. **Usage**:
   ```python
   from agno.knowledge.embedder.vllm import VLLMEmbedder

   # Local mode (no server needed)
   embedder = VLLMEmbedder(
       id="intfloat/e5-mistral-7b-instruct",
       dimensions=4096
   )

   # Get embeddings
   embedding = embedder.get_embedding("Hello world")
   print(f"Embedding dimension: {len(embedding)}")
   ```

5. **Examples**:
   - Basic usage: `cookbook/knowledge/embedders/vllm_embedder.py`
   - With batching: `cookbook/knowledge/embedders/vllm_embedder_batching.py`

### Local vs Remote Mode

**Local Mode** (no server):
- Use `VLLMEmbedder(id="model-name")`
- Model loads directly into GPU/CPU
- No `base_url` needed
- Best for: Development, single-machine deployment

**Remote Mode** (requires server):
- Use `VLLMEmbedder(base_url="http://localhost:8000/v1")`
- Connects to running vLLM server
- Best for: Production, shared infrastructure

### Performance Tips

- Enable batching for multiple embeddings:
  ```python
  embedder = VLLMEmbedder(
      id="intfloat/e5-mistral-7b-instruct",
      enable_batch=True,
      batch_size=32  # Adjust based on GPU memory
  )
  ```

- Use smaller models for faster inference if precision isn't critical
- For CPU-only: Use smaller models (bge-small, MiniLM)

## Examples



```shell
python cookbook/models/vllm/basic.py
```

### Embeddings

- [vllm_embedder.py](../knowledge/embedders/vllm_embedder.py) - Local and remote embeddings
- [vllm_embedder_batching.py](../knowledge/embedders/vllm_embedder_batching.py) - Batch processing
