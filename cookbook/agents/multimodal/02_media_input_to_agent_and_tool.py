"""
Comprehensive test for joint media access functionality.

This demonstrates:
1. Initial image upload and analysis
2. DALL-E image generation within the same run
3. Analysis of both original and generated images
4. Cross-run media persistence (accessing images from previous runs)
"""

from typing import Optional, Sequence

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.tools import Toolkit
from agno.tools.dalle import DalleTools


class ImageAnalysisTools(Toolkit):
    def __init__(self):
        tools = [
            self.analyze_images,
            self.count_images,
        ]
        super().__init__(name="image_analysis_tools", tools=tools)

    def analyze_images(self, images: Optional[Sequence[Image]] = None) -> str:
        """
        Analyze all available images and provide detailed descriptions.

        Args:
            images: Images available to the tool (automatically injected)

        Returns:
            Analysis of all available images
        """
        if not images:
            return "No images available to analyze."

        print(f"--> analyze_images received {len(images)} images")

        print("--> IMAGES", images)

        analysis_results = []
        for i, image in enumerate(images):
            if image.url:
                analysis_results.append(
                    f"Image {i + 1}: URL-based image at {image.url}"
                )
            elif image.content:
                analysis_results.append(
                    f"Image {i + 1}: Content-based image ({len(image.content)} bytes)"
                )
            else:
                analysis_results.append(f"Image {i + 1}: Unknown image format")

        return f"Found {len(images)} images:\n" + "\n".join(analysis_results)

    def count_images(self, images: Optional[Sequence[Image]] = None) -> str:
        """
        Count the number of available images.

        Args:
            images: Images available to the tool (automatically injected)

        Returns:
            Count of available images
        """
        if not images:
            return "0 images available"

        print(f"--> count_images received {len(images)} images")
        return f"{len(images)} images available"


def create_sample_image_content() -> bytes:
    """Create a simple image-like content for demonstration."""
    # This is just sample content - in reality you'd have actual image bytes
    return b"FAKE_IMAGE_CONTENT_FOR_DEMO"


def main():
    # Create an agent with both DALL-E and image analysis tools
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),  # Use GPT-4o for vision support
        tools=[ImageAnalysisTools(), DalleTools()],
        name="Joint Media Test Agent",
        description="An agent that can generate and analyze images using joint media access.",
        debug_mode=True,
        add_history_to_context=True,
        send_media_to_model=False,
        db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    )

    print("=== Joint Media Access Test ===\n")

    # Test 1: Initial image upload and analysis
    print("1. Testing initial image upload and analysis...")

    # Create sample image
    sample_image = Image(id="test_image_1", content=create_sample_image_content())

    response1 = agent.run(
        input="I've uploaded an image. Please count how many images are available and analyze them.",
        images=[sample_image],
    )

    print(f"Run 1 Response: {response1.content}")
    print(f"--> Run 1 Images in response: {len(response1.input.images or [])}")
    print("\n" + "=" * 50 + "\n")

    # Test 2: DALL-E generation + analysis in same run
    print("2. Testing DALL-E generation and immediate analysis...")

    response2 = agent.run(input="Generate an image of a cute cat.")

    print(f"Run 2 Response: {response2.content}")
    print(f"--> Run 2 Images in response: {len(response2.images or [])}")
    print("\n" + "=" * 50 + "\n")

    # Test 3: Cross-run media persistence
    print("3. Testing cross-run media persistence...")

    response3 = agent.run(
        input="Count how many images are available from all previous runs and analyze them."
    )

    print(f"Run 3 Response: {response3.content}")
    print("\n" + "=" * 50 + "\n")


if __name__ == "__main__":
    main()
