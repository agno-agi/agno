import json
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.salesforce import SalesforceTools


@pytest.fixture
def mock_sf_client():
    with patch("agno.tools.salesforce.Salesforce") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        instance.base_url = "https://test.salesforce.com/services/data/v59.0/"
        instance.headers = {"Authorization": "Bearer test_token"}
        yield instance


@pytest.fixture
def sf_tools(mock_sf_client):
    return SalesforceTools(
        username="test@example.com",
        password="testpass",
        security_token="testtoken",
        domain="login",
        all=True,
    )


@pytest.fixture
def account_describe():
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

    def test_init_session_auth(self, mock_sf_client):
        tools = SalesforceTools(
            instance_url="https://my.salesforce.com",
            session_id="session123",
        )
        sf = tools._get_client()
        assert sf is not None
        from agno.tools.salesforce import Salesforce

        Salesforce.assert_called_with(
            instance_url="https://my.salesforce.com",
            session_id="session123",
        )

    def test_configurable_limits(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            max_records=50,
            max_fields=25,
        )
        assert tools.max_records == 50
        assert tools.max_fields == 25

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

    def test_default_registration_read_only(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            security_token="testtoken",
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        # Read ops enabled by default
        assert "list_objects" in fn_names
        assert "describe_object" in fn_names
        assert "get_record" in fn_names
        assert "query" in fn_names
        assert "search" in fn_names
        # Write ops disabled by default
        assert "create_record" not in fn_names
        assert "update_record" not in fn_names
        assert "delete_record" not in fn_names
        assert "get_report" not in fn_names

    def test_tool_registration_selective(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            security_token="testtoken",
            enable_list_objects=True,
            enable_query=True,
            enable_create_record=True,
            enable_describe_object=False,
            enable_get_record=False,
            enable_search=False,
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        assert "list_objects" in fn_names
        assert "query" in fn_names
        assert "create_record" in fn_names
        assert "describe_object" not in fn_names


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

    def test_list_objects_capping(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            max_records=3,
            all=True,
        )
        mock_sf_client.describe.return_value = {
            "sobjects": [
                {
                    "name": f"Obj{i}",
                    "label": f"Obj {i}",
                    "queryable": True,
                    "createable": True,
                    "updateable": True,
                    "deletable": True,
                }
                for i in range(10)
            ]
        }

        result = json.loads(tools.list_objects())
        assert result["total"] == 10
        assert result["returned"] == 3
        assert len(result["objects"]) == 3

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
                }
            ]
        }

        sf_tools.list_objects()
        sf_tools.list_objects()
        mock_sf_client.describe.assert_called_once()

    def test_describe_object(self, sf_tools, mock_sf_client, account_describe):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.describe.return_value = account_describe

        result = json.loads(sf_tools.describe_object(sobject="Account"))
        assert result["name"] == "Account"
        assert result["totalFields"] == 4
        assert result["returnedFields"] == 4

        industry_field = next(f for f in result["fields"] if f["name"] == "Industry")
        assert len(industry_field["picklistValues"]) == 2

        owner_field = next(f for f in result["fields"] if f["name"] == "OwnerId")
        assert owner_field["referenceTo"] == ["User"]

    def test_describe_object_field_capping(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            max_fields=2,
            all=True,
        )
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.describe.return_value = {
            "name": "Account",
            "label": "Account",
            "createable": True,
            "updateable": True,
            "deletable": True,
            "fields": [
                {
                    "name": f"Field{i}",
                    "label": f"Field {i}",
                    "type": "string",
                    "nillable": True,
                    "createable": True,
                    "updateable": True,
                }
                for i in range(10)
            ],
        }

        result = json.loads(tools.describe_object(sobject="Account"))
        assert result["totalFields"] == 10
        assert result["returnedFields"] == 2
        assert len(result["fields"]) == 2

    def test_describe_object_caching(self, sf_tools, mock_sf_client, account_describe):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.describe.return_value = account_describe

        sf_tools.describe_object(sobject="Account")
        sf_tools.describe_object(sobject="Account")
        mock_sf_client.Account.describe.assert_called_once()

    def test_describe_object_empty_name(self, sf_tools):
        result = json.loads(sf_tools.describe_object(sobject=""))
        assert "error" in result


