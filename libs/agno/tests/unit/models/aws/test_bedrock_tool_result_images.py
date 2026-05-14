"""Tests for Bedrock tool result image handling."""

from unittest.mock import patch

from agno.media import Image
from agno.models.aws import AwsBedrock
from agno.models.message import Message


def _make_bedrock():
    """Create an AwsBedrock instance without requiring AWS credentials."""
    return AwsBedrock(id="global.anthropic.claude-sonnet-4-6")


class TestToolResultWithImages:
    def test_tool_result_with_images(self):
        """Tool message with images should include image blocks in toolResult content."""
        bedrock = _make_bedrock()
        png_bytes = b"\x89PNG fake image bytes"

        msgs = [
            Message(role="user", content="Describe this"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "toolu_001",
                        "type": "function",
                        "function": {"name": "screenshot", "arguments": "{}"},
                    }
                ],
            ),
            Message(
                role="tool",
                tool_call_id="toolu_001",
                tool_name="screenshot",
                content="Screenshot taken",
                images=[Image(content=png_bytes, format="png")],
            ),
        ]
        formatted, _system = bedrock._format_messages(msgs)

        # Find the user message containing the tool result
        tool_user_msg = [m for m in formatted if m["role"] == "user" and any("toolResult" in c for c in m["content"])]
        assert len(tool_user_msg) == 1

        tool_result = tool_user_msg[0]["content"][0]["toolResult"]
        assert tool_result["toolUseId"] == "toolu_001"

        content = tool_result["content"]
        assert len(content) == 2
        assert content[0] == {"json": {"result": "Screenshot taken"}}
        assert content[1] == {
            "image": {
                "format": "png",
                "source": {"bytes": png_bytes},
            }
        }

    def test_tool_result_unsupported_format_skipped(self):
        """Unsupported image format should be skipped with a warning."""
        bedrock = _make_bedrock()
        bmp_bytes = b"BM fake bmp"

        msgs = [
            Message(role="user", content="Describe"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "toolu_002",
                        "type": "function",
                        "function": {"name": "capture", "arguments": "{}"},
                    }
                ],
            ),
            Message(
                role="tool",
                tool_call_id="toolu_002",
                tool_name="capture",
                content="Captured",
                images=[Image(content=bmp_bytes, format="bmp")],
            ),
        ]
        with patch("agno.models.aws.bedrock.log_warning") as mock_warn:
            formatted, _system = bedrock._format_messages(msgs)
            mock_warn.assert_called_once()
            assert "bmp" in mock_warn.call_args[0][0]

        # Should only have the json result, no image
        tool_user_msg = [m for m in formatted if m["role"] == "user" and any("toolResult" in c for c in m["content"])]
        tool_result = tool_user_msg[0]["content"][0]["toolResult"]
        assert len(tool_result["content"]) == 1

    def test_tool_result_without_images_unchanged(self):
        """Tool message without images should have normal content."""
        bedrock = _make_bedrock()

        msgs = [
            Message(role="user", content="Search"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "toolu_003",
                        "type": "function",
                        "function": {"name": "search", "arguments": "{}"},
                    }
                ],
            ),
            Message(
                role="tool",
                tool_call_id="toolu_003",
                tool_name="search",
                content="Result text",
            ),
        ]
        formatted, _system = bedrock._format_messages(msgs)

        tool_user_msg = [m for m in formatted if m["role"] == "user" and any("toolResult" in c for c in m["content"])]
        tool_result = tool_user_msg[0]["content"][0]["toolResult"]
        assert tool_result["content"] == [{"json": {"result": "Result text"}}]

    def test_tool_result_mime_type_fallback(self):
        """Image with mime_type but no format should derive format from mime_type."""
        bedrock = _make_bedrock()
        png_bytes = b"\x89PNG fake image bytes"

        msgs = [
            Message(role="user", content="Describe"),
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "toolu_004",
                        "type": "function",
                        "function": {"name": "capture", "arguments": "{}"},
                    }
                ],
            ),
            Message(
                role="tool",
                tool_call_id="toolu_004",
                tool_name="capture",
                content="Captured",
                images=[Image(content=png_bytes, mime_type="image/png")],
            ),
        ]
        formatted, _system = bedrock._format_messages(msgs)

        tool_user_msg = [m for m in formatted if m["role"] == "user" and any("toolResult" in c for c in m["content"])]
        tool_result = tool_user_msg[0]["content"][0]["toolResult"]
        assert len(tool_result["content"]) == 2
        assert tool_result["content"][1] == {
            "image": {
                "format": "png",
                "source": {"bytes": png_bytes},
            }
        }
