# multimodal

Examples for image/audio/video processing patterns.

## Files
- `audio_input_output.py` - Demonstrates audio input output.
- `audio_sentiment_analysis.py` - Demonstrates audio sentiment analysis.
- `audio_streaming.py` - Demonstrates audio streaming.
- `audio_to_text.py` - Demonstrates audio to text.
- `image_to_audio.py` - Demonstrates image to audio.
- `image_to_image.py` - Demonstrates image to image.
- `image_to_structured_output.py` - Demonstrates image to structured output.
- `image_to_text.py` - Demonstrates image to text.
- `media_input_for_tool.py` - Demonstrates media input for tool.
- `video_caption.py` - Demonstrates video caption.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`
