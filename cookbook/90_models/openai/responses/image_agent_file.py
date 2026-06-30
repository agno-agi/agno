from pathlib import Path

import httpx
from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-4o"),
    markdown=True,
)

image_path = Path(__file__).parent.joinpath("sample.jpg")

if not image_path.exists():
    resp = httpx.get(
        "https://picsum.photos/id/1/640/480",
        headers={"User-Agent": "agno-cookbook/1.0"},
        follow_redirects=True,
    )
    image_path.write_bytes(resp.content)

# Auto-detect MIME from file extension (.jpg -> image/jpeg)
agent.print_response(
    "Tell me about this image.",
    images=[Image(filepath=image_path)],
    stream=True,
)

# Explicit MIME type override
agent.print_response(
    "What do you see?",
    images=[Image(filepath=image_path, mime_type="image/jpeg")],
    stream=True,
)
