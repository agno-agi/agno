# Google Gemini Cookbook

> Note: Fork and clone this repository if needed
>
> This cookbook is for testing Gemini models.

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export environment variables

If you want to use the Gemini API, you need to export the following environment variables:

```shell
export GOOGLE_API_KEY=***
```

If you want to use Vertex AI, you need to export the following environment variables:

```shell
export GOOGLE_GENAI_USE_VERTEXAI="true"
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="your-location"
```

### 3. Install libraries

```shell
uv pip install -U google-generativeai ddgs yfinance agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/google/gemini/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Agent

```shell
python cookbook/90_models/google/gemini/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/90_models/google/gemini/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/90_models/google/gemini/db.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/90_models/google/gemini/knowledge.py
```

### 9. Run Agent that interprets an audio file

```shell
python cookbook/90_models/google/gemini/audio_input_bytes_content.py
```

### 10. Run Agent that analyzes an image

```shell
python cookbook/90_models/google/gemini/image_input.py
```

or

```shell
python cookbook/90_models/google/gemini/image_input_file_upload.py
```

### 11. Run Agent that analyzes a video

```shell
python cookbook/90_models/google/gemini/video_input_bytes_content.py
```

### 12. Run Agent with thinking budget configuration

```shell
python cookbook/90_models/google/gemini/agent_with_thinking_budget.py
```

### 13. Run agent with URL context

```shell
python cookbook/90_models/google/gemini/url_context.py
```

### 14. Run agent with URL context + Search Grounding

```shell
python cookbook/90_models/google/gemini/url_context_with_search.py
```

### 15. Run agent with Google Search

```shell
python cookbook/90_models/google/gemini/search.py
```

### 16. Run agent with Google Search Grounding

```shell
python cookbook/90_models/google/gemini/grounding.py
```

### 17. Run agent with Vertex AI Search

```shell
python cookbook/90_models/google/gemini/vertex_ai_search.py
```

### 18. Run a basic agent on Gemini 3.8 Flash

```shell
python cookbook/90_models/google/gemini/gemini_3_8_flash.py
```

### 19. Run a market brief agent on Gemini 3.8 Flash

Combines Google Search grounding, URL context, and a structured output schema
to produce a source-backed competitive brief.

```shell
python cookbook/90_models/google/gemini/gemini_3_8_flash_market_brief.py
```
