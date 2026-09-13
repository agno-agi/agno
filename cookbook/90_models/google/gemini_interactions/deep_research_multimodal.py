"""
Gemini Interactions - Deep Research with multimodal input
==========================================================

Deep Research accepts images and documents (PDFs) as input, then conducts
web-based research grounded in that content. Pass them as Agno `Image` /
`File` objects with a URL (GCS / Gemini URIs pass through; regular HTTP
URLs are downloaded and base64-encoded automatically).
"""

from agno.agent import Agent
from agno.media import File, Image
from agno.models.google import GeminiInteractions

agent = Agent(
    model=GeminiInteractions(
        agent="deep-research-preview-04-2026",
        thinking_summaries="auto",
    ),
    markdown=True,
)

if __name__ == "__main__":
    # --- Image-grounded research ---
    agent.print_response(
        "Analyze the interspecies dynamics in this image and research the "
        "symbiotic relationships shown.",
        images=[
            Image(
                url="https://storage.googleapis.com/generativeai-downloads/images/generated_elephants_giraffes_zebras_sunset.jpg"
            )
        ],
    )

    # --- Document-grounded research ---
    agent.print_response(
        "What is this document about, and how does it relate to current "
        "research trends?",
        files=[File(url="https://arxiv.org/pdf/1706.03762")],
    )
