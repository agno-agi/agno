# Multimodal Teams

Teams handling text, images, audio, and video for comprehensive multimedia processing.

## Setup

```bash
pip install agno openai
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

```python
from agno.team import Team
from agno.media import Audio

team = Team(
    members=[transcript_agent, audio_agent, text_agent],
    model=OpenAIChat(id="gpt-4o"),
)

team.print_response(
    "Give a transcript of this audio conversation",
    audio=[Audio(content=audio_content)],
)
```

## Examples

- **[audio_sentiment_analysis.py](./audio_sentiment_analysis.py)** - Audio sentiment analysis with teams
- **[audio_to_text.py](./audio_to_text.py)** - Audio transcription and processing
- **[generate_image_with_team.py](./generate_image_with_team.py)** - Collaborative image generation
- **[image_to_image_transformation.py](./image_to_image_transformation.py)** - Image transformation workflows
- **[image_to_structured_output.py](./image_to_structured_output.py)** - Structured data from images
- **[image_to_text.py](./image_to_text.py)** - Image description and storytelling
- **[video_caption_generation.py](./video_caption_generation.py)** - Video analysis and captioning
