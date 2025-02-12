import requests
from agno.agent import Agent
from agno.media import Image
from agno.models.mistral.mistral import MistralChat

agent = Agent(
    model=MistralChat(id="pixtral-12b-2409"),
    show_tool_calls=True,
    markdown=True,
)

image_url = (
    "https://tripfixers.com/wp-content/uploads/2019/11/eiffel-tower-with-snow.jpeg"
)


def fetch_image_bytes(url: str) -> bytes:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.content


image_bytes_from_url = fetch_image_bytes(image_url)

agent.print_response(
    "Tell me about this image.",
    images=[
        Image(content=image_bytes_from_url),
    ],
)
