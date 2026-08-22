"""Unit tests for ElevenLabsVoiceRAGTools."""

import json
from unittest.mock import MagicMock, mock_open, patch

import pytest

from agno.tools.eleven_labs_voice_rag import ElevenLabsVoiceRAGTools


@pytest.fixture
def mock_sync_client():
    """Mock httpx.Client used by sync methods."""
    with patch("agno.tools.eleven_labs_voice_rag.httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_instance)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_instance


@pytest.fixture
def mock_async_client():
    """Mock httpx.AsyncClient used by async methods."""
    with patch("agno.tools.eleven_labs_voice_rag.httpx.AsyncClient") as mock_client_cls:
        mock_instance = MagicMock()

        async def aenter(_self):
            return mock_instance

        async def aexit(_self, exc_type, exc, tb):
            return False

        mock_client_cls.return_value.__aenter__ = aenter
        mock_client_cls.return_value.__aexit__ = aexit
        yield mock_instance


@pytest.fixture
def voice_rag_tools():
    """Create a tools instance with the API key set, RAG auto-index disabled to keep tests focused."""
    with patch.dict("os.environ", {"ELEVEN_LABS_API_KEY": "test_key"}):
        return ElevenLabsVoiceRAGTools(auto_compute_rag_index=False)


def _ok_response(json_payload):
    """Build a MagicMock httpx.Response stub returning json_payload."""
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=json_payload)
    return response


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_with_api_key():
    """Initialization with explicit api_key takes precedence over env."""
    tools = ElevenLabsVoiceRAGTools(api_key="explicit_key")
    assert tools.api_key == "explicit_key"
    assert tools.base_url == "https://api.elevenlabs.io/v1"
    assert tools.default_language == "en"
    assert tools.default_llm == "qwen3-30b-a3b"


def test_init_with_env_var():
    """Initialization picks up ELEVEN_LABS_API_KEY from the environment."""
    with patch.dict("os.environ", {"ELEVEN_LABS_API_KEY": "env_key"}, clear=False):
        tools = ElevenLabsVoiceRAGTools()
        assert tools.api_key == "env_key"


def test_init_with_alternate_env_var():
    """Initialization also accepts ELEVENLABS_API_KEY (no underscore)."""
    with patch.dict("os.environ", {"ELEVENLABS_API_KEY": "alt_env_key"}, clear=True):
        tools = ElevenLabsVoiceRAGTools()
        assert tools.api_key == "alt_env_key"


def test_init_missing_api_key_warns(caplog):
    """Initialization without an API key logs a warning but does not raise."""
    with patch.dict("os.environ", {}, clear=True):
        tools = ElevenLabsVoiceRAGTools()
        assert tools.api_key is None


def test_feature_registration_defaults():
    """All features enabled by default registers the full set of tools."""
    tools = ElevenLabsVoiceRAGTools(api_key="test_key")
    expected = {
        "upload_document",
        "create_from_url",
        "create_from_text",
        "create_voice_agent",
        "get_conversation_url",
        "list_voices",
        "list_documents",
    }
    assert expected.issubset(set(tools.functions.keys()))


def test_feature_registration_disabled():
    """Disabling specific feature flags removes the matching tools."""
    tools = ElevenLabsVoiceRAGTools(
        api_key="test_key",
        enable_upload_document=False,
        enable_create_from_url=False,
        enable_create_from_text=False,
        enable_create_agent=False,
        enable_get_conversation_url=False,
        enable_list_voices=False,
        enable_list_documents=False,
    )
    assert tools.functions == {} or len(tools.functions) == 0


def test_get_content_type_known_extensions():
    """File extension to MIME mapping covers the documented types."""
    tools = ElevenLabsVoiceRAGTools(api_key="test_key")
    assert tools._get_content_type("file.pdf") == "application/pdf"
    assert tools._get_content_type("file.txt") == "text/plain"
    assert tools._get_content_type("file.docx") == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert tools._get_content_type("file.csv") == "text/csv"
    assert tools._get_content_type("file.json") == "application/json"
    assert tools._get_content_type("file.md") == "text/markdown"


def test_get_content_type_unknown_extension():
    """Unknown extensions fall back to application/octet-stream."""
    tools = ElevenLabsVoiceRAGTools(api_key="test_key")
    assert tools._get_content_type("file.xyz") == "application/octet-stream"


def test_get_headers_with_and_without_content_type():
    """_get_headers always includes the API key and toggles Content-Type."""
    tools = ElevenLabsVoiceRAGTools(api_key="test_key")
    with_ct = tools._get_headers(include_content_type=True)
    without_ct = tools._get_headers(include_content_type=False)
    assert with_ct["xi-api-key"] == "test_key"
    assert with_ct["Content-Type"] == "application/json"
    assert without_ct["xi-api-key"] == "test_key"
    assert "Content-Type" not in without_ct


# ---------------------------------------------------------------------------
# create_from_text (sync)
# ---------------------------------------------------------------------------


