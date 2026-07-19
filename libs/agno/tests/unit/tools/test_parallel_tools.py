import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.parallel import ParallelTools


@pytest.fixture
def mock_parallel_client():
    with patch("agno.tools.parallel.ParallelClient") as mock_client:
        yield mock_client


@pytest.fixture
def parallel_tools(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test-api-key"}):
        return ParallelTools(api_key="test-api-key")


# === Initialization ===


def test_init_with_api_key(mock_parallel_client):
    tools = ParallelTools(api_key="test-key")
    assert tools.api_key == "test-key"


def test_init_with_env_var(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "env-key"}):
        tools = ParallelTools()
        assert tools.api_key == "env-key"


def test_init_registers_default_tools(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools()
        names = list(tools.functions.keys())
        assert "parallel_search" in names
        assert "parallel_extract" in names
        assert len(names) == 2


def test_init_all_flag_enables_all(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools(all=True)
        names = list(tools.functions.keys())
        assert "parallel_search" in names
        assert "parallel_extract" in names
        assert "create_task" in names
        assert "create_monitor" in names
        assert len(names) == 11


def test_init_enable_task_flag(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools(enable_task=True)
        names = list(tools.functions.keys())
        assert "create_task" in names
        assert "get_task_status" in names
        assert "get_task_result" in names
        assert "create_monitor" not in names


def test_init_enable_monitor_flag(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools(enable_monitor=True)
        names = list(tools.functions.keys())
        assert "create_monitor" in names
        assert "list_monitors" in names
        assert "cancel_monitor" in names
        assert "create_task" not in names


def test_init_disable_defaults(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools(enable_search=False, enable_extract=False)
        assert len(tools.functions) == 0


def test_init_stores_constructor_params(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools(
            max_results=20,
            max_chars_per_result=5000,
            mode="turbo",
            include_domains=["example.com"],
            exclude_domains=["spam.com"],
        )
        assert tools.max_results == 20
        assert tools.max_chars_per_result == 5000
        assert tools.mode == "turbo"
        assert tools.include_domains == ["example.com"]
        assert tools.exclude_domains == ["spam.com"]


# === Search API ===


def test_search_returns_results(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(
        return_value={
            "search_id": "test-search-id",
            "results": [{"title": "Test", "url": "https://example.com", "excerpts": ["content"]}],
        }
    )
    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    result = parallel_tools.parallel_search(objective="test query")
    parsed = json.loads(result)

    assert parsed["search_id"] == "test-search-id"
    assert len(parsed["results"]) == 1


def test_search_requires_objective_or_queries(parallel_tools):
    result = parallel_tools.parallel_search()
    parsed = json.loads(result)

    assert "error" in parsed
    assert "objective or search_queries" in parsed["error"]


def test_search_auto_populates_search_queries(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "id", "results": []})
    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    parallel_tools.parallel_search(objective="AI trends")

    call_args = parallel_tools.parallel_client.search.call_args[1]
    assert call_args["search_queries"] == ["AI trends"]


def test_search_passes_explicit_queries(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "id", "results": []})
    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    parallel_tools.parallel_search(objective="AI", search_queries=["query1", "query2"])

    call_args = parallel_tools.parallel_client.search.call_args[1]
    assert call_args["search_queries"] == ["query1", "query2"]


def test_search_defaults_to_advanced_mode(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "id", "results": []})
    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    parallel_tools.parallel_search(objective="test")

    call_args = parallel_tools.parallel_client.search.call_args[1]
    assert call_args["mode"] == "advanced"


def test_search_uses_constructor_mode(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools(mode="turbo")

    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "id", "results": []})
    tools.parallel_client.search = Mock(return_value=mock_result)

    tools.parallel_search(objective="test")

    call_args = tools.parallel_client.search.call_args[1]
    assert call_args["mode"] == "turbo"


def test_search_advanced_settings_structure(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "id", "results": []})
    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    parallel_tools.parallel_search(objective="test", max_results=5, max_chars_per_result=3000)

    call_args = parallel_tools.parallel_client.search.call_args[1]
    assert call_args["advanced_settings"]["max_results"] == 5
    assert call_args["advanced_settings"]["excerpt_settings"] == {"max_chars_per_result": 3000}


def test_search_includes_domain_filters(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test"}):
        tools = ParallelTools(include_domains=["a.com"], exclude_domains=["b.com"])

    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "id", "results": []})
    tools.parallel_client.search = Mock(return_value=mock_result)

    tools.parallel_search(objective="test")

    call_args = tools.parallel_client.search.call_args[1]
    assert call_args["advanced_settings"]["source_policy"]["include_domains"] == ["a.com"]
    assert call_args["advanced_settings"]["source_policy"]["exclude_domains"] == ["b.com"]


def test_search_error_returns_json(parallel_tools):
    parallel_tools.parallel_client.search = Mock(side_effect=Exception("API Error"))

    result = parallel_tools.parallel_search(objective="test")
    parsed = json.loads(result)

    assert "error" in parsed
    assert "Search failed" in parsed["error"]


# === Extract API ===


def test_extract_returns_results(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(
        return_value={
            "extract_id": "test-id",
            "results": [{"url": "https://example.com", "title": "Test", "excerpts": ["content"]}],
            "errors": [],
        }
    )
    parallel_tools.parallel_client.extract = Mock(return_value=mock_result)

    result = parallel_tools.parallel_extract(urls=["https://example.com"])
    parsed = json.loads(result)

    assert parsed["extract_id"] == "test-id"
    assert len(parsed["results"]) == 1


def test_extract_requires_urls(parallel_tools):
    result = parallel_tools.parallel_extract(urls=[])
    parsed = json.loads(result)

    assert "error" in parsed
    assert "URL" in parsed["error"]


def test_extract_with_full_content(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"extract_id": "id", "results": [], "errors": []})
    parallel_tools.parallel_client.extract = Mock(return_value=mock_result)

    parallel_tools.parallel_extract(urls=["https://example.com"], full_content=True)

    call_args = parallel_tools.parallel_client.extract.call_args[1]
    assert call_args["advanced_settings"]["full_content"] is True


def test_extract_with_full_content_limit(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"extract_id": "id", "results": [], "errors": []})
    parallel_tools.parallel_client.extract = Mock(return_value=mock_result)

    parallel_tools.parallel_extract(urls=["https://example.com"], full_content=True, max_chars_for_full_content=5000)

    call_args = parallel_tools.parallel_client.extract.call_args[1]
    assert call_args["advanced_settings"]["full_content"] == {"max_chars_per_result": 5000}


