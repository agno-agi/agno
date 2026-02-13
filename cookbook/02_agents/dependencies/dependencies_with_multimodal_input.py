"""
Dependencies In Context with Multimodal Input
==============================================

This example demonstrates that `add_dependencies_to_context=True` works
correctly with multimodal input (text + images). Dependencies are injected
into the text part of multimodal messages.

Multimodal content formats supported:
- OpenAI format: [{"type": "text", "text": "..."}, {"type": "image_url", ...}]
- Message with images: Message(role="user", content="...", images=[...])
- List[Message] with multimodal content
"""

from agno.agent import Agent
from agno.media import Image
from agno.models.message import Message
from agno.models.openai import OpenAIChat


def get_image_analysis_context() -> dict:
    """Return context for image analysis (simulated)."""
    return {
        "user_preferences": {
            "style": "detailed",
            "focus_areas": ["architecture", "nature", "people"],
        },
        "analysis_guidelines": [
            "Describe the main subject",
            "Note colors and lighting",
            "Identify any text or symbols",
        ],
    }


def get_current_user() -> dict:
    """Return current user info (simulated)."""
    return {
        "name": "Alice",
        "role": "Designer",
        "expertise": ["UI/UX", "Visual Design", "Brand Identity"],
    }


# ---------------------------------------------------------------------------
# Create Agent with dependencies
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    # Dependencies are resolved when the agent runs
    dependencies={
        "image_analysis_context": get_image_analysis_context,
        "current_user": get_current_user,
    },
    # This flag injects dependencies into the user message context
    add_dependencies_to_context=True,
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run Agent with multimodal input types
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Sample image URL for testing
    sample_image_url = "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg"

    print("=" * 70)
    print("Example 1: Message with images parameter")
    print("=" * 70)
    # Using the images parameter on Message - dependencies will be injected
    # into the text content
    agent.print_response(
        Message(
            role="user",
            content="Analyze this image based on my expertise and preferences.",
            images=[Image(url=sample_image_url)],
        ),
        stream=True,
    )

    print("\n" + "=" * 70)
    print("Example 2: OpenAI multimodal format (List of content parts)")
    print("=" * 70)
    # OpenAI-style multimodal content with type/text structure
    # Dependencies will be appended to the last text part
    multimodal_message = Message(
        role="user",
        content=[
            {"type": "text", "text": "What do you see in this image? Consider my background."},
            {"type": "image_url", "image_url": {"url": sample_image_url}},
        ],
    )
    agent.print_response(multimodal_message, stream=True)

    print("\n" + "=" * 70)
    print("Example 3: List[Message] with multimodal content (AGUI style)")
    print("=" * 70)
    # Conversation history with multimodal message - common in chat interfaces
    messages = [
        Message(role="user", content="I want to analyze some images."),
        Message(role="assistant", content="Sure! Send me the images and I'll analyze them."),
        Message(
            role="user",
            content=[
                {"type": "text", "text": "Here's a famous landmark. What can you tell me about it?"},
                {"type": "image_url", "image_url": {"url": sample_image_url}},
            ],
        ),
    ]
    agent.print_response(messages, stream=True)