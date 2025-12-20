"""Integration tests for OpenAI Responses API file upload functionality."""

import tempfile
from pathlib import Path

import pytest

from agno.agent.agent import Agent
from agno.media import File
from agno.models.openai.responses import OpenAIResponses


@pytest.fixture
def sample_text_file():
    """Create a temporary text file for testing."""
    content = """# Thai Green Curry Recipe

## Ingredients:
- 2 tbsp green curry paste
- 400ml coconut milk
- 200g chicken breast, sliced
- 1 cup Thai basil leaves
- 2 tbsp fish sauce
- 1 tbsp palm sugar

## Instructions:
1. Heat curry paste in a pan
2. Add coconut milk and bring to simmer
3. Add chicken and cook for 10 minutes
4. Add fish sauce and palm sugar
5. Garnish with Thai basil

Serves 2-3 people. Preparation time: 30 minutes.
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        temp_path = Path(f.name)

    yield temp_path

    # Cleanup
    if temp_path.exists():
        temp_path.unlink()


def test_file_upload_direct_input_from_filepath(sample_text_file):
    """Test file upload using direct input (input_file) from filepath without vector stores."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    # Test file upload WITHOUT file_search tool - uses direct input_file
    response = agent.run(
        "What recipe is in this file? Just give me the recipe name.",
        files=[File(filepath=sample_text_file)],
    )

    assert response.content is not None
    assert "curry" in response.content.lower() or "thai" in response.content.lower()


def test_file_upload_direct_input_from_url():
    """Test file upload using direct input (input_file) from URL without vector stores."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    # Test file upload from URL WITHOUT file_search tool
    response = agent.run(
        "What recipes are in this PDF? List just the recipe names.",
        files=[
            File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"),
        ],
    )

    assert response.content is not None
    # Should contain some Thai recipe names
    content_lower = response.content.lower()
    assert any(
        keyword in content_lower
        for keyword in ["curry", "pad thai", "tom yum", "recipe", "thai"]
    )


def test_file_upload_direct_input_from_content():
    """Test file upload using direct input (input_file) from raw content without vector stores."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    content = b"""Shopping List:
- Apples
- Bananas
- Milk
- Bread
- Eggs
"""

    response = agent.run(
        "What items are on this shopping list? Just list them.",
        files=[File(content=content, filename="shopping_list.txt")],
    )

    assert response.content is not None
    content_lower = response.content.lower()
    # Should mention some of the items
    assert any(item in content_lower for item in ["apple", "banana", "milk", "bread", "egg"])


def test_file_upload_with_background_mode(sample_text_file):
    """Test file upload works correctly with background=True mode.

    This was the original bug - files didn't work with background mode.
    """
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    # Run in background mode
    response = agent.run(
        "What is the main dish in this recipe file?",
        files=[File(filepath=sample_text_file)],
        background=True,
    )

    # Background mode returns a response_id
    assert response.response_id is not None

    # Wait for completion and get result
    final_response = agent.get_response(response.response_id)
    assert final_response.content is not None
    assert "curry" in final_response.content.lower()


def test_multiple_files_upload():
    """Test uploading multiple files at once."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    # Create two temporary files
    file1_content = b"Document 1: The quick brown fox jumps over the lazy dog."
    file2_content = b"Document 2: Python is a high-level programming language."

    response = agent.run(
        "What are the topics of these two documents? Be brief.",
        files=[
            File(content=file1_content, filename="doc1.txt"),
            File(content=file2_content, filename="doc2.txt"),
        ],
    )

    assert response.content is not None
    content_lower = response.content.lower()
    # Should reference both documents' content
    assert any(word in content_lower for word in ["fox", "dog", "animal"])
    assert any(word in content_lower for word in ["python", "programming", "language"])


def test_file_upload_with_vector_store_still_works(sample_text_file):
    """Test that the old vector store method still works with file_search tool."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        tools=[{"type": "file_search"}],  # Uses vector store approach
        markdown=True,
        telemetry=False,
    )

    response = agent.run(
        "What recipe is in this file?",
        files=[File(filepath=sample_text_file)],
    )

    assert response.content is not None
    assert "curry" in response.content.lower()


def test_file_upload_handles_missing_file_gracefully():
    """Test that missing files are handled gracefully without crashing."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    # Try to use a non-existent file path
    with pytest.raises(ValueError, match="File not found"):
        # This should raise an error during file upload
        File(filepath="/nonexistent/path/file.txt")


def test_file_content_accessible_in_response():
    """Test that the model can actually read and understand file content."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    # Create a file with specific, verifiable content
    content = b"""The secret code is: ALPHA-BRAVO-CHARLIE-123
This is a test document to verify file content is accessible.
The answer to the test question is: 42
"""

    response = agent.run(
        "What is the secret code mentioned in this file? Give only the code.",
        files=[File(content=content, filename="secret.txt")],
    )

    assert response.content is not None
    # The model should be able to extract the secret code
    assert "ALPHA" in response.content or "alpha" in response.content.lower()
    assert "BRAVO" in response.content or "bravo" in response.content.lower()
    assert "CHARLIE" in response.content or "charlie" in response.content.lower()


def test_file_upload_with_text_and_file():
    """Test combining text prompt with file upload."""
    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        markdown=True,
        telemetry=False,
    )

    content = b"""Product Review:
Product: XYZ Headphones
Rating: 4.5/5 stars
Pros: Great sound quality, comfortable
Cons: Expensive, limited color options
"""

    response = agent.run(
        "Based on this review, would you recommend buying this product? Answer yes or no and give one reason.",
        files=[File(content=content, filename="review.txt")],
    )

    assert response.content is not None
    # Should give a yes/no answer with reasoning
    assert any(word in response.content.lower() for word in ["yes", "no", "recommend"])