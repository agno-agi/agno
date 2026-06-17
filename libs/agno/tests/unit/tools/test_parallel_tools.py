"""Unit tests for ParallelTools"""

import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.parallel import ParallelTools


@pytest.fixture
def mock_parallel_client():
    """Mock Parallel client."""
    with patch("agno.tools.parallel.ParallelClient") as mock_client:
        yield mock_client


@pytest.fixture
def parallel_tools(mock_parallel_client):
    """Create ParallelTools instance with mocked client."""
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test-api-key"}):
        return ParallelTools(api_key="test-api-key")


def test_parallel_search(parallel_tools):
    """Test parallel_search function."""
    # Setup mock data
    mock_result = Mock()
    mock_result.model_dump = Mock(
        return_value={
            "search_id": "test-search-id",
            "results": [
                {
                    "title": "Test Title",
                    "url": "https://example.com",
                    "publish_date": "2025-01-01",
                    "excerpts": ["Test excerpt content"],
                }
            ],
        }
    )

    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    # Execute test
    result = parallel_tools.parallel_search(objective="Test objective")
    result_dict = json.loads(result)

    # Verify the result
    assert result_dict["search_id"] == "test-search-id"
    assert len(result_dict["results"]) == 1
    assert result_dict["results"][0]["title"] == "Test Title"


def test_parallel_search_with_queries(parallel_tools):
    """Test parallel_search with search queries."""
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "test-id", "results": []})

    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    parallel_tools.parallel_search(objective="Test", search_queries=["query1", "query2"])

    # Verify search_queries was passed
    call_args = parallel_tools.parallel_client.search.call_args
    assert call_args[1]["search_queries"] == ["query1", "query2"]


def test_parallel_search_auto_populates_search_queries(parallel_tools):
    """Test that search_queries is auto-populated from objective when not provided."""
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"search_id": "test-id", "results": []})

    parallel_tools.parallel_client.search = Mock(return_value=mock_result)

    parallel_tools.parallel_search(objective="Find AI trends")

    # GA API requires search_queries — should be auto-populated from objective
    call_args = parallel_tools.parallel_client.search.call_args
    assert call_args[1]["search_queries"] == ["Find AI trends"]
    assert call_args[1]["mode"] == "advanced"


def test_parallel_search_error(parallel_tools):
    """Test parallel_search error handling."""
    parallel_tools.parallel_client.search = Mock(side_effect=Exception("API Error"))

    result = parallel_tools.parallel_search(objective="Test")
    result_dict = json.loads(result)

    assert "error" in result_dict
    assert "Search failed" in result_dict["error"]


def test_parallel_extract(parallel_tools):
    """Test parallel_extract function."""
    # Setup mock data
    mock_result = Mock()
    mock_result.model_dump = Mock(
        return_value={
            "extract_id": "test-extract-id",
            "results": [
                {
                    "url": "https://example.com",
                    "title": "Test Title",
                    "excerpts": ["Excerpt 1", "Excerpt 2"],
                }
            ],
            "errors": [],
        }
    )

    parallel_tools.parallel_client.extract = Mock(return_value=mock_result)

    # Execute test
    result = parallel_tools.parallel_extract(urls=["https://example.com"])
    result_dict = json.loads(result)

    # Verify the result
    assert result_dict["extract_id"] == "test-extract-id"
    assert len(result_dict["results"]) == 1
    assert result_dict["results"][0]["url"] == "https://example.com"


def test_parallel_extract_with_full_content(parallel_tools):
    """Test parallel_extract with full_content."""
    mock_result = Mock()
    mock_result.model_dump = Mock(return_value={"extract_id": "test-id", "results": [], "errors": []})

    parallel_tools.parallel_client.extract = Mock(return_value=mock_result)

    parallel_tools.parallel_extract(urls=["https://example.com"], excerpts=False, full_content=True)

    # Verify parameters
    call_args = parallel_tools.parallel_client.extract.call_args
    assert call_args[1]["excerpts"] is False
    assert call_args[1]["full_content"] is True


