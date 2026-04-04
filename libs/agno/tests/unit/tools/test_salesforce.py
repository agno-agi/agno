"""Unit tests for SalesforceTools class."""

import json
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.salesforce import SalesforceTools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sf_client():
    """Patch Salesforce client so no real API calls are made."""
    with patch("agno.tools.salesforce.Salesforce") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.base_url = "https://test.salesforce.com/services/data/v59.0/"
        instance.headers = {"Authorization": "Bearer test_token"}
        yield instance


@pytest.fixture
def sf_tools(mock_sf_client):
    """Create a SalesforceTools instance with test credentials."""
    return SalesforceTools(
        username="test@example.com",
        password="testpass",
        security_token="testtoken",
        domain="login",
    )


@pytest.fixture
def account_describe():
    """Mock Account describe response."""
    return {
        "name": "Account",
        "label": "Account",
        "createable": True,
        "updateable": True,
        "deletable": True,
        "fields": [
            {
                "name": "Id",
                "label": "Account ID",
                "type": "id",
                "nillable": False,
                "createable": False,
                "updateable": False,
                "picklistValues": [],
            },
            {
                "name": "Name",
                "label": "Account Name",
                "type": "string",
                "nillable": False,
                "createable": True,
                "updateable": True,
                "picklistValues": [],
            },
            {
                "name": "Industry",
                "label": "Industry",
                "type": "picklist",
                "nillable": True,
                "createable": True,
                "updateable": True,
                "picklistValues": [
                    {"value": "Technology", "label": "Technology", "active": True},
                    {"value": "Finance", "label": "Finance", "active": True},
                    {"value": "Retired", "label": "Retired", "active": False},
                ],
            },
            {
                "name": "OwnerId",
                "label": "Owner ID",
                "type": "reference",
                "nillable": False,
                "createable": True,
                "updateable": True,
                "picklistValues": [],
                "referenceTo": ["User"],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Test 1: Initialization
# ---------------------------------------------------------------------------


class TestSalesforceInit:
    def test_init_with_credentials(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            security_token="testtoken",
        )
        assert tools.username == "test@example.com"
        assert tools.password == "testpass"
        assert tools.security_token == "testtoken"
        assert tools.domain == "login"

    def test_init_with_env_variables(self, mock_sf_client):
        with patch.dict(
            "os.environ",
            {
                "SALESFORCE_USERNAME": "env@example.com",
                "SALESFORCE_PASSWORD": "envpass",
                "SALESFORCE_SECURITY_TOKEN": "envtoken",
                "SALESFORCE_DOMAIN": "test",
            },
        ):
            tools = SalesforceTools()
            assert tools.username == "env@example.com"
            assert tools.password == "envpass"
            assert tools.security_token == "envtoken"
            assert tools.domain == "test"

    def test_tool_registration_all(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            security_token="testtoken",
            all=True,
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        assert "list_objects" in fn_names
        assert "describe_object" in fn_names
        assert "get_record" in fn_names
        assert "create_record" in fn_names
        assert "update_record" in fn_names
        assert "delete_record" in fn_names
        assert "query" in fn_names
        assert "search" in fn_names
        assert "get_report" in fn_names

    def test_tool_registration_selective(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            security_token="testtoken",
            enable_list_objects=True,
            enable_query=True,
            enable_create_record=False,
            enable_update_record=False,
            enable_delete_record=False,
            enable_describe_object=False,
            enable_get_record=False,
            enable_search=False,
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        assert "list_objects" in fn_names
        assert "query" in fn_names
        assert "create_record" not in fn_names
        assert "delete_record" not in fn_names


# ---------------------------------------------------------------------------
# Test 2: Metadata operations
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_list_objects(self, sf_tools, mock_sf_client):
        mock_sf_client.describe.return_value = {
            "sobjects": [
                {
                    "name": "Account",
                    "label": "Account",
                    "queryable": True,
                    "createable": True,
                    "updateable": True,
                    "deletable": True,
                },
                {
                    "name": "Custom__c",
                    "label": "Custom",
                    "queryable": True,
                    "createable": True,
                    "updateable": True,
                    "deletable": True,
                },
            ]
        }

        result = json.loads(sf_tools.list_objects())
        assert len(result) == 2
        assert result[0]["name"] == "Account"
        assert result[1]["name"] == "Custom__c"

    def test_list_objects_exclude_custom(self, sf_tools, mock_sf_client):
        mock_sf_client.describe.return_value = {
            "sobjects": [
                {
                    "name": "Account",
                    "label": "Account",
                    "queryable": True,
                    "createable": True,
                    "updateable": True,
                    "deletable": True,
                },
                {
                    "name": "Custom__c",
                    "label": "Custom",
                    "queryable": True,
                    "createable": True,
                    "updateable": True,
                    "deletable": True,
                },
            ]
        }

        result = json.loads(sf_tools.list_objects(include_custom=False))
        assert len(result) == 1
        assert result[0]["name"] == "Account"

    def test_list_objects_caching(self, sf_tools, mock_sf_client):
        mock_sf_client.describe.return_value = {
            "sobjects": [
                {
                    "name": "Account",
                    "label": "Account",
                    "queryable": True,
                    "createable": True,
                    "updateable": True,
                    "deletable": True,
                },
            ]
        }

        sf_tools.list_objects()
        sf_tools.list_objects()
        # Should only call describe once due to caching
        mock_sf_client.describe.assert_called_once()

    def test_describe_object(self, sf_tools, mock_sf_client, account_describe):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.describe.return_value = account_describe

        result = json.loads(sf_tools.describe_object(sobject="Account"))
        assert result["name"] == "Account"
        assert len(result["fields"]) == 4

        # Check picklist filtering (only active values)
        industry_field = next(f for f in result["fields"] if f["name"] == "Industry")
        assert len(industry_field["picklistValues"]) == 2

        # Check reference field
        owner_field = next(f for f in result["fields"] if f["name"] == "OwnerId")
        assert owner_field["referenceTo"] == ["User"]

    def test_describe_object_caching(self, sf_tools, mock_sf_client, account_describe):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.describe.return_value = account_describe

        sf_tools.describe_object(sobject="Account")
        sf_tools.describe_object(sobject="Account")
        mock_sf_client.Account.describe.assert_called_once()

    def test_describe_object_empty_name(self, sf_tools):
        result = json.loads(sf_tools.describe_object(sobject=""))
        assert "error" in result


# ---------------------------------------------------------------------------
# Test 3: CRUD operations
# ---------------------------------------------------------------------------


class TestCRUD:
    def test_get_record(self, sf_tools, mock_sf_client):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.get.return_value = OrderedDict(
            [("Id", "001ABC"), ("Name", "Acme Corp"), ("Industry", "Technology")]
        )

        result = json.loads(sf_tools.get_record(sobject="Account", record_id="001ABC"))
        assert result["Id"] == "001ABC"
        assert result["Name"] == "Acme Corp"

    def test_get_record_with_fields(self, sf_tools, mock_sf_client):
        mock_sf_client.query.return_value = {
            "records": [{"Id": "001ABC", "Name": "Acme Corp"}],
            "totalSize": 1,
        }

        result = json.loads(sf_tools.get_record(sobject="Account", record_id="001ABC", fields="Id,Name"))
        assert result["Id"] == "001ABC"

    def test_get_record_not_found(self, sf_tools, mock_sf_client):
        mock_sf_client.query.return_value = {"records": [], "totalSize": 0}

        result = json.loads(sf_tools.get_record(sobject="Account", record_id="001INVALID", fields="Id"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_get_record_missing_params(self, sf_tools):
        result = json.loads(sf_tools.get_record(sobject="", record_id=""))
        assert "error" in result

    def test_create_record(self, sf_tools, mock_sf_client):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.create.return_value = {"id": "001NEW", "success": True}

        result = json.loads(
            sf_tools.create_record(
                sobject="Account",
                record_data='{"Name": "New Corp", "Industry": "Technology"}',
            )
        )
        assert result["id"] == "001NEW"
        assert result["success"] is True
        assert result["sobject"] == "Account"

    def test_create_record_invalid_json(self, sf_tools):
        result = json.loads(sf_tools.create_record(sobject="Account", record_data="not json"))
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_create_record_missing_params(self, sf_tools):
        result = json.loads(sf_tools.create_record(sobject="", record_data=""))
        assert "error" in result

    def test_update_record(self, sf_tools, mock_sf_client):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.update.return_value = 204

        result = json.loads(
            sf_tools.update_record(
                sobject="Account",
                record_id="001ABC",
                record_data='{"Industry": "Finance"}',
            )
        )
        assert result["status"] == "success"
        assert result["id"] == "001ABC"

    def test_update_record_missing_params(self, sf_tools):
        result = json.loads(sf_tools.update_record(sobject="", record_id="", record_data=""))
        assert "error" in result

    def test_delete_record(self, sf_tools, mock_sf_client):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.delete.return_value = 204

        result = json.loads(sf_tools.delete_record(sobject="Account", record_id="001ABC"))
        assert result["status"] == "success"
        assert result["id"] == "001ABC"

    def test_delete_record_missing_params(self, sf_tools):
        result = json.loads(sf_tools.delete_record(sobject="", record_id=""))
        assert "error" in result


# ---------------------------------------------------------------------------
# Test 4: Query and Search
# ---------------------------------------------------------------------------


class TestQuerySearch:
    def test_query_success(self, sf_tools, mock_sf_client):
        mock_sf_client.query.return_value = {
            "totalSize": 2,
            "done": True,
            "records": [
                {"Id": "001A", "Name": "Acme"},
                {"Id": "001B", "Name": "Globex"},
            ],
        }

        result = json.loads(sf_tools.query(soql="SELECT Id, Name FROM Account LIMIT 2"))
        assert result["totalSize"] == 2
        assert len(result["records"]) == 2

    def test_query_empty(self, sf_tools):
        result = json.loads(sf_tools.query(soql=""))
        assert "error" in result

    def test_search_success(self, sf_tools, mock_sf_client):
        mock_sf_client.search.return_value = {
            "searchRecords": [
                {"Id": "003A", "attributes": {"type": "Contact"}},
            ]
        }

        result = json.loads(sf_tools.search(sosl="FIND {John} RETURNING Contact(Id)"))
        assert "searchRecords" in result

    def test_search_empty(self, sf_tools):
        result = json.loads(sf_tools.search(sosl=""))
        assert "error" in result


# ---------------------------------------------------------------------------
# Test 5: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_no_credentials(self, mock_sf_client):
        tools = SalesforceTools(
            username=None,
            password=None,
            security_token=None,
        )
        result = json.loads(tools.query(soql="SELECT Id FROM Account"))
        assert "error" in result

    def test_salesforce_api_error(self, sf_tools, mock_sf_client):
        from simple_salesforce import SalesforceError

        mock_sf_client.query.side_effect = SalesforceError("https://test.salesforce.com", 400, "test", "Bad request")

        result = json.loads(sf_tools.query(soql="INVALID SOQL"))
        assert "error" in result