def test_create_from_text_success(voice_rag_tools, mock_sync_client):
    """create_from_text returns the API document_id and tracks it on the instance."""
    mock_sync_client.post.return_value = _ok_response({"id": "doc_123", "name": "Sample"})

    result = voice_rag_tools.create_from_text(text="Hello world", name="Sample")
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["document_id"] == "doc_123"
    assert payload["name"] == "Sample"
    assert "doc_123" in voice_rag_tools._uploaded_documents

    call_args = mock_sync_client.post.call_args
    assert "/convai/knowledge-base/text" in call_args[0][0]
    assert call_args[1]["json"] == {"text": "Hello world", "name": "Sample"}


def test_create_from_text_api_error(voice_rag_tools, mock_sync_client):
    """create_from_text returns a JSON error when the upstream API fails."""
    mock_sync_client.post.side_effect = Exception("API down")

    result = voice_rag_tools.create_from_text(text="Hello", name="Sample")
    payload = json.loads(result)

    assert "error" in payload
    assert "API down" in payload["error"]


# ---------------------------------------------------------------------------
# create_from_url (sync)
# ---------------------------------------------------------------------------


def test_create_from_url_success(voice_rag_tools, mock_sync_client):
    """create_from_url passes the URL to the API and returns the document_id."""
    mock_sync_client.post.return_value = _ok_response({"id": "doc_url_1"})

    result = voice_rag_tools.create_from_url(url="https://docs.python.org", name="Python Docs")
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["document_id"] == "doc_url_1"
    assert payload["source_url"] == "https://docs.python.org"
    assert "doc_url_1" in voice_rag_tools._uploaded_documents

    call_args = mock_sync_client.post.call_args
    assert "/convai/knowledge-base/url" in call_args[0][0]
    assert call_args[1]["json"] == {"url": "https://docs.python.org", "name": "Python Docs"}


def test_create_from_url_error(voice_rag_tools, mock_sync_client):
    """create_from_url surfaces upstream exceptions as a JSON error string."""
    mock_sync_client.post.side_effect = Exception("network err")

    result = voice_rag_tools.create_from_url(url="https://x.example")
    payload = json.loads(result)

    assert "error" in payload


# ---------------------------------------------------------------------------
# upload_document (sync)
# ---------------------------------------------------------------------------


def test_upload_document_missing_file(voice_rag_tools):
    """upload_document returns an error when the file does not exist."""
    result = voice_rag_tools.upload_document(file_path="/nonexistent/path/file.pdf")
    payload = json.loads(result)
    assert "error" in payload
    assert "File not found" in payload["error"]


def test_upload_document_success(voice_rag_tools, mock_sync_client):
    """upload_document opens the file, posts it, and tracks the resulting document_id."""
    mock_sync_client.post.return_value = _ok_response({"id": "doc_upload_1", "name": "spec.pdf"})

    with (
        patch("agno.tools.eleven_labs_voice_rag.Path") as mock_path_cls,
        patch("builtins.open", mock_open(read_data=b"PDF-CONTENT")),
    ):
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_instance.name = "spec.pdf"
        mock_path_instance.suffix = ".pdf"
        mock_path_cls.return_value = mock_path_instance

        result = voice_rag_tools.upload_document(file_path="spec.pdf", name="My Spec")
        payload = json.loads(result)

    assert payload["success"] is True
    assert payload["document_id"] == "doc_upload_1"
    assert "doc_upload_1" in voice_rag_tools._uploaded_documents

    call_args = mock_sync_client.post.call_args
    assert "/convai/knowledge-base/file" in call_args[0][0]
    # Headers must NOT include Content-Type for multipart upload
    assert "Content-Type" not in call_args[1]["headers"]
    assert call_args[1]["data"] == {"name": "My Spec"}


# ---------------------------------------------------------------------------
# create_voice_agent (sync)
# ---------------------------------------------------------------------------


def test_create_voice_agent_success(voice_rag_tools, mock_sync_client):
    """create_voice_agent calls the create endpoint and returns rich metadata."""
    create_response = _ok_response({"agent_id": "agent_xyz"})
    signed_url_response = _ok_response({"signed_url": "wss://example/signed"})
    mock_sync_client.post.return_value = create_response
    mock_sync_client.get.return_value = signed_url_response

    result = voice_rag_tools.create_voice_agent(
        name="Test Agent",
        system_prompt="Be helpful",
        first_message="Hi",
        knowledge_base_ids=["doc_1", "doc_2"],
        voice_id="voice_xyz",
        language="hi",
        llm="gpt-4o",
    )
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["agent_id"] == "agent_xyz"
    assert payload["voice_id"] == "voice_xyz"
    assert payload["language"] == "hi"
    assert payload["llm"] == "gpt-4o"
    assert payload["knowledge_base_count"] == 2
    assert payload["conversation_url"] == "wss://example/signed"
    assert 'agent-id="agent_xyz"' in payload["embed_code"]
    assert "agent_xyz" in voice_rag_tools._created_agents

    create_call = mock_sync_client.post.call_args
    body = create_call[1]["json"]
    assert body["name"] == "Test Agent"
    prompt_cfg = body["conversation_config"]["agent"]["prompt"]
    assert prompt_cfg["llm"] == "gpt-4o"
    assert prompt_cfg["rag"]["enabled"] is True
    assert {kb["id"] for kb in prompt_cfg["knowledge_base"]} == {"doc_1", "doc_2"}
    assert body["conversation_config"]["agent"]["language"] == "hi"
    assert body["conversation_config"]["tts"]["voice_id"] == "voice_xyz"


