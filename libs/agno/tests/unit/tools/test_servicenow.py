"""Unit tests for ServiceNowTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.servicenow import ServiceNowTools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session():
    """Patch requests.Session so no real HTTP calls are made."""
    with patch("agno.tools.servicenow.requests.Session") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        # Default: auth is set during __init__
        instance.auth = ("testuser", "testpass")
        yield instance


@pytest.fixture
def sn_tools(mock_session):
    """Create a ServiceNowTools instance with test credentials."""
    return ServiceNowTools(
        instance="dev12345",
        username="testuser",
        password="testpass",
    )


@pytest.fixture
def incident_response():
    """Mock ServiceNow incident GET response (list)."""
    return {
        "result": [
            {
                "sys_id": "abc123",
                "number": "INC0010001",
                "short_description": "Email server down",
                "description": "Users cannot send or receive email.",
                "state": "1",
                "priority": "1",
                "urgency": "1",
                "impact": "1",
                "category": "network",
                "assignment_group": {
                    "link": "https://dev12345.service-now.com/api/now/table/sys_user_group/grp1",
                    "value": "grp1",
                },
                "assigned_to": {
                    "link": "https://dev12345.service-now.com/api/now/table/sys_user/usr1",
                    "value": "usr1",
                },
                "caller_id": {"link": "https://dev12345.service-now.com/api/now/table/sys_user/usr2", "value": "usr2"},
                "opened_at": "2026-03-01 08:00:00",
                "resolved_at": "",
                "closed_at": "",
            }
        ]
    }


@pytest.fixture
def created_incident_response():
    """Mock ServiceNow incident POST response."""
    return {
        "result": {
            "sys_id": "new123",
            "number": "INC0010002",
            "short_description": "New incident",
            "state": "1",
        }
    }


# ---------------------------------------------------------------------------
# Test 1: Initialization and configuration
# ---------------------------------------------------------------------------


class TestServiceNowInit:
    def test_init_with_credentials(self, mock_session):
        tools = ServiceNowTools(
            instance="dev12345",
            username="testuser",
            password="testpass",
        )
        assert tools.instance == "dev12345"
        assert tools.username == "testuser"
        assert tools.password == "testpass"
        assert tools.base_url == "https://dev12345.service-now.com/api/now/table"
        assert tools.timeout == 30

    def test_init_with_env_variables(self, mock_session):
        with patch.dict(
            "os.environ",
            {
                "SERVICENOW_INSTANCE": "env-instance",
                "SERVICENOW_USERNAME": "env-user",
                "SERVICENOW_PASSWORD": "env-pass",
            },
        ):
            tools = ServiceNowTools()
            assert tools.instance == "env-instance"
            assert tools.username == "env-user"
            assert tools.password == "env-pass"

    def test_init_custom_timeout(self, mock_session):
        tools = ServiceNowTools(
            instance="dev12345",
            username="testuser",
            password="testpass",
            timeout=60,
        )
        assert tools.timeout == 60

    def test_tool_registration_all(self, mock_session):
        tools = ServiceNowTools(
            instance="dev12345",
            username="testuser",
            password="testpass",
            all=True,
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        assert "get_incident" in fn_names
        assert "create_incident" in fn_names
        assert "update_incident" in fn_names
        assert "query_incidents" in fn_names
        assert "add_comment" in fn_names
        assert "get_change_request" in fn_names
        assert "create_change_request" in fn_names
        assert "query_table" in fn_names
        assert "get_user" in fn_names

    def test_tool_registration_selective(self, mock_session):
        tools = ServiceNowTools(
            instance="dev12345",
            username="testuser",
            password="testpass",
            enable_get_incident=True,
            enable_create_incident=False,
            enable_update_incident=False,
            enable_query_incidents=True,
            enable_add_comment=False,
            enable_get_change_request=False,
            enable_create_change_request=False,
            enable_query_table=False,
            enable_get_user=False,
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        assert "get_incident" in fn_names
        assert "query_incidents" in fn_names
        assert "create_incident" not in fn_names
        assert "update_incident" not in fn_names


# ---------------------------------------------------------------------------
# Test 2: Get incident (success + not found + missing params)
# ---------------------------------------------------------------------------


class TestGetIncident:
    def test_get_incident_by_number(self, sn_tools, mock_session, incident_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = incident_response
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        result = json.loads(sn_tools.get_incident(number="INC0010001"))

        assert result["number"] == "INC0010001"
        assert result["sys_id"] == "abc123"
        assert result["short_description"] == "Email server down"
        mock_session.request.assert_called_once()
        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["method"] == "GET"
        assert "incident" in call_kwargs.kwargs["url"]

    def test_get_incident_by_sys_id(self, sn_tools, mock_session):
        single_response = {
            "result": {
                "sys_id": "abc123",
                "number": "INC0010001",
                "short_description": "Test",
                "description": "",
                "state": "1",
                "priority": "2",
                "urgency": "2",
                "impact": "2",
                "category": "",
                "assignment_group": "",
                "assigned_to": "",
                "caller_id": "",
                "opened_at": "2026-03-01 08:00:00",
                "resolved_at": "",
                "closed_at": "",
            }
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = single_response
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        result = json.loads(sn_tools.get_incident(sys_id="abc123"))

        assert result["sys_id"] == "abc123"
        call_kwargs = mock_session.request.call_args
        assert "incident/abc123" in call_kwargs.kwargs["url"]

    def test_get_incident_not_found(self, sn_tools, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": []}
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        result = json.loads(sn_tools.get_incident(number="INC9999999"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_get_incident_no_params(self, sn_tools):
        result = json.loads(sn_tools.get_incident())
        assert "error" in result
        assert "Provide either" in result["error"]


# ---------------------------------------------------------------------------
# Test 3: Create incident + error handling
# ---------------------------------------------------------------------------


class TestCreateIncident:
    def test_create_incident_success(self, sn_tools, mock_session, created_incident_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = created_incident_response
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        result = json.loads(
            sn_tools.create_incident(
                short_description="New incident",
                urgency="1",
                impact="1",
            )
        )

        assert result["number"] == "INC0010002"
        assert result["sys_id"] == "new123"
        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["method"] == "POST"
        payload = call_kwargs.kwargs["json"]
        assert payload["short_description"] == "New incident"
        assert payload["urgency"] == "1"
        assert payload["impact"] == "1"

    def test_create_incident_with_optional_fields(self, sn_tools, mock_session, created_incident_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = created_incident_response
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        sn_tools.create_incident(
            short_description="Test",
            category="hardware",
            assignment_group="grp-sys-id",
            caller_id="usr-sys-id",
        )

        payload = mock_session.request.call_args.kwargs["json"]
        assert payload["category"] == "hardware"
        assert payload["assignment_group"] == "grp-sys-id"
        assert payload["caller_id"] == "usr-sys-id"

    def test_create_incident_http_error(self, sn_tools, mock_session):
        import requests

        mock_error_resp = MagicMock()
        mock_error_resp.status_code = 403
        mock_error_resp.text = "Insufficient rights"
        http_error = requests.exceptions.HTTPError(response=mock_error_resp)

        mock_session.request.side_effect = http_error

        result = json.loads(sn_tools.create_incident(short_description="Will fail"))
        assert "error" in result
        assert "403" in result["error"]


# ---------------------------------------------------------------------------
# Test 4: Query table validation + truncation
# ---------------------------------------------------------------------------


class TestQueryTable:
    def test_query_table_success(self, sn_tools, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": [{"sys_id": "r1", "name": "Record 1"}]}
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        result = json.loads(sn_tools.query_table(table="cmdb_ci", query="active=true", limit=10))

        assert len(result) == 1
        assert result[0]["sys_id"] == "r1"
        call_kwargs = mock_session.request.call_args
        assert "cmdb_ci" in call_kwargs.kwargs["url"]

    def test_query_table_invalid_name(self, sn_tools):
        result = json.loads(sn_tools.query_table(table="../etc/passwd"))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_query_table_invalid_name_special_chars(self, sn_tools):
        result = json.loads(sn_tools.query_table(table="table;DROP"))
        assert "error" in result

    def test_query_table_limit_cap(self, sn_tools, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": []}
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        sn_tools.query_table(table="incident", limit=9999)

        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["params"]["sysparm_limit"] == "200"

    def test_query_table_with_fields(self, sn_tools, mock_session):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": []}
        mock_resp.raise_for_status.return_value = None
        mock_session.request.return_value = mock_resp

        sn_tools.query_table(table="incident", fields="sys_id,number")

        call_kwargs = mock_session.request.call_args
        assert call_kwargs.kwargs["params"]["sysparm_fields"] == "sys_id,number"


# ---------------------------------------------------------------------------
# Test 5: Error handling (timeout, connection, missing config)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_timeout_error(self, sn_tools, mock_session):
        import requests

        mock_session.request.side_effect = requests.exceptions.Timeout("timed out")

        result = json.loads(sn_tools.query_incidents(query="active=true"))
        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_connection_error(self, sn_tools, mock_session):
        import requests

        mock_session.request.side_effect = requests.exceptions.ConnectionError("DNS failure")

        result = json.loads(sn_tools.get_incident(number="INC0010001"))
        assert "error" in result
        assert "Connection error" in result["error"]

    def test_missing_instance(self, mock_session):
        mock_session.auth = None
        tools = ServiceNowTools(
            instance=None,
            username="user",
            password="pass",
        )
        result = json.loads(tools.get_incident(number="INC0010001"))
        assert "error" in result

    def test_missing_credentials(self, mock_session):
        mock_session.auth = None
        tools = ServiceNowTools(
            instance="dev12345",
            username=None,
            password=None,
        )
        result = json.loads(tools.get_incident(number="INC0010001"))
        assert "error" in result

    def test_add_comment_missing_sys_id(self, sn_tools):
        result = json.loads(sn_tools.add_comment(sys_id="", comment="test"))
        assert "error" in result
        assert "sys_id is required" in result["error"]
