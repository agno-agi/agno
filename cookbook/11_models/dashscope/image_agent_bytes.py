"""Image analysis using local file with base64 encoding"""

import base64
from pathlib import Path

import requests
from agno.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope
from agno.tools.duckduckgo import DuckDuckGoTools

MODEL_ID = "qwen3-vl-2b-instruct"
BASE_URL = "http://localhost:1234/v1"


def encode_image_to_base64(image_path: Path) -> str:
    """Read image file and convert to base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def download_image(url: str, save_path: Path) -> None:
    """Download image from URL and save to file"""
    print(f"Downloading image from {url}...")
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    save_path.write_bytes(response.content)
    print(f"Image saved to {save_path}")


# You can use a local image file or download one
image_path = Path(__file__).parent.joinpath("sample.jpg")
image_url = (
    "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"
)

# Download image if it doesn't exist
if not image_path.exists():
    download_image(image_url, image_path)

# Encode image to base64
image_base64 = encode_image_to_base64(image_path)

agent = Agent(
    model=DashScope(id=MODEL_ID, base_url=BASE_URL),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

agent.print_response(
    "Analyze this image in detail. Describe what you see and search for more information.",
    images=[Image(url=f"data:image/jpeg;base64,{image_base64}")],
    stream=True,
)
