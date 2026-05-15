# Gemini Interactions API

Examples using Google's Interactions API with Agno.

The Interactions API is a new primitive that provides:

- **Server-side conversation history** - Only send new messages each turn, not the full history
- **Implicit caching** - Prior turns are cached server-side for lower costs and latency
- **Typed execution steps** - Responses contain discriminated content types for better observability
- **Background execution** - Support for long-running tasks
- **Multimodal I/O** - Image, audio, video, and document inputs; image and audio generation

## Setup

```bash
pip install -U google-genai
export GOOGLE_API_KEY=your-api-key
```

Requires `google-genai>=2.0.0`.

## Examples

| File | Description |
|------|-------------|
| `basic.py` | Basic text generation (sync, async, streaming) |
| `tool_use.py` | Function calling with external tools |
| `multi_turn.py` | Multi-turn conversation with server-side history |
| `thinking.py` | Reasoning/thinking mode |
| `search.py` | Built-in Google Search tool |
| `image_understanding.py` | Image analysis from URLs, files, and bytes |
| `image_generation.py` | Generate images with response_modalities |
| `audio_understanding.py` | Audio analysis and transcription |
| `video_understanding.py` | Video analysis from URLs |
| `document_processing.py` | PDF document processing |
| `structured_output.py` | Structured JSON output with Pydantic schemas |

## Usage

```python
from agno.agent import Agent
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview"),
    markdown=True,
)
agent.print_response("Hello!")
```

### Image Understanding

```python
from agno.media import Image

agent.print_response(
    "What is in this image?",
    images=[Image(url="https://example.com/photo.jpg")],
)
```

### Structured Output

```python
from pydantic import BaseModel

class MovieReview(BaseModel):
    title: str
    rating: float

agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview"),
    output_schema=MovieReview,
)
```

### Inference Tiers

```python
# Lower cost, higher latency
agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview", service_tier="flex"),
)

# Lowest latency
agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview", service_tier="priority"),
)
```

## Notes

- The Interactions API is experimental and may change in future versions
- Interactions are stored server-side for 55 days (paid) / 1 day (free tier)
- System instructions and tools must be re-sent each turn (they are interaction-scoped)
- Set `store=False` to disable server-side persistence
