"""Unit tests for Cartesia tools."""

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from agno.tools.cartesia import CartesiaTools


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
            )
            assert len(tools.functions) == 2
            assert "get_voice" in tools.functions
            assert "batch_text_to_speech" in tools.functions

    def test_list_voices(self, mock_cartesia, mock_voices):
        """Test listing all available voices."""
        tools = CartesiaTools()
        mock_cartesia.voices.list.return_value = mock_voices

        result = tools.list_voices()
        result_data = json.loads(result)

        mock_cartesia.voices.list.assert_called_once()
        assert len(result_data) == 2
        assert "id" in result_data[0]
        assert "description" in result_data[0]

    def test_get_voice(self, mock_cartesia, mock_voices):
        """Test getting a specific voice."""
        tools = CartesiaTools()
        mock_cartesia.voices.get.return_value = mock_voices[0]

        result = tools.get_voice(voice_id="a0e99841-438c-4a64-b679-ae501e7d6091")
        result_data = json.loads(result)

        mock_cartesia.voices.get.assert_called_once_with(id="a0e99841-438c-4a64-b679-ae501e7d6091")
        assert result_data["id"] == "a0e99841-438c-4a64-b679-ae501e7d6091"
        assert result_data["name"] == "Female Voice"

    def test_clone_voice(self, mock_cartesia, mock_voices):
        """Test cloning a voice from an audio file."""
        tools = CartesiaTools()
        mock_cartesia.voices.clone.return_value = mock_voices[0]

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
            mock_cartesia.voices.clone.assert_called_once()
            assert "name" in mock_cartesia.voices.clone.call_args[1]
            assert "clip" in mock_cartesia.voices.clone.call_args[1]
            assert "mode" in mock_cartesia.voices.clone.call_args[1]
            assert "enhance" in mock_cartesia.voices.clone.call_args[1]
            assert "description" in mock_cartesia.voices.clone.call_args[1]
            assert "language" in mock_cartesia.voices.clone.call_args[1]

            assert result_data["id"] == "a0e99841-438c-4a64-b679-ae501e7d6091"
            assert result_data["name"] == "Female Voice"

    def test_clone_voice_error(self, mock_cartesia):
        """Test error handling when cloning a voice."""
        tools = CartesiaTools()
        mock_cartesia.voices.clone.side_effect = Exception("Cloning failed")

        with patch("builtins.open", mock_open(read_data=b"audio data")):
            result = tools.clone_voice(name="Cloned Voice", audio_file_path="path/to/audio.wav")

            result_data = json.loads(result)
            assert "error" in result_data
            assert "Cloning failed" in result_data["error"]

    def test_text_to_speech(self, mock_cartesia):
        """Test basic text-to-speech functionality."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"audio data"

        # Create a temporary mock for file operations
        with patch("builtins.open", mock_open()):
            result = tools.text_to_speech(
                transcript="Hello world",
                model_id="sonic-2",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
            )

            result_data = json.loads(result)

            mock_cartesia.tts.bytes.assert_called_once()
            assert "model_id" in mock_cartesia.tts.bytes.call_args[1]
            assert "transcript" in mock_cartesia.tts.bytes.call_args[1]
            assert "voice_id" in mock_cartesia.tts.bytes.call_args[1]
            assert "language" in mock_cartesia.tts.bytes.call_args[1]
            assert "output_format" in mock_cartesia.tts.bytes.call_args[1]

            # Verify output_format has the correct structure
            output_format = mock_cartesia.tts.bytes.call_args[1]["output_format"]
            assert "container" in output_format
            assert "sample_rate" in output_format
            assert "encoding" in output_format
            assert output_format["encoding"] == "mp3"
            assert "bit_rate" in output_format

            assert result_data["success"] is True

    def test_text_to_speech_with_file_output(self, mock_cartesia):
        """Test TTS with file output."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"audio data"

        # Create a Path object for the test
        output_path = Path("output_dir/output.mp3")

        with patch("builtins.open", mock_open()) as mock_file:
            # Directly set the file_path that would be created
            with patch.object(tools, "output_dir") as mock_output_dir:
                mock_output_dir.__truediv__.return_value = output_path

                result = tools.text_to_speech(
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

    def test_text_to_speech_with_experimental_controls(self, mock_cartesia):
        """Test TTS with speed and emotion controls."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"audio data"

        # In the current implementation, experimental controls are passed through kwargs
        with patch("builtins.open", mock_open()):
            result = tools.text_to_speech(
                transcript="Hello world",
                model_id="sonic-2",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
                voice_experimental_controls_speed="fast",
                voice_experimental_controls_emotion=["positivity", "curiosity:low"],
            )

            result_data = json.loads(result)

            # Check that parameters were passed in call
            assert "model_id" in mock_cartesia.tts.bytes.call_args[1]
            assert "transcript" in mock_cartesia.tts.bytes.call_args[1]
            assert "voice_id" in mock_cartesia.tts.bytes.call_args[1]

            # These should be passed through if SDK supports them
            assert result_data["success"] is True

    def test_text_to_speech_missing_voice_id(self, mock_cartesia):
        """Test TTS with missing voice_id parameter."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.side_effect = Exception("Either voice_id or voice_embedding must be specified.")

        result = tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id=None,  # Missing voice_id
            language="en",
        )

        result_data = json.loads(result)

        mock_cartesia.tts.bytes.assert_called_once()
        assert "error" in result_data
        assert "voice_id" in result_data["error"]

    def test_mix_voices(self, mock_cartesia, mock_voices):
        """Test mixing voices functionality."""
        tools = CartesiaTools()
        mock_cartesia.voices.mix.return_value = {
            "id": "mixed-voice-id",
            "name": "Mixed Voice",
            "description": "A mixed voice",
            "language": "en",
        }

        result = tools.mix_voices(voices=[{"id": "voice_id_1", "weight": 0.25}, {"id": "voice_id_2", "weight": 0.75}])

        result_data = json.loads(result)

        mock_cartesia.voices.mix.assert_called_once_with(
            voices=[{"id": "voice_id_1", "weight": 0.25}, {"id": "voice_id_2", "weight": 0.75}]
        )

        assert result_data["id"] == "mixed-voice-id"
        assert result_data["name"] == "Mixed Voice"

    def test_infill_audio(self, mock_cartesia):
        """Test audio infill functionality."""
        tools = CartesiaTools()
        mock_cartesia.infill.bytes.return_value = b"infilled audio"

        with patch("builtins.open", mock_open(read_data=b"audio data")) as mock_file:
            result = tools.infill_audio(
                transcript="Infill text",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                model_id="sonic-2",
                language="en",
                left_audio_path="left.wav",
                right_audio_path="right.wav",
                output_format_container="mp3",
                output_format_sample_rate=44100,
                output_format_encoding="mp3",
                output_format_bit_rate=128000,
            )

            result_data = json.loads(result)

            assert mock_file.call_count == 2
            mock_cartesia.infill.bytes.assert_called_once()

            assert "transcript" in mock_cartesia.infill.bytes.call_args[1]
            assert "voice_id" in mock_cartesia.infill.bytes.call_args[1]
            assert "model_id" in mock_cartesia.infill.bytes.call_args[1]
            assert "language" in mock_cartesia.infill.bytes.call_args[1]
            assert "left_audio" in mock_cartesia.infill.bytes.call_args[1]
            assert "right_audio" in mock_cartesia.infill.bytes.call_args[1]
            assert "output_format_container" in mock_cartesia.infill.bytes.call_args[1]
            assert "output_format_sample_rate" in mock_cartesia.infill.bytes.call_args[1]
            assert "output_format_encoding" in mock_cartesia.infill.bytes.call_args[1]
            assert "output_format_bit_rate" in mock_cartesia.infill.bytes.call_args[1]

            assert result_data["success"] is True

    def test_different_output_formats(self, mock_cartesia):
        """Test TTS with different output formats."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"audio data"

        # Test with WAV format
        tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
            language="en",
            output_format_container="wav",
            output_format_sample_rate=48000,
            output_format_encoding="pcm_s16le",
        )

        # Verify WAV parameters were passed correctly
        assert mock_cartesia.tts.bytes.call_args_list[0][1]["output_format"]["container"] == "wav"
        assert mock_cartesia.tts.bytes.call_args_list[0][1]["output_format"]["encoding"] == "pcm_s16le"
        assert mock_cartesia.tts.bytes.call_args_list[0][1]["output_format"]["sample_rate"] == 48000

        # Test with RAW format
        tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
            language="en",
            output_format_container="raw",
            output_format_sample_rate=22050,
            output_format_encoding="pcm_s16le",
        )

        # Verify RAW parameters were passed correctly
        assert mock_cartesia.tts.bytes.call_args_list[1][1]["output_format"]["container"] == "raw"
        assert mock_cartesia.tts.bytes.call_args_list[1][1]["output_format"]["encoding"] == "pcm_s16le"
        assert mock_cartesia.tts.bytes.call_args_list[1][1]["output_format"]["sample_rate"] == 22050

    def test_get_api_status(self, mock_cartesia):
        """Test getting API status."""
        tools = CartesiaTools()
        mock_cartesia.api_status.get.return_value = {"status": "operational", "message": "All systems operational"}

        result = tools.get_api_status()
        result_data = json.loads(result)

        mock_cartesia.api_status.get.assert_called_once()
        assert result_data["status"] == "operational"
        assert result_data["message"] == "All systems operational"

    def test_error_handling(self, mock_cartesia):
        """Test error handling for various scenarios."""
        tools = CartesiaTools()

        # Test error in TTS
        mock_cartesia.tts.bytes.side_effect = Exception("TTS error")
        result = tools.text_to_speech(
            transcript="Hello world", model_id="sonic-2", voice_id="a0e99841-438c-4a64-b679-ae501e7d6091", language="en"
        )
        result_data = json.loads(result)
        assert "error" in result_data
        assert "TTS error" in result_data["error"]

    def test_text_to_speech_with_sonic_turbo(self, mock_cartesia):
        """Test TTS with sonic-turbo model."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"audio data"

        with patch("builtins.open", mock_open()):
            result = tools.text_to_speech(
                transcript="Hello world",
                model_id="sonic-turbo",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
            )

            result_data = json.loads(result)

            mock_cartesia.tts.bytes.assert_called_once()
            assert mock_cartesia.tts.bytes.call_args[1]["model_id"] == "sonic-turbo"
            assert "output_format" in mock_cartesia.tts.bytes.call_args[1]
            assert result_data["success"] is True

    def test_text_to_speech_without_saving(self, mock_cartesia):
        """Test TTS without saving to file."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"audio data"

        result = tools.text_to_speech(
            transcript="Hello world",
            model_id="sonic-2",
            voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
            language="en",
            output_path=None,
            save_to_file=False,
        )

        result_data = json.loads(result)

        mock_cartesia.tts.bytes.assert_called_once()
        assert "success" in result_data
        assert result_data["success"] is True
        assert "total_bytes" in result_data
        assert "data" in result_data
        assert result_data["data"] == "Binary audio data (not displayed)"

    def test_text_to_speech_stream(self, mock_cartesia):
        """Test streaming TTS functionality."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"streamed audio data"

        with patch("builtins.open", mock_open()):
            result = tools.text_to_speech_stream(
                transcript="Hello world",
                model_id="sonic-2",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
            )

            result_data = json.loads(result)

            mock_cartesia.tts.bytes.assert_called_once()
            assert "model_id" in mock_cartesia.tts.bytes.call_args[1]
            assert "transcript" in mock_cartesia.tts.bytes.call_args[1]
            assert "voice_id" in mock_cartesia.tts.bytes.call_args[1]
            assert "language" in mock_cartesia.tts.bytes.call_args[1]
            assert "output_format" in mock_cartesia.tts.bytes.call_args[1]

            # Verify output_format has the encoding field
            output_format = mock_cartesia.tts.bytes.call_args[1]["output_format"]
            assert "encoding" in output_format

            assert result_data["success"] is True
            assert "streaming" in result_data
            assert result_data["streaming"] is False  # Using bytes method, not true streaming
            assert "total_bytes" in result_data

    def test_batch_text_to_speech(self, mock_cartesia):
        """Test batch TTS functionality."""
        tools = CartesiaTools()
        mock_cartesia.tts.bytes.return_value = b"audio data"

        with patch("builtins.open", mock_open()):
            result = tools.batch_text_to_speech(
                transcripts=["Hello", "World", "Test"],
                model_id="sonic-2",
                voice_id="a0e99841-438c-4a64-b679-ae501e7d6091",
                language="en",
            )

            result_data = json.loads(result)

            assert mock_cartesia.tts.bytes.call_count == 3
            assert "success" in result_data
            assert result_data["success"] is True
            assert "total" in result_data
            assert result_data["total"] == 3
            assert "success_count" in result_data
            assert "output_directory" in result_data