def test_parallel_extract_error(parallel_tools):
    """Test parallel_extract error handling."""
    parallel_tools.parallel_client.extract = Mock(side_effect=Exception("API Error"))

    result = parallel_tools.parallel_extract(urls=["https://example.com"])
    result_dict = json.loads(result)

    assert "error" in result_dict
    assert "Extract failed" in result_dict["error"]


# ---------------------------------------------------------------------------
# Task API Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def task_tools(mock_parallel_client):
    """Create ParallelTools with Task API enabled."""
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test-api-key"}):
        return ParallelTools(api_key="test-api-key", enable_task=True)


def test_create_task(task_tools):
    """Test create_task function."""
    mock_task_run = Mock()
    mock_task_run.run_id = "test-run-id"
    mock_task_run.status = "running"
    mock_task_run.interaction_id = "test-interaction-id"
    mock_task_run.processor = "base"
    mock_task_run.is_active = True

    task_tools.parallel_client.task_run.create = Mock(return_value=mock_task_run)

    result = task_tools.create_task(query="Research AI trends")
    result_dict = json.loads(result)

    assert result_dict["run_id"] == "test-run-id"
    assert result_dict["status"] == "running"
    assert result_dict["is_active"] is True


def test_get_task_result(task_tools):
    """Test get_task_result function."""
    mock_task_result = Mock()
    mock_task_result.run.status = "completed"
    mock_task_result.run.processor = "base"
    mock_task_result.output.content = {"data": "result"}
    mock_task_result.output.basis = []

    task_tools.parallel_client.task_run.result = Mock(return_value=mock_task_result)

    result = task_tools.get_task_result(run_id="test-run-id")
    result_dict = json.loads(result)

    assert result_dict["status"] == "completed"
    assert result_dict["content"] == {"data": "result"}


def test_get_task_status(task_tools):
    """Test get_task_status function."""
    mock_task_run = Mock()
    mock_task_run.run_id = "test-run-id"
    mock_task_run.status = "running"
    mock_task_run.processor = "base"
    mock_task_run.is_active = True
    mock_task_run.created_at = "2026-01-01T00:00:00Z"
    mock_task_run.modified_at = "2026-01-01T00:01:00Z"

    task_tools.parallel_client.task_run.retrieve = Mock(return_value=mock_task_run)

    result = task_tools.get_task_status(run_id="test-run-id")
    result_dict = json.loads(result)

    assert result_dict["run_id"] == "test-run-id"
    assert result_dict["status"] == "running"
    assert result_dict["is_active"] is True


# ---------------------------------------------------------------------------
# Monitor API Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def monitor_tools(mock_parallel_client):
    """Create ParallelTools with Monitor API enabled."""
    with patch.dict("os.environ", {"PARALLEL_API_KEY": "test-api-key"}):
        return ParallelTools(api_key="test-api-key", enable_monitor=True)


def test_create_monitor(monitor_tools):
    """Test create_monitor function."""
    mock_monitor = Mock()
    mock_monitor.monitor_id = "test-monitor-id"
    mock_monitor.type = "event_stream"
    mock_monitor.status = "active"
    mock_monitor.frequency = "1d"
    mock_monitor.processor = "lite"
    mock_monitor.created_at = "2026-01-01T00:00:00Z"
    mock_monitor.last_run_at = None

    monitor_tools.parallel_client.monitor.create = Mock(return_value=mock_monitor)

    result = monitor_tools.create_monitor(query="AI funding news")
    result_dict = json.loads(result)

    assert result_dict["monitor_id"] == "test-monitor-id"
    assert result_dict["status"] == "active"
    assert result_dict["query"] == "AI funding news"


def test_list_monitors(monitor_tools):
    """Test list_monitors function."""
    mock_monitor = Mock()
    mock_monitor.monitor_id = "test-monitor-id"
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
    result_dict = json.loads(result)

    assert len(result_dict["monitors"]) == 1
    assert result_dict["monitors"][0]["monitor_id"] == "test-monitor-id"
    assert result_dict["has_more"] is False


