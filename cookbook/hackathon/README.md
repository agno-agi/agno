# Agno Hackathon

## Setup

### Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### Export your API keys

```shell
export OPENAI_API_KEY=***
...
```

### Install libraries

```shell
pip install -U openai agno
```

## Example - Basic Agent

```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    markdown=True
)
agent.print_response("Tell me about a breaking news story from New York.", stream=True)
```

## Example - Image Agent

```python
from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    markdown=True,
)

agent.print_response(
    "Tell me about this image",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
        )
    ],
    stream=True,
)
```

## Example - Audio Agent

```python
from agno.agent import Agent
from agno.media import Audio
from agno.models.openai import OpenAIChat

url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"

agent = Agent(
    model=OpenAIChat(id="gpt-4o-audio-preview", modalities=["text"]),
    markdown=True,
)
agent.print_response("What is in this audio?", audio=[Audio(url=url, format="wav")])
```

## Example - Video Agent

```python
from pathlib import Path

from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash-exp"),
    markdown=True,
)

# Run: `wget https://storage.googleapis.com/generativeai-downloads/images/GreatRedSpot.mp4` to download a sample video
video_path = Path(__file__).parent.joinpath("sample_video.mp4")

agent.print_response("Tell me about this video?", videos=[Video(filepath=video_path)])
```


The following model providers provide the most multimodal support:
- Gemini - Image, Audio and Video input
- OpenAI - Image and Audio input
- Anthropic - Image input
- Groq - Image input
- Mistral - Image input

For more information, see the [model providers](https://docs.agno.com/models/compatibility#multimodal-support) documentation.

## Model usage:

```cookbook/hackathon/models```

##  Examples:

```cookbook/hackathon/examples```

## Multimodal Examples:

```cookbook/hackathon/multimodal```
