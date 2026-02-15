#!/usr/bin/env python3
"""
Pytest test for OpenRouter Gemini image generation response structure
"""
import json
import pytest
from agno.agent import Agent
from agno.models.openrouter import OpenRouter


@pytest.fixture
def gemini_image_agent():
    """Create a simple agent with Gemini image generation"""
    return Agent(
        name="Test Agent",
        model=OpenRouter(
            id="google/gemini-2.5-flash-image-preview",
            modalities=["image", "text"]
        ),
        markdown=False
    )


def test_openrouter_gemini_image_generation(gemini_image_agent, capsys):
    """Test OpenRouter Gemini image generation response structure"""

    print("🚀 Testing OpenRouter Gemini image generation...")
    print("=" * 60)

    # Run with a simple image generation prompt
    response = gemini_image_agent.run("Generate a simple red circle")

    # Basic assertions
    assert response is not None, "Response should not be None"
    assert hasattr(response, 'messages'), "Response should have messages attribute"
    assert len(response.messages) > 0, "Response should contain at least one message"

    print("\n📝 Response Object Type:", type(response))
    print("\n📋 Response Attributes:")
    for attr in dir(response):
        if not attr.startswith('_'):
            print(f"  - {attr}")

    # Test key response fields exist
    assert hasattr(response, 'content'), "Response should have content attribute"
    assert hasattr(response, 'images'), "Response should have images attribute"
    assert hasattr(response, 'videos'), "Response should have videos attribute"
    assert hasattr(response, 'audio'), "Response should have audio attribute"
    assert hasattr(response, 'files'), "Response should have files attribute"

    print("\n🔍 Key Response Fields:")
    print(f"  content: {response.content}")
    print(f"  images: {response.images}")
    print(f"  videos: {response.videos}")
    print(f"  audio: {response.audio}")
    print(f"  files: {response.files}")

    print("\n💬 Messages:")
    for i, msg in enumerate(response.messages):
        print(f"\nMessage {i}:")
        print(f"  Role: {msg.role}")
        print(f"  Content type: {type(msg.content)}")
        print(f"  Content: {str(msg.content)[:200] if msg.content else 'None'}")

        # Check for provider_data (raw API response)
        if hasattr(msg, 'provider_data') and msg.provider_data:
            print(f"  provider_data keys: {list(msg.provider_data.keys())}")
            print(f"  provider_data: {json.dumps(msg.provider_data, indent=2, default=str)[:1000]}")

        # Check for additional fields
        if hasattr(msg, 'images'):
            print(f"  msg.images: {msg.images}")
        if hasattr(msg, 'image_output'):
            print(f"  msg.image_output: {msg.image_output}")
        if hasattr(msg, 'video_output'):
            print(f"  msg.video_output: {msg.video_output}")
        if hasattr(msg, 'audio_output'):
            print(f"  msg.audio_output: {msg.audio_output}")

    print("\n🔬 Full Response Dict:")
    try:
        response_dict = response.model_dump() if hasattr(response, 'model_dump') else vars(response)
        response_json = json.dumps(response_dict, indent=2, default=str)[:2000]
        print(response_json)

        # Assert we can serialize the response
        assert response_json, "Response should be serializable to JSON"
    except Exception as e:
        print(f"Error converting to dict: {e}")
        print("\nRaw response:", response)
        pytest.fail(f"Failed to serialize response: {e}")

    print("\n✅ Test complete!")


def test_openrouter_gemini_response_structure(gemini_image_agent):
    """Test that the response has the expected structure without printing"""

    response = gemini_image_agent.run("Generate a simple red circle")

    # Validate response structure
    assert response is not None
    assert hasattr(response, 'messages')
    assert hasattr(response, 'content')
    assert hasattr(response, 'images')
    assert hasattr(response, 'videos')
    assert hasattr(response, 'audio')
    assert hasattr(response, 'files')

    # Validate messages
    assert len(response.messages) > 0
    for msg in response.messages:
        assert hasattr(msg, 'role')
        assert hasattr(msg, 'content')


if __name__ == "__main__":
    # Allow running directly with python for quick testing
    pytest.main([__file__, "-v", "-s"])