def test_get_monitor(monitor_tools):
    """Test get_monitor function."""
    mock_monitor = Mock()
    mock_monitor.monitor_id = "test-monitor-id"
    mock_monitor.type = "event_stream"
    mock_monitor.status = "active"
    mock_monitor.frequency = "1d"
    mock_monitor.processor = "lite"
    mock_monitor.created_at = "2026-01-01T00:00:00Z"
    mock_monitor.last_run_at = None
    mock_monitor.settings = Mock()
    mock_monitor.settings.query = "Test query"

    monitor_tools.parallel_client.monitor.retrieve = Mock(return_value=mock_monitor)

    result = monitor_tools.get_monitor(monitor_id="test-monitor-id")
    result_dict = json.loads(result)

    assert result_dict["monitor_id"] == "test-monitor-id"
    assert result_dict["status"] == "active"
    assert result_dict["query"] == "Test query"


def test_update_monitor(monitor_tools):
    """Test update_monitor function."""
    mock_monitor = Mock()
    mock_monitor.monitor_id = "test-monitor-id"
    mock_monitor.type = "event_stream"
    mock_monitor.status = "active"
    mock_monitor.frequency = "1h"
    mock_monitor.processor = "lite"
    mock_monitor.settings = Mock()
    mock_monitor.settings.query = "Updated query"

    monitor_tools.parallel_client.monitor.update = Mock(return_value=mock_monitor)

    result = monitor_tools.update_monitor(monitor_id="test-monitor-id", frequency="1h")
    result_dict = json.loads(result)

    assert result_dict["monitor_id"] == "test-monitor-id"
    assert result_dict["frequency"] == "1h"
    assert result_dict["updated"] is True


def test_cancel_monitor(monitor_tools):
    """Test cancel_monitor function."""
    mock_monitor = Mock()
    mock_monitor.monitor_id = "test-monitor-id"
    mock_monitor.status = "cancelled"

    monitor_tools.parallel_client.monitor.cancel = Mock(return_value=mock_monitor)

    result = monitor_tools.cancel_monitor(monitor_id="test-monitor-id")
    result_dict = json.loads(result)

    assert result_dict["monitor_id"] == "test-monitor-id"
    assert result_dict["status"] == "cancelled"
    assert result_dict["cancelled"] is True


def test_get_monitor_events(monitor_tools):
    """Test get_monitor_events function."""
    mock_output = Mock()
    mock_output.content = {"summary": "New AI funding announced"}
    mock_output.basis = []

    mock_event = Mock()
    mock_event.event_id = "test-event-id"
    mock_event.event_type = "event_stream"
    mock_event.event_group_id = "test-group-id"
    mock_event.event_date = "2026-01-01"
    mock_event.output = mock_output

    mock_response = Mock()
    mock_response.events = [mock_event]
    mock_response.next_cursor = None

    monitor_tools.parallel_client.monitor.events = Mock(return_value=mock_response)

    result = monitor_tools.get_monitor_events(monitor_id="test-monitor-id")
    result_dict = json.loads(result)

    assert len(result_dict["events"]) == 1
    assert result_dict["events"][0]["event_type"] == "event_stream"
    assert result_dict["events"][0]["event_date"] == "2026-01-01"
    assert result_dict["events"][0]["content"] == {"summary": "New AI funding announced"}
    assert result_dict["has_more"] is False


def test_get_monitor_events_error(monitor_tools):
    """Test get_monitor_events error handling."""
    monitor_tools.parallel_client.monitor.events = Mock(side_effect=Exception("API Error"))

    result = monitor_tools.get_monitor_events(monitor_id="test-monitor-id")
    result_dict = json.loads(result)

    assert "error" in result_dict
    assert "Get events failed" in result_dict["error"]