class TestCRUD:
    def test_get_record(self, sf_tools, mock_sf_client):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.get.return_value = OrderedDict(
            [("Id", "001000000000ABC"), ("Name", "Acme Corp"), ("Industry", "Technology")]
        )

        result = json.loads(sf_tools.get_record(sobject="Account", record_id="001000000000ABC"))
        assert result["Id"] == "001000000000ABC"
        assert result["Name"] == "Acme Corp"

    def test_get_record_with_fields(self, sf_tools, mock_sf_client):
        mock_sf_client.query.return_value = {
            "records": [{"Id": "001000000000ABC", "Name": "Acme Corp"}],
            "totalSize": 1,
        }

        result = json.loads(sf_tools.get_record(sobject="Account", record_id="001000000000ABC", fields="Id,Name"))
        assert result["Id"] == "001000000000ABC"

    def test_get_record_not_found(self, sf_tools, mock_sf_client):
        mock_sf_client.query.return_value = {"records": [], "totalSize": 0}

        result = json.loads(sf_tools.get_record(sobject="Account", record_id="001000000000XYZ", fields="Id"))
        assert "error" in result
        assert "not found" in result["error"]

    def test_get_record_invalid_id_blocked(self, sf_tools):
        result = json.loads(sf_tools.get_record(sobject="Account", record_id="' OR Id != '", fields="Id,Name"))
        assert "error" in result
        assert "Invalid Salesforce record ID" in result["error"]

    def test_get_record_invalid_fields_blocked(self, sf_tools, mock_sf_client):
        result = json.loads(
            sf_tools.get_record(sobject="Account", record_id="001000000000ABC", fields="Id FROM Account--")
        )
        assert "error" in result
        assert "Invalid field names" in result["error"]

    def test_get_record_missing_params(self, sf_tools):
        result = json.loads(sf_tools.get_record(sobject="", record_id=""))
        assert "error" in result

    def test_create_record(self, sf_tools, mock_sf_client):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.create.return_value = {"id": "001000000000NEW", "success": True}

        result = json.loads(
            sf_tools.create_record(
                sobject="Account",
                record_data='{"Name": "New Corp", "Industry": "Technology"}',
            )
        )
        assert result["id"] == "001000000000NEW"
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
                record_id="001000000000ABC",
                record_data='{"Industry": "Finance"}',
            )
        )
        assert result["status"] == "success"
        assert result["id"] == "001000000000ABC"

    def test_update_record_invalid_id(self, sf_tools):
        result = json.loads(sf_tools.update_record(sobject="Account", record_id="bad-id!", record_data='{"Name": "x"}'))
        assert "error" in result
        assert "Invalid Salesforce record ID" in result["error"]

    def test_update_record_missing_params(self, sf_tools):
        result = json.loads(sf_tools.update_record(sobject="", record_id="", record_data=""))
        assert "error" in result

    def test_delete_record(self, sf_tools, mock_sf_client):
        mock_sf_client.Account = MagicMock()
        mock_sf_client.Account.delete.return_value = 204

        result = json.loads(sf_tools.delete_record(sobject="Account", record_id="001000000000ABC"))
        assert result["status"] == "success"
        assert result["id"] == "001000000000ABC"

    def test_delete_record_invalid_id(self, sf_tools):
        result = json.loads(sf_tools.delete_record(sobject="Account", record_id="'; DROP TABLE--"))
        assert "error" in result
        assert "Invalid Salesforce record ID" in result["error"]

    def test_delete_record_missing_params(self, sf_tools):
        result = json.loads(sf_tools.delete_record(sobject="", record_id=""))
        assert "error" in result


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
        assert result["returned"] == 2
        assert len(result["records"]) == 2

    def test_query_record_cap(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            max_records=5,
            all=True,
        )
        mock_sf_client.query.return_value = {
            "totalSize": 20,
            "done": True,
            "records": [{"Id": f"{i:03d}"} for i in range(20)],
        }

        result = json.loads(tools.query(soql="SELECT Id FROM Account"))
        assert result["totalSize"] == 20
        assert result["returned"] == 5
        assert len(result["records"]) == 5

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


