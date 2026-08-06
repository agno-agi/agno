# yt-dlp Tools

CLI-driven audio/video extraction via [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## APIs

| Tool | Use Case |
|------|----------|
| `extract_metadata` | Quick research without downloading |
| `download_video` | Save media to `download_dir` |
| `download_audio` | MP3 only |
| `list_supported_sites` | Filter supported sites |

## Cookbooks

| File | Description |
|------|-------------|
| `youtube_video_research.py` | Single-agent video summarizer |

## Setup

```bash
pip install yt-dlp
# ffmpeg must be on PATH for format merging
export OPENAI_API_KEY=<your-api-key>
```

## Quick Start

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from yt_dlp_tools import YtDlpTools

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[YtDlpTools(download_dir="./tmp/yt_dlp")],
)

agent.print_response(
    "Fetch metadata for this URL: https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    stream=True,
)
```
