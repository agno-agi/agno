"""Unit tests for WolframAlphaTools class."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

# Mock wolframalpha before importing our module
mock_wolframalpha = MagicMock()
sys.modules["wolframalpha"] = mock_wolframalpha


@pytest.fixture
def mock_client():
    """Create a mock Wolfram Alpha client."""
    mock_client_instance = MagicMock()
    mock_wolframalpha.Client.return_value = mock_client_instance
    return mock_client_instance


@pytest.fixture
def wolfram_tools(mock_client):
    """Create a WolframAlphaTools instance with mocked client."""
    with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-app-id"}):
        from agno.tools.wolfram_alpha import WolframAlphaTools

        tools = WolframAlphaTools()
        tools.client = mock_client
        return tools


class TestWolframAlphaToolsInitialization:
    """Tests for WolframAlphaTools initialization."""

    def test_initialization_with_env_var(self, mock_client):
        """Test initialization using environment variable."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools()
            assert tools.app_id == "test-id"

    def test_initialization_with_explicit_app_id(self, mock_client):
        """Test initialization with explicit app_id parameter."""
        with patch.dict("os.environ", {}, clear=True):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(app_id="explicit-id")
            assert tools.app_id == "explicit-id"

    def test_initialization_without_app_id_raises(self, mock_client):
        """Test that missing app_id raises ValueError."""
        with patch.dict("os.environ", {}, clear=True):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            with pytest.raises(ValueError, match="Wolfram Alpha App ID not provided"):
                WolframAlphaTools()

    def test_default_tools_registered(self, wolfram_tools):
        """Test that query and short_answer are registered by default."""
        function_names = list(wolfram_tools.functions.keys())
        assert "query" in function_names
        assert "short_answer" in function_names
        assert "conversational_query" not in function_names

    def test_all_tools_registered(self, mock_client):
        """Test that all=True registers all tools."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(all=True)
            function_names = list(tools.functions.keys())
            assert "query" in function_names
            assert "short_answer" in function_names
            assert "conversational_query" in function_names

    def test_selective_tool_enablement(self, mock_client):
        """Test enabling only specific tools."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(
                enable_query=False,
                enable_short_answer=True,
                enable_conversational=True,
            )
            function_names = list(tools.functions.keys())
            assert "query" not in function_names
            assert "short_answer" in function_names
            assert "conversational_query" in function_names


class TestWolframAlphaQuery:
    """Tests for the query method."""

    def test_successful_query(self, wolfram_tools, mock_client):
        """Test a successful full query with pods."""
        # Create mock pods
        mock_subpod = MagicMock()
        mock_subpod.plaintext = "125/3"

        mock_pod = MagicMock()
        mock_pod.title = "Result"
        mock_pod.id = "Result"
        mock_pod.subpods = [mock_subpod]

        mock_input_pod = MagicMock()
        mock_input_pod.title = "Input"
        mock_input_pod.id = "Input"
        mock_input_subpod = MagicMock()
        mock_input_subpod.plaintext = "integral_0^5 x^2 dx"
        mock_input_pod.subpods = [mock_input_subpod]

        mock_result = MagicMock()
        mock_result.pods = [mock_input_pod, mock_pod]
        mock_client.query.return_value = mock_result

        result = wolfram_tools.query("integrate x^2 from 0 to 5")
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["num_pods"] == 2
        assert parsed["pods"][1]["title"] == "Result"
        assert parsed["pods"][1]["text"] == "125/3"

    def test_query_no_results(self, wolfram_tools, mock_client):
        """Test query that returns no results."""
        mock_result = MagicMock()
        mock_result.pods = None
        mock_client.query.return_value = mock_result

        result = wolfram_tools.query("asdfghjkl nonsense")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "No results found" in parsed["error"]

    def test_query_empty_pods(self, wolfram_tools, mock_client):
        """Test query that returns pods with no text content."""
        mock_pod = MagicMock()
        mock_pod.title = "Image"
        mock_pod.id = "Image"
        mock_pod.subpods = []
        mock_pod.text = None

        mock_result = MagicMock()
        mock_result.pods = [mock_pod]
        # Make hasattr work correctly
        type(mock_pod).subpods = []
        mock_client.query.return_value = mock_result

        result = wolfram_tools.query("plot x^2")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "No text results" in parsed["error"]

    def test_query_with_max_pods_limit(self, mock_client):
        """Test that max_pods limits the number of returned pods."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(max_pods=2)
            tools.client = mock_client

            # Create 5 mock pods
            pods = []
            for i in range(5):
                mock_subpod = MagicMock()
                mock_subpod.plaintext = f"Result {i}"
                mock_pod = MagicMock()
                mock_pod.title = f"Pod {i}"
                mock_pod.id = f"Pod{i}"
                mock_pod.subpods = [mock_subpod]
                pods.append(mock_pod)

            mock_result = MagicMock()
            mock_result.pods = pods
            mock_client.query.return_value = mock_result

            result = tools.query("test query")
            parsed = json.loads(result)

            assert parsed["success"] is True
            assert parsed["num_pods"] == 2

    def test_query_with_pod_id_filter(self, mock_client):
        """Test filtering pods by ID."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(include_pod_ids=["Result"])
            tools.client = mock_client

            mock_input_subpod = MagicMock()
            mock_input_subpod.plaintext = "x^2"
            mock_input_pod = MagicMock()
            mock_input_pod.title = "Input"
            mock_input_pod.id = "Input"
            mock_input_pod.subpods = [mock_input_subpod]

            mock_result_subpod = MagicMock()
            mock_result_subpod.plaintext = "42"
            mock_result_pod = MagicMock()
            mock_result_pod.title = "Result"
            mock_result_pod.id = "Result"
            mock_result_pod.subpods = [mock_result_subpod]

            mock_response = MagicMock()
            mock_response.pods = [mock_input_pod, mock_result_pod]
            mock_client.query.return_value = mock_response

            result = tools.query("test")
            parsed = json.loads(result)

            assert parsed["success"] is True
            assert parsed["num_pods"] == 1
            assert parsed["pods"][0]["id"] == "Result"

    def test_query_exception_handling(self, wolfram_tools, mock_client):
        """Test that exceptions are caught and returned as JSON errors."""
        mock_client.query.side_effect = Exception("API timeout")

        result = wolfram_tools.query("test query")
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert "API timeout" in parsed["error"]


