"""MCP resource links must survive conversion into model-facing tool results."""

import base64
from unittest.mock import AsyncMock

import pytest
from mcp.types import (
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
    Tool,
)

from agno.agent import Agent
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.tools.function import ToolResult
from agno.tools.mcp import MCPTools
from agno.utils.mcp import get_entrypoint_for_tool


@pytest.mark.asyncio
@pytest.mark.parametrize("uri", ["https://example.com/report.pdf", "file:///reports/q3.pdf", "reports://quarterly/q3"])
async def test_resource_link_preserves_fields_without_reading_resource(uri):
    link = ResourceLink(
        name="q3-report",
        uri=uri,
        title="Quarterly report",
        description="Revenue breakdown",
        mime_type="application/pdf",
        size=1024,
        annotations={"audience": ["assistant"], "priority": 0.8},
        meta={"display_hint": "report-card"},
    )
    session = AsyncMock()
    session.call_tool.return_value = CallToolResult(content=[link])
    result = await get_entrypoint_for_tool(Tool(name="report", input_schema={}), session)()

    assert uri in result.content
    assert "Quarterly report" in result.content
    assert "Revenue breakdown" in result.content
    assert "application/pdf" in result.content
    assert "report-card" not in result.content
    assert "Unsupported content type" not in result.content
    assert result.metadata["resource_links"] == [
        {
            "type": "resource_link",
            "name": "q3-report",
            "uri": uri,
            "title": "Quarterly report",
            "description": "Revenue breakdown",
            "mimeType": "application/pdf",
            "size": 1024,
            "annotations": {"audience": ["assistant"], "priority": 0.8},
            "_meta": {"display_hint": "report-card"},
        }
    ]
    session.call_tool.assert_awaited_once_with("report", {})
    session.read_resource.assert_not_called()


@pytest.mark.asyncio
async def test_minimal_resource_link_keeps_required_fields():
    session = AsyncMock()
    session.call_tool.return_value = CallToolResult(content=[ResourceLink(name="report", uri="reports://q3")])
    result = await get_entrypoint_for_tool(Tool(name="report", input_schema={}), session)()

    assert "report" in result.content
    assert "reports://q3" in result.content
    assert result.metadata == {"resource_links": [{"type": "resource_link", "name": "report", "uri": "reports://q3"}]}


@pytest.mark.asyncio
async def test_resource_links_keep_mixed_content_order_and_existing_media():
    session = AsyncMock()
    session.call_tool.return_value = CallToolResult(
        content=[
            TextContent(type="text", text="Before"),
            ResourceLink(name="first", uri="reports://first"),
            TextContent(type="text", text="Between"),
            ResourceLink(name="second", uri="reports://second"),
            ImageContent(type="image", data=base64.b64encode(b"image-data").decode(), mime_type="image/png"),
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(uri="reports://embedded", text="Embedded report", mime_type="text/plain"),
            ),
            TextContent(type="text", text="After"),
        ]
    )
    result = await get_entrypoint_for_tool(Tool(name="report", input_schema={}), session)()

    markers = [
        "Before",
        "reports://first",
        "Between",
        "reports://second",
        "Image has been generated",
        "Embedded report",
        "After",
    ]
    positions = [result.content.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert len(result.images) == 1
    assert result.images[0].content == b"image-data"
    assert result.images[0].mime_type == "image/png"
    assert [link["uri"] for link in result.metadata["resource_links"]] == ["reports://first", "reports://second"]


@pytest.mark.asyncio
@pytest.mark.parametrize("is_error", [False, True])
async def test_resource_link_metadata_coexists_with_result_metadata(is_error):
    session = AsyncMock()
    session.call_tool.return_value = CallToolResult(
        content=[ResourceLink(name="details", uri="reports://details")],
        meta={"trace_id": "trace-1"},
        structured_content={"count": 1},
        is_error=is_error,
    )
    result = await get_entrypoint_for_tool(Tool(name="report", input_schema={}), session)()

    assert result.metadata == {
        "meta": {"trace_id": "trace-1"},
        "structured_content": {"count": 1},
        "resource_links": [{"type": "resource_link", "name": "details", "uri": "reports://details"}],
    }
    assert ToolResult.model_validate_json(result.model_dump_json()).metadata == result.metadata
    if is_error:
        assert "Error from MCP tool 'report'" in result.content


class _ToolCallingModel(Model):
    """Run the actual model/tool loop with deterministic responses and no provider."""

    def __init__(self):
        super().__init__(id="resource-link-test", name="resource-link-test", provider="test")
        self.tool_messages = []

    def invoke(self, messages, **kwargs):
        self.tool_messages = [message.model_copy(deep=True) for message in messages if message.role == "tool"]
        if self.tool_messages:
            return ModelResponse(role="assistant", content="Report found")
        return ModelResponse(
            role="assistant",
            tool_calls=[
                {"id": "call-report", "type": "function", "function": {"name": "find_report", "arguments": "{}"}}
            ],
        )

    async def ainvoke(self, messages, **kwargs):
        return self.invoke(messages, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):
        raise NotImplementedError

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.mark.asyncio
async def test_real_mcp_resource_link_reaches_next_agent_model_request():
    from fastmcp import Client, FastMCP

    server = FastMCP("resource-link-test")
    resource_reads = []

    @server.resource("reports://q3")
    def report() -> str:
        resource_reads.append("q3")
        return "Full report body"

    @server.tool(output_schema=None)
    def find_report() -> CallToolResult:
        return CallToolResult(
            content=[
                TextContent(type="text", text="Found report:"),
                ResourceLink(
                    name="quarterly-report",
                    uri="reports://q3",
                    description="Quarterly revenue breakdown",
                    meta={"display_hint": "report-card"},
                ),
            ]
        )

    model = _ToolCallingModel()
    async with Client(server) as client:
        tools = MCPTools(session=client)
        await tools.build_tools()
        agent = Agent(model=model, tools=[tools], telemetry=False)
        response = await agent.arun("Find the quarterly report")

    assert response.content == "Report found"
    assert len(model.tool_messages) == 1
    message = model.tool_messages[0]
    assert message.tool_name == "find_report"
    assert "reports://q3" in message.content
    assert "quarterly-report" in message.content
    assert "Quarterly revenue breakdown" in message.content
    assert "report-card" not in message.content
    assert "reports://q3" in response.tools[0].result
    assert resource_reads == []
