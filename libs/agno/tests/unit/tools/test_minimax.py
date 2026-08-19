from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from agno.tools.minimax import MINIMAX_VIDEO_URLS, MiniMaxTools


def _response(data, method="GET"):
    request = httpx.Request(method, "https://example.com")
    return httpx.Response(200, json=data, request=request)


def test_init_uses_regional_endpoint():
    tools = MiniMaxTools(api_key="test-key", region="cn_zh")

    assert tools.base_url == MINIMAX_VIDEO_URLS["cn_zh"]
    assert "generate_video" in tools.functions
    assert "generate_video" in tools.async_functions


def test_generate_video_returns_video_artifact():
    tools = MiniMaxTools(api_key="test-key", poll_interval=0, max_wait_time=10)
    create_response = _response({"task_id": "task-123"}, method="POST")
    running_response = _response({"task": {"id": "task-123", "status": "running"}})
    succeeded_response = _response(
        {
            "task": {
                "id": "task-123",
                "status": "succeeded",
                "content": {"url": "https://cdn.example.com/video.mp4"},
            }
        }
    )

    with (
        patch("agno.tools.minimax.httpx.post", return_value=create_response) as mock_post,
        patch("agno.tools.minimax.httpx.get", side_effect=[running_response, succeeded_response]) as mock_get,
        patch("agno.tools.minimax.time.sleep") as mock_sleep,
    ):
        result = tools.generate_video("A paper boat crosses a moonlit lake")

    assert result.content == "Video generated successfully"
    assert result.videos is not None
    assert result.videos[0].url == "https://cdn.example.com/video.mp4"
    assert result.videos[0].original_prompt == "A paper boat crosses a moonlit lake"
    _, post_kwargs = mock_post.call_args
    assert post_kwargs["json"] == {
        "model": "MiniMax-H3",
        "content": [{"type": "text", "text": "A paper boat crosses a moonlit lake"}],
        "resolution": "2K",
        "duration": 5,
        "ratio": "16:9",
    }
    assert mock_get.call_count == 2
    assert mock_get.call_args.args[0] == "https://api.minimax.io/v2/query/video_generation/task-123"
    mock_sleep.assert_called_once_with(0)


def test_generate_video_surfaces_task_failure():
    tools = MiniMaxTools(api_key="test-key")
    create_response = _response({"task_id": "task-123"}, method="POST")
    failed_response = _response(
        {"task": {"id": "task-123", "status": "failed", "error": {"message": "Prompt rejected"}}}
    )

    with (
        patch("agno.tools.minimax.httpx.post", return_value=create_response),
        patch("agno.tools.minimax.httpx.get", return_value=failed_response),
    ):
        result = tools.generate_video("Rejected prompt")

    assert result.content == "Failed to generate video: Prompt rejected"
    assert result.videos is None


def test_generate_video_requires_task_id():
    tools = MiniMaxTools(api_key="test-key")

    with patch("agno.tools.minimax.httpx.post", return_value=_response({}, method="POST")):
        result = tools.generate_video("A quiet forest")

    assert result.content == "Failed to generate video: No task ID returned"


def test_generate_video_never_polls_past_max_wait_time():
    tools = MiniMaxTools(api_key="test-key", poll_interval=5, max_wait_time=10, timeout=30)
    create_response = _response({"task_id": "task-123"}, method="POST")
    running_response = _response({"task": {"id": "task-123", "status": "running"}})

    clock = {"now": 100.0}
    sleeps = []

    def fake_get(*args, **kwargs):
        # The query request itself consumes most of the remaining budget.
        clock["now"] += 8.0
        return running_response

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    with (
        patch("agno.tools.minimax.httpx.post", return_value=create_response),
        patch("agno.tools.minimax.httpx.get", side_effect=fake_get) as mock_get,
        patch("agno.tools.minimax.time.monotonic", side_effect=lambda: clock["now"]),
        patch("agno.tools.minimax.time.sleep", side_effect=fake_sleep),
    ):
        result = tools.generate_video("A very slow render")

    assert result.content == "Video generation timed out after 10 seconds"
    # The query timeout is capped by the remaining budget instead of the full request timeout.
    assert mock_get.call_args.kwargs["timeout"] == 10
    # The sleep is clamped to the two seconds left rather than the full poll interval.
    assert sleeps == [2.0]
    assert mock_get.call_count == 1
    assert clock["now"] == 110.0


async def test_agenerate_video_returns_video_artifact():
    tools = MiniMaxTools(api_key="test-key", poll_interval=0, max_wait_time=10)
    client = MagicMock()
    client.post = AsyncMock(return_value=_response({"task_id": "task-123"}, method="POST"))
    client.get = AsyncMock(
        side_effect=[
            _response({"task": {"id": "task-123", "status": "running"}}),
            _response(
                {
                    "task": {
                        "id": "task-123",
                        "status": "succeeded",
                        "content": {"url": "https://cdn.example.com/video.mp4"},
                    }
                }
            ),
        ]
    )
    client_factory = MagicMock()
    client_factory.return_value.__aenter__.return_value = client
    client_factory.return_value.__aexit__.return_value = False

    with (
        patch("agno.tools.minimax.httpx.AsyncClient", client_factory),
        patch("agno.tools.minimax.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        result = await tools.agenerate_video("A paper boat crosses a moonlit lake")

    assert result.videos is not None
    assert result.videos[0].url == "https://cdn.example.com/video.mp4"
    assert client.get.await_count == 2
    mock_sleep.assert_awaited_once_with(0)


async def test_agenerate_video_never_polls_past_max_wait_time():
    tools = MiniMaxTools(api_key="test-key", poll_interval=5, max_wait_time=10, timeout=30)
    running_response = _response({"task": {"id": "task-123", "status": "running"}})

    clock = {"now": 100.0}
    sleeps = []

    async def fake_get(*args, **kwargs):
        # The query request itself consumes most of the remaining budget.
        clock["now"] += 8.0
        return running_response

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    client = MagicMock()
    client.post = AsyncMock(return_value=_response({"task_id": "task-123"}, method="POST"))
    client.get = AsyncMock(side_effect=fake_get)
    client_factory = MagicMock()
    client_factory.return_value.__aenter__.return_value = client
    client_factory.return_value.__aexit__.return_value = False

    with (
        patch("agno.tools.minimax.httpx.AsyncClient", client_factory),
        patch("agno.tools.minimax.time.monotonic", side_effect=lambda: clock["now"]),
        patch("agno.tools.minimax.asyncio.sleep", side_effect=fake_sleep),
    ):
        result = await tools.agenerate_video("A very slow render")

    assert result.content == "Video generation timed out after 10 seconds"
    assert client.get.await_args.kwargs["timeout"] == 10
    assert sleeps == [2.0]
    assert client.get.await_count == 1
    assert clock["now"] == 110.0