class TestWolframAlphaShortAnswer:
    """Tests for the short_answer method."""

    def test_successful_short_answer(self, wolfram_tools):
        """Test a successful short answer query."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"384,400 kilometers"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = wolfram_tools.short_answer("distance from Earth to Moon")
            parsed = json.loads(result)

            assert parsed["success"] is True
            assert parsed["answer"] == "384,400 kilometers"

    def test_short_answer_query_not_understood(self, wolfram_tools):
        """Test short answer with unrecognized query."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(url="", code=501, msg="", hdrs=None, fp=None),
        ):
            result = wolfram_tools.short_answer("asdfghjkl")
            parsed = json.loads(result)

            assert parsed["success"] is False
            assert "not understood" in parsed["error"]

    def test_short_answer_exception_handling(self, wolfram_tools):
        """Test that network errors are handled gracefully."""
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            result = wolfram_tools.short_answer("test")
            parsed = json.loads(result)

            assert parsed["success"] is False
            assert "Network error" in parsed["error"]


class TestWolframAlphaConversational:
    """Tests for the conversational_query method."""

    def test_successful_conversational_query(self, mock_client):
        """Test a successful conversational query."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(all=True)

            response_data = json.dumps(
                {
                    "result": "The population of France is approximately 67 million.",
                    "conversationID": "conv-123",
                }
            ).encode("utf-8")

            mock_response = MagicMock()
            mock_response.read.return_value = response_data
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_response):
                result = tools.conversational_query("population of France")
                parsed = json.loads(result)

                assert parsed["success"] is True
                assert "67 million" in parsed["answer"]
                assert parsed["conversation_id"] == "conv-123"

    def test_conversational_follow_up(self, mock_client):
        """Test a follow-up conversational query with conversation_id."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(all=True)

            response_data = json.dumps(
                {
                    "result": "Germany has approximately 83 million people.",
                    "conversationID": "conv-123",
                }
            ).encode("utf-8")

            mock_response = MagicMock()
            mock_response.read.return_value = response_data
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)

            with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
                result = tools.conversational_query("what about Germany?", conversation_id="conv-123")
                parsed = json.loads(result)

                assert parsed["success"] is True
                # Verify conversation_id was included in the URL
                call_url = mock_urlopen.call_args[0][0]
                assert "conversationid=conv-123" in call_url

    def test_conversational_exception_handling(self, mock_client):
        """Test that exceptions in conversational mode are handled."""
        with patch.dict("os.environ", {"WOLFRAM_ALPHA_APP_ID": "test-id"}):
            from agno.tools.wolfram_alpha import WolframAlphaTools

            tools = WolframAlphaTools(all=True)

            with patch("urllib.request.urlopen", side_effect=Exception("Timeout")):
                result = tools.conversational_query("test")
                parsed = json.loads(result)

                assert parsed["success"] is False
                assert "Timeout" in parsed["error"]
