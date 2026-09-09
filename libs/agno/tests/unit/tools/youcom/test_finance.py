"""Unit tests for YouFinanceResearchTools."""

from unittest.mock import MagicMock, patch

import pytest

from agno.tools.youcom.finance import YouFinanceResearchTools

# ── Initialization ────────────────────────────────────────────────────────


def test_init_with_api_key():
    tools = YouFinanceResearchTools(api_key="test-key")
    assert tools.api_key == "test-key"


def test_init_reads_env_var():
    with patch.dict("os.environ", {"YDC_API_KEY": "env-key"}):
        tools = YouFinanceResearchTools()
        assert tools.api_key == "env-key"


def test_only_finance_research_tool_registered():
    tools = YouFinanceResearchTools(api_key="test")
    registered = {fn.name for fn in tools.functions.values()}
    assert registered == {"you_finance_research"}


def test_default_base_url():
    tools = YouFinanceResearchTools(api_key="test")
    assert tools.base_url == "https://api.you.com"


def test_base_url_strips_trailing_slash():
    tools = YouFinanceResearchTools(api_key="test", base_url="https://custom.api.com/")
    assert tools.base_url == "https://custom.api.com"


def test_default_timeout():
    tools = YouFinanceResearchTools(api_key="test")
    assert tools.timeout == 15


def test_default_research_effort():
    tools = YouFinanceResearchTools(api_key="test")
    assert tools.research_effort == "deep"


# ── Runtime validation for research_effort ────────────────────────────────


def test_init_rejects_invalid_research_effort():
    with pytest.raises(ValueError, match="research_effort must be one of"):
        YouFinanceResearchTools(api_key="test", research_effort="lite")

    with pytest.raises(ValueError, match="research_effort must be one of"):
        YouFinanceResearchTools(api_key="test", research_effort="standard")

    with pytest.raises(ValueError, match="research_effort must be one of"):
        YouFinanceResearchTools(api_key="test", research_effort="bogus")


def test_method_rejects_invalid_research_effort_override():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"output": {"content": "", "content_type": "text", "sources": []}}
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test")
        result = tools.you_finance_research("test query", research_effort="lite")
        assert "Error" in result
        assert "research_effort must be one of" in result


# ── Request payload construction ──────────────────────────────────────────


def test_basic_request_payload():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"output": {"content": "Answer", "content_type": "text", "sources": []}}
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test-key")
        tools.you_finance_research("What is NVDA revenue?")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")

        assert payload["input"] == "What is NVDA revenue?"
        assert payload["research_effort"] == "deep"


def test_research_effort_override_in_payload():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"output": {"content": "Answer", "content_type": "text", "sources": []}}
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test-key", research_effort="deep")
        tools.you_finance_research("Complex query", research_effort="exhaustive")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")

        assert payload["research_effort"] == "exhaustive"


def test_request_url_is_correct():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"output": {"content": "", "content_type": "text", "sources": []}}
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test")
        tools.you_finance_research("test")

        call_args = mock_post.call_args
        url = call_args.args[0] if call_args.args else call_args[0][0]
        assert url == "https://api.you.com/v1/finance_research"


def test_headers_contain_api_key():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"output": {"content": "", "content_type": "text", "sources": []}}
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="my-secret-key")
        tools.you_finance_research("test")

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["X-API-Key"] == "my-secret-key"


def test_input_length_validation():
    tools = YouFinanceResearchTools(api_key="test")
    long_input = "A" * 40001
    result = tools.you_finance_research(long_input)
    assert "Error" in result
    assert "maximum length" in result


# ── Response parsing — JSON format ────────────────────────────────────────


def test_json_format_with_sources():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "output": {
                "content": "NVIDIA revenue was $130.5B",
                "content_type": "text",
                "sources": [
                    {
                        "url": "https://example.com/report",
                        "title": "NVIDIA Annual Report",
                        "snippets": ["Revenue grew 114%"],
                    }
                ],
            }
        }
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test", format="json")
        result = tools.you_finance_research("NVDA revenue?")

        import json

        parsed = json.loads(result)
        assert parsed["content"] == "NVIDIA revenue was $130.5B"
        assert parsed["content_type"] == "text"
        assert len(parsed["sources"]) == 1
        assert parsed["sources"][0]["title"] == "NVIDIA Annual Report"


def test_json_format_empty_sources():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "output": {
                "content": "No data found.",
                "content_type": "text",
                "sources": [],
            }
        }
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test", format="json")
        result = tools.you_finance_research("Unknown company?")

        import json

        parsed = json.loads(result)
        assert parsed["content"] == "No data found."
        assert "sources" not in parsed


# ── Response parsing — Markdown format ────────────────────────────────────


def test_markdown_format_with_sources():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "output": {
                "content": "Apple FCF was $99.6B in FY2023.",
                "content_type": "text",
                "sources": [
                    {"url": "https://apple.com/10k", "title": "Apple 10-K"},
                    {"url": "https://sec.gov/filing", "title": "SEC Filing"},
                ],
            }
        }
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test", format="markdown")
        result = tools.you_finance_research("Apple FCF?")

        assert "# Finance Research:" in result
        assert "Apple FCF was $99.6B in FY2023." in result
        assert "## Sources" in result
        assert "1. [Apple 10-K](https://apple.com/10k)" in result
        assert "2. [SEC Filing](https://sec.gov/filing)" in result


# ── Truncation ────────────────────────────────────────────────────────────


def test_snippet_truncation():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        long_snippet = "B" * 2000
        mock_response.json.return_value = {
            "output": {
                "content": "Answer",
                "content_type": "text",
                "sources": [{"url": "https://example.com", "snippets": [long_snippet]}],
            }
        }
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test", text_length_limit=500)
        result = tools.you_finance_research("test")

        import json

        parsed = json.loads(result)
        assert len(parsed["sources"][0]["snippets"][0]) == 500


# ── Error handling ────────────────────────────────────────────────────────


def test_http_error_returns_message():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")
        mock_post.return_value = mock_response

        tools = YouFinanceResearchTools(api_key="test")
        result = tools.you_finance_research("test")

        assert "Error" in result
        assert "401 Unauthorized" in result
