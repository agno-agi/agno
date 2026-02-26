"""
8. Image Understanding
======================
Gemini can analyze images -- describe content, read text, answer questions.
Pass images via URL or local file path.

Run:
    python cookbook/gemini_3/8_image_input.py

Example prompt:
    "Tell me about this image and give me the latest news about it."
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
image_agent = Agent(
    name="Image Analyst",
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions="You are an image analysis expert. Describe what you see in detail and provide relevant context.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    image_agent.print_response(
        "Tell me about this image and give me the latest news about it.",
        images=[
            Image(
                url="https://upload.wikimedia.org/wikipedia/commons/b/bf/Krakow_-_Kosciol_Mariacki.jpg"
            ),
        ],
        stream=True,
    )
