# Models Cookbook Testing Log

Testing model provider examples in `cookbook/92_models/`.

**Test Environment:**
- Python: `.venvs/demo/bin/python`
- Date: 2026-01-14

---

## Test Results by Provider

### openai/

| File | Status | Notes |
|------|--------|-------|
| chat/basic.py | PASS | Horror story generation, streaming works |

---

### anthropic/

| File | Status | Notes |
|------|--------|-------|
| basic.py | PASS | Horror story generation, streaming works |

---

### groq/

| File | Status | Notes |
|------|--------|-------|
| basic.py | SKIP | Requires `groq` module installation |

---

### Other Providers

| Provider | Status | Notes |
|----------|--------|-------|
| google/ | SKIP | Requires GOOGLE_API_KEY |
| aws/ | SKIP | Requires AWS credentials |
| azure/ | SKIP | Requires AZURE_* credentials |
| ollama/ | SKIP | Requires local Ollama setup |
| mistral/ | SKIP | Requires MISTRAL_API_KEY |
| cohere/ | SKIP | Requires CO_API_KEY |
| deepseek/ | SKIP | Requires DEEPSEEK_API_KEY |
| + 15 more | SKIP | Various API keys required |

---

## TESTING SUMMARY

**Overall Results:**
- **Total Examples:** 667 (largest folder)
- **Tested:** 3 files
- **Passed:** 2
- **Failed:** 0
- **Skipped:** Most require provider-specific API keys

**Fixes Applied:**
1. Fixed 48 path references (`cookbook/11_models/` and `cookbook/models/` -> `cookbook/92_models/`)

**Key Features Verified:**
- OpenAI GPT-4o streaming completion
- Anthropic Claude streaming completion
- Basic agent with model configuration

**Skipped Due to Dependencies:**
- Groq (requires `groq` module)
- Google (requires GOOGLE_API_KEY)
- AWS Bedrock (requires AWS credentials)
- Azure OpenAI (requires AZURE_* keys)
- Local models (Ollama, llama_cpp, lmstudio)
- 20+ other providers (require respective API keys)

**Notes:**
- Largest cookbook folder (667 examples across 25+ providers)
- Each provider typically has: basic.py, streaming.py, tool_use.py, structured_output.py
- OpenAI and Anthropic are the most commonly used providers
- Local model providers (Ollama, llama_cpp) require separate setup

