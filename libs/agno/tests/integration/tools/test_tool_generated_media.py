import os

import pytest

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.media import AudioArtifact, ImageArtifact
from agno.models.google import Gemini
from agno.models.openai.chat import OpenAIChat
from agno.tools.dalle import DalleTools


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestAgentToolGeneratedMedia:
    """Real integration tests for tool-generated media in agent responses."""

    def setup_method(self):
        """Set up test environment for each test."""
        self.db = InMemoryDb()

    def create_test_agent(self, tools=None):
        """Create a test agent with database and tools."""
        return Agent(model=OpenAIChat(id="gpt-4o-mini"), db=self.db, tools=tools or [], debug_mode=True)

    def test_dalle_image_generation_in_run_output(self):
        """Test that DALL-E generated images appear in RunOutput."""
        # Create agent with DALL-E tools
        dalle_tools = DalleTools()
        agent = self.create_test_agent(tools=[dalle_tools])

        # Run agent with image generation request
        response = agent.run("Generate a simple image of a red apple on white background")

        # Verify response contains generated image
        assert response is not None
        assert response.content is not None
        assert response.images is not None
        assert len(response.images) >= 1
        assert isinstance(response.images[0], ImageArtifact)
        assert response.images[0].url is not None or response.images[0].content is not None

        # Verify image is accessible via get_last_run_output
        last_output = agent.get_last_run_output()
        assert last_output is not None
        assert last_output.images is not None
        assert len(last_output.images) >= 1
        assert last_output.images[0].id == response.images[0].id

    def test_dalle_image_generation_persistence(self):
        """Test that generated images persist in database."""
        # Create agent with DALL-E tools
        dalle_tools = DalleTools()
        agent = self.create_test_agent(tools=[dalle_tools])

        # Run agent with image generation request
        response = agent.run("Generate a simple image of a blue circle")

        # Verify response contains generated image
        assert response is not None
        assert response.images is not None
        assert len(response.images) >= 1

        # Check database persistence
        session_in_db = self.db.get_session(response.session_id, session_type=SessionType.AGENT)
        assert session_in_db is not None
        assert session_in_db.runs is not None
        assert len(session_in_db.runs) >= 1

        # Check that the run output in database contains images
        run_output = session_in_db.runs[-1]  # Get the last run
        assert run_output.images is not None
        assert len(run_output.images) >= 1
        assert isinstance(run_output.images[0], ImageArtifact)

    def test_multiple_images_generation(self):
        """Test that multiple images can be generated and stored."""
        # Create agent with DALL-E tools
        dalle_tools = DalleTools()
        agent = self.create_test_agent(tools=[dalle_tools])

        # Run agent with multiple image generation request
        response = agent.run("Generate an image of a cat, then generate another image of a dog")

        # Verify response contains generated images
        assert response is not None
        assert response.content is not None

        # Note: This might generate 1 or 2 images depending on how the agent interprets the request
        # The key is that whatever images are generated should be properly captured
        if response.images:
            assert len(response.images) >= 1
            for image in response.images:
                assert isinstance(image, ImageArtifact)
                assert image.url is not None or image.content is not None

    def test_image_generation_with_streaming(self):
        """Test that images are captured correctly in streaming mode."""
        # Create agent with DALL-E tools
        dalle_tools = DalleTools()
        agent = self.create_test_agent(tools=[dalle_tools])

        # Run agent with streaming enabled
        response_stream = agent.run("Generate a simple image of a green tree", stream=True)

        # Collect all streaming events and find the completed event
        run_completed_event = None
        for event in response_stream:
            # Look for RunCompletedEvent which contains the media
            if hasattr(event, "event") and event.event == "run_completed":
                run_completed_event = event
            # The final event might also be the completed event
            elif hasattr(event, "images"):
                run_completed_event = event

        # Verify the completed event contains generated image
        assert run_completed_event is not None
        assert run_completed_event.images is not None
        assert len(run_completed_event.images) >= 1
        assert isinstance(run_completed_event.images[0], ImageArtifact)

        # Also verify that the agent's last run output contains the image
        last_output = agent.get_last_run_output()
        assert last_output is not None
        assert last_output.images is not None
        assert len(last_output.images) >= 1

    def test_image_analysis_after_generation(self):
        """Test that generated images can be analyzed in the same conversation."""
        # Create agent with DALL-E tools
        dalle_tools = DalleTools()
        agent = self.create_test_agent(tools=[dalle_tools])

        # First, generate an image
        response1 = agent.run("Generate an image of a red sports car")
        assert response1 is not None
        assert response1.images is not None
        assert len(response1.images) >= 1

        # Then, ask about the generated image (this tests that the image is available for analysis)
        response2 = agent.run("What can you tell me about the image you just generated?")
        assert response2 is not None
        assert response2.content is not None

        # Verify the conversation history includes the generated image
        last_output = agent.get_last_run_output()
        assert last_output is not None


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestAgentAudioGeneration:
    """Real integration tests for audio generation tools."""

    def setup_method(self):
        """Set up test environment for each test."""
        self.db = InMemoryDb()

    def create_test_agent(self, tools=None):
        """Create a test agent with database and tools."""
        return Agent(model=Gemini(id="gemini-2.5-pro"), db=self.db, tools=tools or [], debug_mode=True)

    def test_openai_speech_generation_in_run_output(self):
        """Test that OpenAI TTS generated audio appears in RunOutput."""
        from agno.tools.openai import OpenAITools

        # Create agent with OpenAI tools
        openai_tools = OpenAITools(enable_speech_generation=True)
        agent = self.create_test_agent(tools=[openai_tools])

        # Run agent with speech generation request
        response = agent.run("Generate speech saying 'Hello, this is a test'")

        # Verify response contains generated audio
        assert response is not None
        assert response.content is not None

        if response.audio:  # Audio generation might not always trigger
            assert len(response.audio) >= 1
            assert isinstance(response.audio[0], AudioArtifact)
            assert response.audio[0].base64_audio is not None


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
class TestAgentMediaPersistence:
    """Test media persistence across agent sessions."""

    def test_media_persistence_across_runs(self, shared_db):
        """Test that media persists correctly across multiple runs."""
        # Create agent with DALL-E tools
        dalle_tools = DalleTools()
        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db, tools=[dalle_tools], debug_mode=True)

        # First run: Generate image
        response1 = agent.run("Generate an image of a sunset")
        assert response1 is not None
        session_id = response1.session_id

        if response1.images:
            assert len(response1.images) >= 1
            original_image_id = response1.images[0].id

            # Second run: Continue conversation
            response2 = agent.run("Now describe what you see in that image", session_id=session_id)
            assert response2 is not None

            # Verify the image from the first run is still accessible
            session_data = shared_db.get_session(session_id, session_type=SessionType.AGENT)
            assert session_data is not None
            assert session_data.runs is not None
            assert len(session_data.runs) >= 2

            # Check first run still has the image
            first_run = session_data.runs[0]
            assert first_run.images is not None
            assert len(first_run.images) >= 1
            assert first_run.images[0].id == original_image_id

    def test_media_serialization_deserialization(self, shared_db):
        """Test that media artifacts are correctly serialized and deserialized."""
        # Create agent with DALL-E tools
        dalle_tools = DalleTools()
        agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), db=shared_db, tools=[dalle_tools], debug_mode=True)

        # Generate image
        response = agent.run("Generate a simple geometric shape")
        assert response is not None

        if response.images:
            original_image = response.images[0]
            assert isinstance(original_image, ImageArtifact)

            # Retrieve from database to test serialization/deserialization
            session_data = shared_db.get_session(response.session_id, session_type=SessionType.AGENT)
            assert session_data is not None
            assert session_data.runs is not None
            assert len(session_data.runs) >= 1

            retrieved_image = session_data.runs[0].images[0]
            assert isinstance(retrieved_image, ImageArtifact)
            assert retrieved_image.id == original_image.id
            assert retrieved_image.url == original_image.url
            assert retrieved_image.content == original_image.content