def test_extract_with_excerpt_limit(parallel_tools):
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"extract_id": "id", "results": [], "errors": []})
    parallel_tools.parallel_client.extract = Mock(return_value=mock_result)

    parallel_tools.parallel_extract(urls=["https://example.com"], max_chars_per_excerpt=3000)

    call_args = parallel_tools.parallel_client.extract.call_args[1]
    assert call_args["advanced_settings"]["excerpt_settings"] == {"max_chars_per_result": 3000}


def test_extract_error_returns_json(parallel_tools):
    parallel_tools.parallel_client.extract = Mock(side_effect=Exception("API Error"))

    result = parallel_tools.parallel_extract(urls=["https://example.com"])
    parsed = json.loads(result)

    assert "error" in parsed
    assert "Extract failed" in parsed["error"]


# === Task API ===


@pytest.fixture
def task_tools(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test-api-key"}):
        return ParallelTools(api_key="test-api-key", enable_task=True)


def test_create_task_returns_run_id(task_tools):
    mock_run = Mock()
    mock_run.run_id = "run-123"
    mock_run.status = "queued"
    mock_run.interaction_id = "int-456"
    mock_run.processor = "base"
    mock_run.is_active = True
    task_tools.parallel_client.task_run.create = Mock(return_value=mock_run)

    result = task_tools.create_task(query="Research AI")
    parsed = json.loads(result)

    assert parsed["run_id"] == "run-123"
    assert parsed["status"] == "queued"
    assert parsed["is_active"] is True


def test_get_task_status(task_tools):
    mock_run = Mock()
    mock_run.run_id = "run-123"
    mock_run.status = "running"
    mock_run.processor = "base"
    mock_run.is_active = True
    mock_run.created_at = "2026-01-01T00:00:00Z"
    mock_run.modified_at = "2026-01-01T00:01:00Z"
    task_tools.parallel_client.task_run.retrieve = Mock(return_value=mock_run)

    result = task_tools.get_task_status(run_id="run-123")
    parsed = json.loads(result)

    assert parsed["run_id"] == "run-123"
    assert parsed["status"] == "running"


def test_get_task_result(task_tools):
    mock_result = Mock()
    mock_result.run.status = "completed"
    mock_result.run.processor = "base"
    mock_result.output.content = {"answer": "AI is transforming..."}
    mock_result.output.basis = []
    task_tools.parallel_client.task_run.result = Mock(return_value=mock_result)

    result = task_tools.get_task_result(run_id="run-123")
    parsed = json.loads(result)

    assert parsed["status"] == "completed"
    assert parsed["content"] == {"answer": "AI is transforming..."}


# === Monitor API ===


@pytest.fixture
def monitor_tools(mock_parallel_client):
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test-api-key"}):
        return ParallelTools(api_key="test-api-key", enable_monitor=True)


def test_create_monitor(monitor_tools):
    mock_monitor = Mock()
    mock_monitor.monitor_id = "mon-123"
    mock_monitor.type = "event_stream"
    mock_monitor.status = "active"
    mock_monitor.frequency = "1d"
    mock_monitor.processor = "lite"
    mock_monitor.created_at = "2026-01-01T00:00:00Z"
    mock_monitor.last_run_at = None
    monitor_tools.parallel_client.monitor.create = Mock(return_value=mock_monitor)

    result = monitor_tools.create_monitor(query="AI funding news")
    parsed = json.loads(result)

    assert parsed["monitor_id"] == "mon-123"
    assert parsed["status"] == "active"
    assert parsed["query"] == "AI funding news"


def test_list_monitors(monitor_tools):
    mock_monitor = Mock()
    mock_monitor.monitor_id = "mon-123"
    mock_monitor.type = "event_stream"
    mock_monitor.status = "active"
    mock_monitor.frequency = "1d"
    mock_monitor.processor = "lite"
    mock_monitor.created_at = "2026-01-01T00:00:00Z"
    mock_monitor.last_run_at = None
    mock_monitor.settings = Mock()
    mock_monitor.settings.query = "Test query"

    mock_response = Mock()
    mock_response.monitors = [mock_monitor]
    mock_response.next_cursor = None
    monitor_tools.parallel_client.monitor.list = Mock(return_value=mock_response)

    result = monitor_tools.list_monitors()
    parsed = json.loads(result)

    assert len(parsed["monitors"]) == 1
    assert parsed["monitors"][0]["monitor_id"] == "mon-123"
    assert parsed["has_more"] is False


def test_get_monitor(monitor_tools):
    mock_monitor = Mock()
    mock_monitor.monitor_id = "mon-123"
    mock_monitor.type = "event_stream"
    mock_monitor.status = "active"
    mock_monitor.frequency = "1d"
    mock_monitor.processor = "lite"
    mock_monitor.created_at = "2026-01-01T00:00:00Z"
    mock_monitor.last_run_at = None
    mock_monitor.settings = Mock()
    mock_monitor.settings.query = "Test query"
    monitor_tools.parallel_client.monitor.retrieve = Mock(return_value=mock_monitor)

    result = monitor_tools.get_monitor(monitor_id="mon-123")
    parsed = json.loads(result)

    assert parsed["monitor_id"] == "mon-123"
    assert parsed["query"] == "Test query"


def test_update_monitor(monitor_tools):
    mock_monitor = Mock()
    mock_monitor.monitor_id = "mon-123"
    mock_monitor.type = "event_stream"
    mock_monitor.status = "active"
    mock_monitor.frequency = "1h"
    mock_monitor.processor = "lite"
    mock_monitor.settings = Mock()
    mock_monitor.settings.query = "Updated query"
    monitor_tools.parallel_client.monitor.update = Mock(return_value=mock_monitor)

    result = monitor_tools.update_monitor(monitor_id="mon-123", frequency="1h")
    parsed = json.loads(result)

    assert parsed["frequency"] == "1h"
    assert parsed["updated"] is True


def test_cancel_monitor(monitor_tools):
    mock_monitor = Mock()
    mock_monitor.monitor_id = "mon-123"
    mock_monitor.status = "cancelled"
    monitor_tools.parallel_client.monitor.cancel = Mock(return_value=mock_monitor)

    result = monitor_tools.cancel_monitor(monitor_id="mon-123")
    parsed = json.loads(result)

    assert parsed["status"] == "cancelled"
    assert parsed["cancelled"] is True


def test_get_monitor_events(monitor_tools):
    mock_output = Mock()
    mock_output.content = {"summary": "New development"}
    mock_output.basis = []

    mock_event = Mock()
    mock_event.event_id = "evt-123"
    mock_event.event_type = "event_stream"
    mock_event.event_group_id = "grp-456"
    mock_event.event_date = "2026-01-01"
    mock_event.output = mock_output

    mock_response = Mock()
    mock_response.events = [mock_event]
    mock_response.next_cursor = None
    monitor_tools.parallel_client.monitor.events = Mock(return_value=mock_response)

    result = monitor_tools.get_monitor_events(monitor_id="mon-123")
    parsed = json.loads(result)

    assert len(parsed["events"]) == 1
    assert parsed["events"][0]["event_id"] == "evt-123"
    assert parsed["has_more"] is False


def test_get_monitor_events_error(monitor_tools):
    monitor_tools.parallel_client.monitor.events = Mock(side_effect=Exception("API Error"))

    result = monitor_tools.get_monitor_events(monitor_id="mon-123")
    parsed = json.loads(result)

    assert "error" in parsed
    assert "Get events failed" in parsed["error"]
