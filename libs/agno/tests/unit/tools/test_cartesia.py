"""Unit tests for Cartesia tools."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from agno.tools.cartesia import CartesiaTools

# Import the specific logger instance used by the tool
from agno.utils.log import logger as agno_logger_instance


@pytest.fixture
def mock_cartesia():
    """Create a mock Cartesia client."""
    with patch("agno.tools.cartesia.Cartesia") as mock_cartesia, patch.dict(
        "os.environ", {"CARTESIA_API_KEY": "dummy_token"}
    ), patch("agno.tools.cartesia.Path") as mock_path:
        # Setup the Path class to handle directory creation and checks
        mock_path_instance = MagicMock()
        mock_path.return_value = mock_path_instance

        # Make the path instance handle / operator calls
        mock_path_instance.__truediv__.return_value = mock_path_instance

        # Create the mock client
        mock_client = MagicMock()
        mock_cartesia.return_value = mock_client

        # Setup common mocks
        mock_client.voices = MagicMock()
        mock_client.tts = MagicMock()
        mock_client.infill = MagicMock()
        mock_client.voice_changer = MagicMock()
        mock_client.api_status = MagicMock()
        mock_client.datasets = MagicMock()

        yield mock_client


@pytest.fixture
def mock_voices():
    """Create mock voice data for testing."""
    voice1 = {
        "id": "a0e99841-438c-4a64-b679-ae501e7d6091",
        "name": "Female Voice",
        "description": "A professional female voice",
        "language": "en",
        "embedding": [0.1] * 192,  # Mock embedding with 192 dimensions
    }

    voice2 = {
        "id": "f9836c6e-a0bd-460e-9d3c-f7299fa60f94",
        "name": "Male Voice",
        "description": "A professional male voice",
        "language": "en",
        "embedding": [0.2] * 192,
    }

    return [voice1, voice2]


@pytest.fixture
def cartesia_tools(mock_cartesia):
    """Create CartesiaTools instance with mocked API."""
    # Ensure API key env var is set for initialization
    with patch.dict("os.environ", {"CARTESIA_API_KEY": "test_key"}):
        tools = CartesiaTools()
        # The mock_cartesia fixture already patches the Cartesia class,
        # so the client instance within tools should be the mock.
        # We can optionally re-assign here for clarity if needed, but the patch should suffice.
        # tools.client = mock_cartesia
        return tools


class TestCartesiaTools:
    """Test class for CartesiaTools methods."""

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        with patch("agno.tools.cartesia.Cartesia") as mock_cartesia:
            CartesiaTools(api_key="test_key")
            mock_cartesia.assert_called_once_with(api_key="test_key")

    def test_init_with_env_var(self):
        """Test initialization with environment variable."""
        with patch("agno.tools.cartesia.Cartesia") as mock_cartesia, patch.dict(
            "os.environ", {"CARTESIA_API_KEY": "env_key"}
        ), patch("os.getenv", return_value="env_key"):
            CartesiaTools()
            mock_cartesia.assert_called_once_with(api_key="env_key")

    def test_init_missing_api_key(self):
        """Test initialization with missing API key."""
        with patch("os.getenv", return_value=None), pytest.raises(ValueError):
            CartesiaTools()

    def test_feature_registration(self):
        """Test that features are correctly registered based on flags."""
        with patch("agno.tools.cartesia.Cartesia"), patch.dict("os.environ", {"CARTESIA_API_KEY": "dummy"}):
            # Test with all features disabled
            tools = CartesiaTools(
                text_to_speech_enabled=False,
                text_to_speech_streaming_enabled=False,
                list_voices_enabled=False,
                voice_get_enabled=False,
                save_audio_enabled=False,
                batch_processing_enabled=False,
                infill_enabled=False,
                api_status_enabled=False,
                datasets_enabled=False,
                voice_clone_enabled=False,
                voice_delete_enabled=False,
                voice_update_enabled=False,
                voice_localize_enabled=False,
                voice_mix_enabled=False,
                voice_create_enabled=False,
                voice_changer_enabled=False,
            )
            assert len(tools.functions) == 0

            # Test with some features enabled
            tools = CartesiaTools(
                text_to_speech_enabled=True,
                list_voices_enabled=True,
                voice_get_enabled=False,
                text_to_speech_streaming_enabled=False,
                save_audio_enabled=False,
                batch_processing_enabled=False,
                infill_enabled=False,
                api_status_enabled=False,
                datasets_enabled=False,
                voice_clone_enabled=False,
                voice_delete_enabled=False,
                voice_update_enabled=False,
                voice_localize_enabled=False,
                voice_mix_enabled=False,
                voice_create_enabled=False,
                voice_changer_enabled=False,
            )
            assert len(tools.functions) == 2
            assert "text_to_speech" in tools.functions
            assert "list_voices" in tools.functions

            # Test with new features
            tools = CartesiaTools(
                voice_get_enabled=True,
                batch_processing_enabled=True,
                text_to_speech_enabled=False,
                list_voices_enabled=False,
                text_to_speech_streaming_enabled=False,
                save_audio_enabled=False,
                infill_enabled=False,
                api_status_enabled=False,
                datasets_enabled=False,
                voice_clone_enabled=False,
                voice_delete_enabled=False,
                voice_update_enabled=False,
                voice_localize_enabled=False,
                voice_mix_enabled=False,
                voice_create_enabled=False,
                voice_changer_enabled=False,
            )
            assert len(tools.functions) == 2
            assert "get_voice" in tools.functions
            assert "batch_text_to_speech" in tools.functions

    def test_list_voices(self, cartesia_tools, mock_voices):
        """Test listing all available voices."""
        cartesia_tools.client.voices.list.return_value = mock_voices

        result = cartesia_tools.list_voices()
        result_data = json.loads(result)

        cartesia_tools.client.voices.list.assert_called_once()
        assert len(result_data) == 2
        assert "id" in result_data[0]
        assert "description" in result_data[0]

    def test_get_voice(self, cartesia_tools, mock_voices):
        """Test getting a specific voice."""
        cartesia_tools.client.voices.get.return_value = mock_voices[0]

        result = cartesia_tools.get_voice(voice_id="a0e99841-438c-4a64-b679-ae501e7d6091")
        result_data = json.loads(result)

        cartesia_tools.client.voices.get.assert_called_once_with(id="a0e99841-438c-4a64-b679-ae501e7d6091")
        assert result_data["id"] == "a0e99841-438c-4a64-b679-ae501e7d6091"
        assert result_data["name"] == "Female Voice"

    def test_clone_voice(self, mock_cartesia, mock_voices):
        """Test cloning a voice from an audio file."""
        # Need mock_cartesia for the client mock setup
        # Instantiate tools locally as flags might differ per test
        tools = CartesiaTools(voice_clone_enabled=True)
        tools.client.voices.clone.return_value = mock_voices[0]  # Use tools.client

        with patch("builtins.open", mock_open(read_data=b"audio data")) as mock_file:
            result = tools.clone_voice(
                name="Cloned Voice",
                audio_file_path="path/to/audio.wav",
                description="Test cloned voice",
                language="en",
                mode="stability",
                enhance=True,
            )

            result_data = json.loads(result)

            mock_file.assert_called_once_with("path/to/audio.wav", "rb")
            tools.client.voices.clone.assert_called_once()  # Use tools.client
            assert "name" in tools.client.voices.clone.call_args[1]  # Use tools.client
            assert "clip" in tools.client.voices.clone.call_args[1]
            assert "mode" in tools.client.voices.clone.call_args[1]
            assert "enhance" in tools.client.voices.clone.call_args[1]
            assert "description" in tools.client.voices.clone.call_args[1]
            assert "language" in tools.client.voices.clone.call_args[1]

            assert result_data["id"] == "a0e99841-438c-4a64-b679-ae501e7d6091"
            assert result_data["name"] == "Female Voice"

    def test_clone_voice_error(self, mock_cartesia):
        """Test error handling when cloning a voice."""
        tools = CartesiaTools(voice_clone_enabled=True)
        tools.client.voices.clone.side_effect = Exception("Cloning failed")  # Use tools.client

        with patch("builtins.open", mock_open(read_data=b"audio data")):
            result = tools.clone_voice(name="Cloned Voice", audio_file_path="path/to/audio.wav")

            result_data = json.loads(result)
            assert "error" in result_data
            assert "Cloning failed" in result_data["error"]

    def test_text_to_speech(self, cartesia_tools):
        """Test basic text-to-speech functionality."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"

        # Create a temporary mock for file operations
        with patch("builtins.open", mock_open()):
            result = cartesia_tools.text_to_speech(
                transcript="Hello world",
                model_id="sonic-2",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
            )

            result_data = json.loads(result)

            cartesia_tools.client.tts.bytes.assert_called_once()
            call_args = cartesia_tools.client.tts.bytes.call_args[1]

            # Verify correct parameters passed to tts.bytes
            assert call_args["model_id"] == "sonic-2"
            assert call_args["transcript"] == "Hello world"
            assert call_args["voice_id"] == "a0e99841-438c-4a64-b679-ae501e7d6091"
            assert call_args["language"] == "en"
            assert "output_format" in call_args
            assert "voice" not in call_args
            assert "voice_experimental_controls" not in call_args

            # Verify output_format has the correct structure
            output_format = call_args["output_format"]
            assert "container" in output_format
            assert "sample_rate" in output_format
            assert "encoding" in output_format
            assert output_format["encoding"] == "mp3"
            assert "bit_rate" in output_format

            assert result_data["success"] is True

    def test_text_to_speech_with_file_output(self, cartesia_tools):
        """Test TTS with file output."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"

        # Create a Path object for the test
        output_path = Path("output_dir/output.mp3")

        with patch("builtins.open", mock_open()) as mock_file:
            # Directly set the file_path that would be created
            with patch.object(cartesia_tools, "output_dir") as mock_output_dir:
                mock_output_dir.__truediv__.return_value = output_path

                result = cartesia_tools.text_to_speech(
                    transcript="Hello world",
                    model_id="sonic-2",
                    voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                    language="en",
                    output_path="output.mp3",
                )

                result_data = json.loads(result)

                # Verify the correct file path is used
                mock_file.assert_called_once_with(output_path, "wb")
                mock_file().write.assert_called_once_with(b"audio data")
                assert result_data["success"] is True
                assert "file_path" in result_data
                assert "total_bytes" in result_data
                assert result_data["total_bytes"] == len(b"audio data")

    def test_text_to_speech_with_experimental_controls(self, cartesia_tools, caplog):
        """Test TTS accepts speed/emotion controls but ignores them for tts.bytes."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"

        logger_name = agno_logger_instance.name
        original_propagate = agno_logger_instance.propagate

        try:
            # Ensure the message propagates to handlers set up by caplog
            agno_logger_instance.propagate = True

            # Capture WARNING level logs specifically from this logger
            with caplog.at_level(logging.WARNING, logger=logger_name):
                with patch("builtins.open", mock_open()):
                    result = cartesia_tools.text_to_speech(
                        transcript="Hello world",
                        model_id="sonic-2",
                        voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                        language="en",
                        voice_experimental_controls_speed="fast",
                        voice_experimental_controls_emotion=["positivity", "curiosity:low"],
                    )

            # Assertions outside the caplog context manager
            result_data = json.loads(result)
            cartesia_tools.client.tts.bytes.assert_called_once()
            call_args = cartesia_tools.client.tts.bytes.call_args[1]
            assert call_args["model_id"] == "sonic-2"
            assert call_args["transcript"] == "Hello world"
            assert call_args["voice_id"] == "a0e99841-438c-4a64-b679-ae501e7d6091"
            assert "voice" not in call_args
            assert "voice_experimental_controls" not in call_args

            assert result_data["success"] is True

            # Check records captured by caplog
            expected_log = (
                "Experimental controls (speed/emotion) were provided but might be ignored by the tts.bytes method."
            )
            found_log = False
            for record in caplog.records:
                if record.levelno == logging.WARNING and expected_log in record.getMessage():
                    found_log = True
                    break
            assert found_log, f"Expected log message '{expected_log}' not found in captured records: {caplog.records}"

        finally:
            # Restore original propagation setting
            agno_logger_instance.propagate = original_propagate

    def test_text_to_speech_missing_voice_id_finds_default(self, cartesia_tools, mock_voices):
        """Test TTS finds a default voice ID if none is provided."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"
        # Mock list_voices to return available voices
        cartesia_tools.client.voices.list.return_value = mock_voices

        with patch("builtins.open", mock_open()):
            result = cartesia_tools.text_to_speech(
                transcript="Hello world",
                model_id="sonic-2",
                voice_id=None,  # Missing voice_id
                language="en",
            )
            result_data = json.loads(result)

            # Check list_voices was called to find default
            cartesia_tools.client.voices.list.assert_called_once()
            # Check tts.bytes was called with the default voice ID
            cartesia_tools.client.tts.bytes.assert_called_once()
            call_args = cartesia_tools.client.tts.bytes.call_args[1]
            assert call_args["voice_id"] == mock_voices[0]["id"]  # Should use the first voice from list
            assert result_data["success"] is True

    def test_text_to_speech_missing_voice_id_no_default(self, cartesia_tools):
        """Test TTS fails gracefully if no voice_id provided and no default found."""
        # Mock list_voices to return an empty list
        cartesia_tools.client.voices.list.return_value = []

        # No need to mock tts.bytes as it shouldn't be called
        cartesia_tools.client.tts.bytes.side_effect = Exception("Should not be called")

        result = cartesia_tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id=None,  # Missing voice_id
            language="en",
        )

        result_data = json.loads(result)

        # Check list_voices was called
        cartesia_tools.client.voices.list.assert_called_once()
        # Check tts.bytes was NOT called
        cartesia_tools.client.tts.bytes.assert_not_called()
        # Check for the specific error message from _get_valid_voice_id
        assert "error" in result_data
        assert "Could not automatically determine a voice ID" in result_data["error"]
        assert "language: en" in result_data["error"]

    def test_mix_voices(self, cartesia_tools, mock_voices):
        """Test mixing voices functionality."""
        # Instantiate tools locally if specific flags are needed, or use fixture if default flags are ok
        # Assuming default flags are ok for mix_voices
        cartesia_tools.client.voices.mix.return_value = {
            "id": "mixed-voice-id",
            "name": "Mixed Voice",
            "description": "A mixed voice",
            "language": "en",
        }

        cartesia_tools.mix_voices(voices=[{"id": "voice_id_1", "weight": 0.25}, {"id": "voice_id_2", "weight": 0.75}])

        cartesia_tools.client.voices.mix.assert_called_once_with(
            voices=[{"id": "voice_id_1", "weight": 0.25}, {"id": "voice_id_2", "weight": 0.75}]
        )

    def test_infill_audio(self, cartesia_tools):
        """Test audio infill functionality."""
        # Assuming default flags ok for infill
        # Mock the correct method
        cartesia_tools.client.tts.infill.return_value = b"infilled audio"

        with patch("builtins.open", mock_open(read_data=b"audio data")) as mock_file:
            result = cartesia_tools.infill_audio(
                transcript="Infill text",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                model_id="sonic-2",
                language="en",
                left_audio_path="left.wav",
                right_audio_path="right.wav",
                output_format_container="mp3",  # Test uses mp3 output
                output_format_sample_rate=44100,
                # output_format_encoding="mp3", # Not needed for mp3
                # output_format_bit_rate=128000, # Uses default
                output_path="infill_output.mp3",  # Specify output to trigger write
            )

            result_data = json.loads(result)

            # Expect 3 calls: read left, read right, write output
            assert mock_file.call_count == 3
            # Check the correct method was called
            cartesia_tools.client.tts.infill.assert_called_once()
            call_args = cartesia_tools.client.tts.infill.call_args[1]  # Get kwargs

            # Check parameters passed to tts.infill
            assert call_args["model_id"] == "sonic-2"
            assert call_args["infill_transcript"] == "Infill text"
            assert "voice" in call_args  # Infill expects nested voice object
            assert call_args["voice"]["id"] == "a0e99841-438c-4a64-b679-ae501e7d6091"
            assert call_args["language"] == "en"
            assert call_args["output_format"]["container"] == "mp3"
            assert "prefix_audio" in call_args
            assert call_args["prefix_audio"] == b"audio data"
            assert "suffix_audio" in call_args
            assert call_args["suffix_audio"] == b"audio data"

            assert result_data["success"] is True
            assert "file_path" in result_data  # Check file path is in result

    def test_different_output_formats(self, cartesia_tools):
        """Test TTS with different output formats."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"

        # Test with WAV format
        cartesia_tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
            language="en",
            output_format_container="wav",
            output_format_sample_rate=48000,
            output_format_encoding="pcm_s16le",
        )

        # Verify WAV parameters were passed correctly
        assert cartesia_tools.client.tts.bytes.call_args_list[0][1]["output_format"]["container"] == "wav"
        assert cartesia_tools.client.tts.bytes.call_args_list[0][1]["output_format"]["encoding"] == "pcm_s16le"
        assert cartesia_tools.client.tts.bytes.call_args_list[0][1]["output_format"]["sample_rate"] == 48000

        # Test with RAW format
        cartesia_tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
            language="en",
            output_format_container="raw",
            output_format_sample_rate=22050,
            output_format_encoding="pcm_s16le",
        )

        # Verify RAW parameters were passed correctly
        assert cartesia_tools.client.tts.bytes.call_args_list[1][1]["output_format"]["container"] == "raw"
        assert cartesia_tools.client.tts.bytes.call_args_list[1][1]["output_format"]["encoding"] == "pcm_s16le"
        assert cartesia_tools.client.tts.bytes.call_args_list[1][1]["output_format"]["sample_rate"] == 22050

    def test_get_api_status(self, cartesia_tools):
        """Test getting API status."""
        cartesia_tools.client.api_status.get.return_value = {
            "status": "operational",
            "message": "All systems operational",
        }

        result = cartesia_tools.get_api_status()
        result_data = json.loads(result)

        cartesia_tools.client.api_status.get.assert_called_once()
        assert result_data["status"] == "operational"
        assert result_data["message"] == "All systems operational"

    def test_error_handling(self, cartesia_tools):
        """Test error handling for various scenarios."""
        # Test error in TTS
        cartesia_tools.client.tts.bytes.side_effect = Exception("TTS error")
        result = cartesia_tools.text_to_speech(
            transcript="Hello world", model_id="sonic-2", voice_id="a0e99841-438c-4a64-b679-ae501e7d6091", language="en"
        )
        result_data = json.loads(result)
        assert "error" in result_data
        assert "TTS error" in result_data["error"]

    def test_text_to_speech_with_sonic_turbo(self, cartesia_tools):
        """Test TTS with sonic-turbo model."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"

        with patch("builtins.open", mock_open()):
            result = cartesia_tools.text_to_speech(
                transcript="Hello world",
                model_id="sonic-turbo",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
            )

            result_data = json.loads(result)

            cartesia_tools.client.tts.bytes.assert_called_once()
            assert cartesia_tools.client.tts.bytes.call_args[1]["model_id"] == "sonic-turbo"
            assert "output_format" in cartesia_tools.client.tts.bytes.call_args[1]
            assert result_data["success"] is True

    def test_text_to_speech_without_saving(self, cartesia_tools):
        """Test TTS without saving to file."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"

        result = cartesia_tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
            language="en",
            output_path=None,
            save_to_file=False,
        )

        result_data = json.loads(result)

        cartesia_tools.client.tts.bytes.assert_called_once()
        assert "success" in result_data
        assert result_data["success"] is True
        assert "total_bytes" in result_data
        assert "data" in result_data
        assert result_data["data"] == "Binary audio data (not displayed)"

    def test_text_to_speech_stream(self, cartesia_tools):
        """Test streaming TTS functionality returns success message."""
        # Mock the tts.stream method (it doesn't need a return value for this test)
        cartesia_tools.client.tts.stream = MagicMock()

        result = cartesia_tools.text_to_speech_stream(
            transcript="Test transcript",
            model_id="sonic-2",
            voice_id="test-voice-id",
            language="en",
            output_format_container="mp3",
            output_format_sample_rate=44100,
            output_format_bit_rate=128000,
            # Add experimental controls to ensure they are passed correctly
            voice_experimental_controls_speed="slow",
            voice_experimental_controls_emotion=["sadness"],
        )

        # Parse the JSON result
        result_data = json.loads(result)

        # Verify the API was called correctly
        cartesia_tools.client.tts.stream.assert_called_once()
        call_args = cartesia_tools.client.tts.stream.call_args[1]  # Get kwargs

        # Check basic parameters
        assert call_args["model_id"] == "sonic-2"
        assert call_args["transcript"] == "Test transcript"
        assert call_args["voice_id"] == "test-voice-id"  # Stream uses direct voice_id
        assert call_args["language"] == "en"

        # Check output format
        assert call_args["output_format"]["container"] == "mp3"
        assert call_args["output_format"]["sample_rate"] == 44100
        assert call_args["output_format"]["bit_rate"] == 128000

        # Check experimental controls are passed correctly for stream
        assert "voice_experimental_controls" in call_args
        assert call_args["voice_experimental_controls"]["speed"] == "slow"
        assert call_args["voice_experimental_controls"]["emotion"] == ["sadness"]

        # Verify correct response structure for the stream initiation message
        assert result_data["success"] is True
        assert "message" in result_data
        assert result_data["message"] == "Streaming started."

    def test_batch_text_to_speech(self, cartesia_tools):
        """Test batch TTS functionality."""
        cartesia_tools.client.tts.bytes.return_value = b"audio data"

        with patch("builtins.open", mock_open()):
            result = cartesia_tools.batch_text_to_speech(
                transcripts=["Hello", "World", "Test"],
                model_id="sonic-2",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
            )

            result_data = json.loads(result)

            assert cartesia_tools.client.tts.bytes.call_count == 3
            assert "success" in result_data
            assert result_data["success"] is True
            assert "total" in result_data
            assert result_data["total"] == 3
            assert "success_count" in result_data
            assert "output_directory" in result_data

    def test_delete_voice(self, mock_cartesia):
        """Test deleting a voice."""
        # Enable the specific feature
        tools = CartesiaTools(voice_delete_enabled=True)
        tools.client.voices.delete.return_value = {"message": "Voice deleted successfully"}  # Use tools.client

        result = tools.delete_voice(voice_id="voice_to_delete")
        result_data = json.loads(result)

        tools.client.voices.delete.assert_called_once_with(id="voice_to_delete")  # Use tools.client
        assert "message" in result_data
        assert result_data["message"] == "Voice deleted successfully"

    def test_update_voice(self, mock_cartesia):
        """Test updating a voice."""
        # Enable the specific feature
        tools = CartesiaTools(voice_update_enabled=True)
        updated_voice_data = {
            "id": "voice_to_update",
            "name": "Updated Name",
            "description": "Updated description",
            "language": "en",
        }
        tools.client.voices.update.return_value = updated_voice_data  # Use tools.client

        result = tools.update_voice(voice_id="voice_to_update", name="Updated Name", description="Updated description")
        result_data = json.loads(result)

        tools.client.voices.update.assert_called_once_with(  # Use tools.client
            id="voice_to_update", name="Updated Name", description="Updated description"
        )
        assert result_data["id"] == "voice_to_update"
        assert result_data["name"] == "Updated Name"

    def test_localize_voice(self, mock_cartesia):
        """Test localizing a voice."""
        # Enable the specific feature
        tools = CartesiaTools(voice_localize_enabled=True)
        localized_voice_data = {
            "id": "localized_voice_id",
            "name": "Localized Voice",
            "language": "es",
            "description": "Voice localized to Spanish",
        }
        tools.client.voices.localize.return_value = localized_voice_data  # Use tools.client

        # Add missing required arguments to the call
        result = tools.localize_voice(
            voice_id="original_voice_id",
            language="es",
            name="Localized Voice",  # Added
            description="Test Localization",  # Added
            original_speaker_gender="female",  # Added
        )
        result_data = json.loads(result)

        tools.client.voices.localize.assert_called_once_with(  # Use tools.client
            voice_id="original_voice_id",  # Changed from id
            language="es",
            name="Localized Voice",
            description="Test Localization",
            original_speaker_gender="female",
        )
        assert result_data["id"] == "localized_voice_id"
        assert result_data["language"] == "es"

    def test_create_voice(self, mock_cartesia):  # Renamed test method
        """Test creating a voice from embedding."""
        # Enable the specific feature
        tools = CartesiaTools(voice_create_enabled=True)
        created_voice_data = {
            "id": "new_voice_from_embedding",
            "name": "Embedding Voice",
            "language": "en",
        }
        mock_embedding = [0.5] * 192  # Example embedding
        tools.client.voices.create.return_value = created_voice_data  # Use tools.client

        # Call the correct method name
        result = tools.create_voice(
            name="Embedding Voice", embedding=mock_embedding, description="Voice from embedding", language="en"
        )
        result_data = json.loads(result)

        # Assert the correct mock was called
        tools.client.voices.create.assert_called_once_with(  # Use tools.client
            name="Embedding Voice", embedding=mock_embedding, description="Voice from embedding", language="en"
        )
        assert result_data["id"] == "new_voice_from_embedding"
        assert result_data["name"] == "Embedding Voice"

    def test_change_voice(self, mock_cartesia):
        """Test changing a voice using voice changer."""
        # Enable the specific feature
        tools = CartesiaTools(voice_changer_enabled=True)
        tools.client.voice_changer.bytes.return_value = b"changed audio data"  # Use tools.client

        # Use file handle and pass format args directly
        mock_file_handle = mock_open(read_data=b"original audio data").return_value
        with patch("builtins.open", return_value=mock_file_handle) as mock_opener:
            result = tools.change_voice(
                voice_id="target_voice_id",
                audio_file_path="original_audio.wav",  # Still needed for open()
                output_format_container="mp3",
                output_format_sample_rate=44100,
            )
            result_data = json.loads(result)

            mock_opener.assert_called_once_with("original_audio.wav", "rb")
            tools.client.voice_changer.bytes.assert_called_once()  # Use tools.client
            call_args = tools.client.voice_changer.bytes.call_args[1]

            assert call_args["voice_id"] == "target_voice_id"
            assert call_args["clip"] == mock_file_handle  # SDK expects file handle
            # Check output format args passed directly to SDK call
            assert call_args["output_format_container"] == "mp3"
            assert call_args["output_format_sample_rate"] == 44100

            assert result_data["success"] is True
            assert "result" in result_data
            assert "changed audio data" in result_data["result"]

    def test_list_datasets(self, mock_cartesia):
        """Test listing datasets."""
        # Enable the specific feature
        tools = CartesiaTools(datasets_enabled=True)
        mock_datasets = [{"id": "ds1", "name": "Dataset 1"}, {"id": "ds2", "name": "Dataset 2"}]
        tools.client.datasets.list.return_value = mock_datasets  # Use tools.client

        result = tools.list_datasets()
        result_data = json.loads(result)

        tools.client.datasets.list.assert_called_once()  # Use tools.client
        assert len(result_data) == 2
        assert result_data[0]["id"] == "ds1"

    def test_create_dataset(self, mock_cartesia):
        """Test creating a dataset."""
        # Enable the specific feature
        tools = CartesiaTools(datasets_enabled=True)
        created_dataset = {"id": "new_ds", "name": "New Dataset", "description": "My new dataset"}
        tools.client.datasets.create.return_value = created_dataset  # Use tools.client

        # Use the file handle directly
        mock_file_handle = mock_open(read_data="col1,col2\nval1,val2").return_value
        # Patch open to return the handle
        with patch("builtins.open", return_value=mock_file_handle):
            # Call create_dataset with the file handle
            result = tools.create_dataset(
                name="New Dataset",
                dataset_file=mock_file_handle,  # Pass file handle
                description="My new dataset",
                # dataset_file_path argument is not used by create_dataset directly
            )
            result_data = json.loads(result)

            # Assert that open was called (it happens outside create_dataset in real usage)
            # mock_opener.assert_called_once_with("dataset.csv", "rb") # This assert isn't correct here as open is mocked globally
            tools.client.datasets.create.assert_called_once()  # Use tools.client
            call_args = tools.client.datasets.create.call_args[1]
            assert call_args["name"] == "New Dataset"
            assert call_args["description"] == "My new dataset"
            assert call_args["file"] == mock_file_handle  # Check file object was passed

            assert result_data["id"] == "new_ds"
            assert result_data["name"] == "New Dataset"

    def test_get_dataset(self, mock_cartesia):
        """Test getting a dataset."""
        # Enable the specific feature
        tools = CartesiaTools(datasets_enabled=True)
        dataset_data = {"id": "ds1", "name": "Dataset 1", "description": "Test"}
        tools.client.datasets.get.return_value = dataset_data  # Use tools.client

        result = tools.get_dataset(dataset_id="ds1")
        result_data = json.loads(result)

        tools.client.datasets.get.assert_called_once_with(id="ds1")  # Use tools.client
        assert result_data["id"] == "ds1"
        assert result_data["name"] == "Dataset 1"

    def test_update_dataset(self, mock_cartesia):
        """Test updating a dataset."""
        # Enable the specific feature
        tools = CartesiaTools(datasets_enabled=True)
        updated_dataset = {"id": "ds1", "name": "Updated Dataset", "description": "New Desc"}
        tools.client.datasets.update.return_value = updated_dataset  # Use tools.client

        result = tools.update_dataset(dataset_id="ds1", name="Updated Dataset", description="New Desc")
        result_data = json.loads(result)

        tools.client.datasets.update.assert_called_once_with(
            id="ds1", name="Updated Dataset", description="New Desc"
        )  # Use tools.client
        assert result_data["id"] == "ds1"
        assert result_data["name"] == "Updated Dataset"

    def test_delete_dataset(self, mock_cartesia):
        """Test deleting a dataset."""
        # Enable the specific feature
        tools = CartesiaTools(datasets_enabled=True)
        tools.client.datasets.delete.return_value = {"message": "Dataset deleted"}  # Use tools.client

        result = tools.delete_dataset(dataset_id="ds_to_delete")
        result_data = json.loads(result)

        tools.client.datasets.delete.assert_called_once_with(id="ds_to_delete")  # Use tools.client
        assert "message" in result_data
        assert result_data["message"] == "Dataset deleted"
