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
pip install -U google-generativeai ddgs yfinance agno
```

### 4. Run basic Agent

- Streaming on

```shell
python cookbook/models/google/gemini/basic_stream.py
```

- Streaming off

```shell
python cookbook/models/google/gemini/basic.py
```

### 5. Run Agent with Tools

- DuckDuckGo Agent

```shell
python cookbook/models/google/gemini/tool_use.py
```

### 6. Run Agent that returns structured output

```shell
python cookbook/models/google/gemini/structured_output.py
```

### 7. Run Agent that uses storage

```shell
python cookbook/models/google/gemini/storage.py
```

### 8. Run Agent that uses knowledge

```shell
python cookbook/models/google/gemini/knowledge.py
```

### 9. Run Agent that interprets an audio file

```shell
python cookbook/models/google/gemini/audio_input_bytes_content.py
```

### 10. Run Agent that analyzes an image

```shell
python cookbook/models/google/gemini/image_agent.py
```

or

```shell
python cookbook/models/google/gemini/image_agent_file_upload.py
```

### 11. Run Agent that analyzes a video

```shell
python cookbook/models/google/gemini/video_agent_input_bytes_content.py
```

### 12. Run Agent that uses flash thinking mode from Gemini

```shell
python cookbook/models/google/gemini/flash_thinking_agent.py
```

### 13. Run Agent with thinking budget configuration

```shell
python cookbook/models/google/gemini/agent_with_thinking_budget.py
```

### 14. Run agent with URL context

```shell
python cookbook/models/google/gemini/url_context.py
```

### 15. Run agent with URL context + Search Grounding

```shell
python cookbook/models/google/gemini/url_context_with_search.py
```

### 16. Run agent with Google Search

```shell
python cookbook/models/google/gemini/search.py
```

### 17. Run agent with Google Search Grounding

```shell
python cookbook/models/google/gemini/grounding.py
```

### 18. Run agent with Vertex AI Search

```shell
python cookbook/models/google/gemini/vertex_ai_search.py
```