def test_create_voice_agent_uses_session_documents(voice_rag_tools, mock_sync_client):
    """When no knowledge_base_ids are passed, previously uploaded documents are used."""
    voice_rag_tools._uploaded_documents = ["session_doc_1"]
    mock_sync_client.post.return_value = _ok_response({"agent_id": "a1"})
    mock_sync_client.get.return_value = _ok_response({"signed_url": "wss://x"})

    voice_rag_tools.create_voice_agent(name="A", system_prompt="P")

    body = mock_sync_client.post.call_args[1]["json"]
    kb_ids = [kb["id"] for kb in body["conversation_config"]["agent"]["prompt"]["knowledge_base"]]
    assert kb_ids == ["session_doc_1"]


def test_create_voice_agent_signed_url_failure_does_not_break(voice_rag_tools, mock_sync_client):
    """If the signed-url lookup fails, the create call still returns a success payload."""
    mock_sync_client.post.return_value = _ok_response({"agent_id": "agent_xyz"})
    mock_sync_client.get.side_effect = Exception("signed url fail")

    result = voice_rag_tools.create_voice_agent(name="A", system_prompt="P")
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["agent_id"] == "agent_xyz"
    assert payload["conversation_url"] is None


# ---------------------------------------------------------------------------
# get_conversation_url, list_voices, list_documents (sync)
# ---------------------------------------------------------------------------


def test_get_conversation_url_success(voice_rag_tools, mock_sync_client):
    """get_conversation_url returns the signed URL and embed code."""
    mock_sync_client.get.return_value = _ok_response({"signed_url": "wss://signed"})

    result = voice_rag_tools.get_conversation_url(agent_id="agent_1")
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["signed_url"] == "wss://signed"
    assert payload["agent_id"] == "agent_1"
    assert 'agent-id="agent_1"' in payload["embed_code"]


def test_list_voices_success(voice_rag_tools, mock_sync_client):
    """list_voices flattens the API payload into id/name/category/labels."""
    mock_sync_client.get.return_value = _ok_response(
        {
            "voices": [
                {"voice_id": "v1", "name": "Eric", "category": "premade", "labels": {"accent": "american"}},
                {"voice_id": "v2", "name": "Aria", "category": "premade", "labels": {}},
            ]
        }
    )

    result = voice_rag_tools.list_voices()
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["total"] == 2
    assert payload["voices"][0]["voice_id"] == "v1"
    assert payload["voices"][1]["name"] == "Aria"


def test_list_documents_success(voice_rag_tools, mock_sync_client):
    """list_documents returns documents and includes session uploads."""
    voice_rag_tools._uploaded_documents = ["session_a"]
    mock_sync_client.get.return_value = _ok_response(
        {
            "documents": [
                {
                    "id": "d1",
                    "name": "Doc 1",
                    "type": "file",
                    "status": "ready",
                    "created_at_unix_secs": 1700000000,
                }
            ]
        }
    )

    result = voice_rag_tools.list_documents()
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["total"] == 1
    assert payload["documents"][0]["document_id"] == "d1"
    assert payload["uploaded_in_session"] == ["session_a"]


def test_list_voices_error(voice_rag_tools, mock_sync_client):
    """list_voices returns an error payload when the API call raises."""
    mock_sync_client.get.side_effect = Exception("boom")

    result = voice_rag_tools.list_voices()
    payload = json.loads(result)
    assert "error" in payload


# ---------------------------------------------------------------------------
# Async variants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acreate_from_text_success(voice_rag_tools, mock_async_client):
    """The async variant of create_from_text mirrors the sync behavior."""

    async def fake_post(*args, **kwargs):
        return _ok_response({"id": "doc_async_1", "name": "AsyncDoc"})

    mock_async_client.post = MagicMock(side_effect=fake_post)

    result = await voice_rag_tools.acreate_from_text(text="hi", name="AsyncDoc")
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["document_id"] == "doc_async_1"
    assert "doc_async_1" in voice_rag_tools._uploaded_documents


@pytest.mark.asyncio
async def test_alist_voices_success(voice_rag_tools, mock_async_client):
    """alist_voices returns a flattened JSON payload."""

    async def fake_get(*args, **kwargs):
        return _ok_response({"voices": [{"voice_id": "v1", "name": "Eric"}]})

    mock_async_client.get = MagicMock(side_effect=fake_get)

    result = await voice_rag_tools.alist_voices()
    payload = json.loads(result)

    assert payload["success"] is True
    assert payload["total"] == 1
    assert payload["voices"][0]["voice_id"] == "v1"
