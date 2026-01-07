"""Image analysis with optional base64 encoding

Cloud APIs (DashScope): Use URL directly (~85 tokens)
Local Models (LM Studio/vLLM/Ollama): Set use_base64=True (~750-1500 tokens)
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.dashscope import DashScope
from agno.tools.duckduckgo import DuckDuckGoTools

MODEL_ID = "qwen3-vl-2b-instruct"
BASE_URL = "http://localhost:1234/v1"

# Cloud deployment
agent = Agent(
    model=DashScope(id=MODEL_ID, base_url=BASE_URL),
    tools=[DuckDuckGoTools()],
    markdown=True,
)

# Example 1: Cloud API (uses URL directly - more efficient)
agent.print_response(
    "Analyze this image in detail and tell me what you see. Also search for more information about the subject.",
    images=[
        Image(
            url="https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
            use_base64=True,
        )
    ],
    stream=True,
)