class TestReport:
    def test_get_report_success(self, sf_tools, mock_sf_client):
        mock_sf_client.restful.return_value = {
            "reportMetadata": {"id": "00O000000000001", "name": "My Report"},
            "factMap": {"T!T": {"rows": []}},
        }

        result = json.loads(sf_tools.get_report(report_id="00O000000000001"))
        assert "reportMetadata" in result
        assert result["reportMetadata"]["name"] == "My Report"

    def test_get_report_not_found(self, sf_tools, mock_sf_client):
        from simple_salesforce import SalesforceError

        mock_sf_client.restful.side_effect = SalesforceError("url", 404, "res", "Not Found")

        result = json.loads(sf_tools.get_report(report_id="00O000000000BAD"))
        assert "error" in result

    def test_get_report_empty_id(self, sf_tools):
        result = json.loads(sf_tools.get_report(report_id=""))
        assert "error" in result

    def test_get_report_unexpected_format(self, sf_tools, mock_sf_client):
        mock_sf_client.restful.return_value = "not a dict"

        result = json.loads(sf_tools.get_report(report_id="00O000000000001"))
        assert "error" in result


class TestErrorHandling:
    @patch.dict("os.environ", {}, clear=True)
    def test_no_credentials(self, mock_sf_client):
        tools = SalesforceTools(
            username=None,
            password=None,
            security_token=None,
        )
        result = json.loads(tools.query(soql="SELECT Id FROM Account"))
        assert "error" in result
        assert "not connected" in result["error"]

    def test_salesforce_api_error(self, sf_tools, mock_sf_client):
        from simple_salesforce import SalesforceError

        mock_sf_client.query.side_effect = SalesforceError("https://test.salesforce.com", 400, "test", "Bad request")

        result = json.loads(sf_tools.query(soql="INVALID SOQL"))
        assert "error" in result

    def test_auth_failure(self, mock_sf_client):
        from simple_salesforce import SalesforceAuthenticationFailed

        from agno.tools.salesforce import Salesforce

        Salesforce.side_effect = SalesforceAuthenticationFailed(401, "Bad credentials")

        tools = SalesforceTools(
            username="bad@example.com",
            password="wrong",
            security_token="bad",
        )
        result = json.loads(tools.query(soql="SELECT Id FROM Account"))
        assert "error" in result


class TestValidation:
    def test_valid_sf_ids(self):
        assert SalesforceTools._validate_sf_id("001000000000ABC")
        assert SalesforceTools._validate_sf_id("001000000000ABCDEF")
        assert SalesforceTools._validate_sf_id("00Qg50000035xNV")

    def test_invalid_sf_ids(self):
        assert not SalesforceTools._validate_sf_id("")
        assert not SalesforceTools._validate_sf_id("short")
        assert not SalesforceTools._validate_sf_id("' OR Id != '")
        assert not SalesforceTools._validate_sf_id("001-000-000-ABC")

    def test_valid_field_names(self):
        assert SalesforceTools._validate_field_names("Id,Name,Industry")
        assert SalesforceTools._validate_field_names("Account.Name")
        assert SalesforceTools._validate_field_names("Custom_Field__c")

    def test_invalid_field_names(self):
        assert not SalesforceTools._validate_field_names("Id FROM Account--")
        assert not SalesforceTools._validate_field_names("Id; DROP")
        assert not SalesforceTools._validate_field_names("Id' OR '1'='1")


class TestJsonParseability:
    def test_list_objects_always_parseable(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            max_records=5,
            all=True,
        )
        mock_sf_client.describe.return_value = {
            "sobjects": [
                {
                    "name": f"Object{i}",
                    "label": f"Object {i}",
                    "queryable": True,
                    "createable": True,
                    "updateable": True,
                    "deletable": True,
                }
                for i in range(100)
            ]
        }

        raw = tools.list_objects()
        result = json.loads(raw)
        assert isinstance(result, dict)
        assert result["total"] == 100
        assert result["returned"] == 5

    def test_query_always_parseable(self, mock_sf_client):
        tools = SalesforceTools(
            username="test@example.com",
            password="testpass",
            max_records=3,
            all=True,
        )
        mock_sf_client.query.return_value = {
            "totalSize": 50,
            "done": True,
            "records": [{"Id": f"{i:018d}", "Description": "x" * 10000} for i in range(50)],
        }

        raw = tools.query(soql="SELECT Id, Description FROM Account")
        result = json.loads(raw)
        assert result["totalSize"] == 50
        assert result["returned"] == 3
