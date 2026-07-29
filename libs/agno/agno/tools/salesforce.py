"""
Salesforce CRM tools for Agno agents.

Provides CRUD operations, SOQL queries, SOSL search, and metadata discovery
for any Salesforce object (standard or custom).

Requirements:
    ``pip install simple-salesforce``

Authentication (pick one):
    **Username / Password** — set SALESFORCE_USERNAME, SALESFORCE_PASSWORD,
    SALESFORCE_SECURITY_TOKEN, and optionally SALESFORCE_DOMAIN env vars.

    **Session / Instance URL** — pass ``instance_url`` and ``session_id`` directly.
    Use this when SOAP API login is disabled (default in newer Developer Edition orgs).
"""

import json
import textwrap
from os import getenv
from typing import Any, Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from simple_salesforce import Salesforce  # type: ignore[import-not-found]
except ImportError:
    raise ImportError("`simple-salesforce` not installed. Please install using `pip install simple-salesforce`.")

SALESFORCE_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Salesforce CRM tools for querying, creating, and managing records.

    ## SOQL (query tool)
    - `SELECT Id, Name FROM Account WHERE Industry = 'Technology' LIMIT 10`
    - `SELECT Id, Name, Account.Name FROM Contact WHERE Account.Industry = 'Technology'` — relationship query
    - `SELECT COUNT() FROM Lead WHERE Status = 'Open - Not Contacted'` — aggregate

    ## SOSL (search tool)
    SOSL requires FIND with curly braces and explicit RETURNING with object names and fields:
    - `FIND {search term} IN ALL FIELDS RETURNING Account(Id, Name), Contact(Id, Name, Email)`
    - `FIND {John} IN NAME FIELDS RETURNING Lead(Id, Name, Company)`
    SOSL does NOT support `RETURNING ALL OBJECTS` or `RETURNING ALL FIELDS`. You must specify object names and fields.

    ## Creating Records
    Use describe_object first to discover field names. Skip fields where defaultedOnCreate is true (e.g. OwnerId) — they are auto-populated.""")


class SalesforceTools(Toolkit):
    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        security_token: Optional[str] = None,
        domain: Optional[str] = None,
        instance_url: Optional[str] = None,
        session_id: Optional[str] = None,
        max_records: int = 200,
        max_fields: int = 100,
        list_objects: bool = True,
        describe_object: bool = True,
        get_record: bool = True,
        query: bool = True,
        search: bool = True,
        create_record: bool = False,
        update_record: bool = False,
        delete_record: bool = False,
        get_report: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        """Initialize Salesforce tools.

        Supports two authentication methods:
        1. Username/password: Set SALESFORCE_USERNAME, SALESFORCE_PASSWORD,
           SALESFORCE_SECURITY_TOKEN env vars, or pass them directly.
        2. Session/instance: Pass instance_url and session_id directly.
           Use this when SOAP API login is disabled.

        Args:
            username: Salesforce username. Falls back to SALESFORCE_USERNAME env var.
            password: Salesforce password. Falls back to SALESFORCE_PASSWORD env var.
            security_token: Security token. Falls back to SALESFORCE_SECURITY_TOKEN env var.
            domain: Login domain. Falls back to SALESFORCE_DOMAIN or "login".
            instance_url: Salesforce instance URL for session-based auth.
            session_id: Session ID for session-based auth.
            max_records: Maximum records to return from queries. Default 200.
            max_fields: Maximum fields to return from describe. Default 100.
            list_objects: Enable list_objects tool. Default True.
            describe_object: Enable describe_object tool. Default True.
            get_record: Enable get_record tool. Default True.
            query: Enable query tool. Default True.
            search: Enable search tool. Default True.
            create_record: Enable create_record tool. Default False.
            update_record: Enable update_record tool. Default False.
            delete_record: Enable delete_record tool. Default False.
            get_report: Enable get_report tool. Default False.
            all: Enable all tools. Default False.
            instructions: Custom instructions for the agent.
            add_instructions: Whether to include default SOQL/SOSL instructions.
        """
        self.instructions = instructions or SALESFORCE_INSTRUCTIONS if add_instructions else None
        self.max_records = max_records
        self.max_fields = max_fields

        username = username or getenv("SALESFORCE_USERNAME")
        password = password or getenv("SALESFORCE_PASSWORD")
        security_token = security_token or getenv("SALESFORCE_SECURITY_TOKEN")
        domain = domain or getenv("SALESFORCE_DOMAIN", "login")

        if instance_url and session_id:
            self.sf = Salesforce(instance_url=instance_url, session_id=session_id)
        elif username and password:
            self.sf = Salesforce(
                username=username,
                password=password,
                security_token=security_token or "",
                domain=domain,
            )
        else:
            raise ValueError(
                "Salesforce credentials not configured. "
                "Set SALESFORCE_USERNAME, SALESFORCE_PASSWORD, and SALESFORCE_SECURITY_TOKEN "
                "or pass instance_url and session_id."
            )

        tools: List[Callable] = []
        if all or list_objects:
            tools.append(self.list_objects)
        if all or describe_object:
            tools.append(self.describe_object)
        if all or get_record:
            tools.append(self.get_record)
        if all or query:
            tools.append(self.query)
        if all or search:
            tools.append(self.search)
        if all or create_record:
            tools.append(self.create_record)
        if all or update_record:
            tools.append(self.update_record)
        if all or delete_record:
            tools.append(self.delete_record)
        if all or get_report:
            tools.append(self.get_report)

        super().__init__(name="salesforce_tools", tools=tools, instructions=self.instructions, **kwargs)

    def list_objects(self) -> str:
        """List all available Salesforce objects in the org.

        Returns:
            JSON with object names, labels, and CRUD capabilities.
        """
        try:
            describe = self.sf.describe()
            objects = [
                {
                    "name": obj.get("name", ""),
                    "label": obj.get("label"),
                    "queryable": obj.get("queryable"),
                    "createable": obj.get("createable"),
                    "updateable": obj.get("updateable"),
                    "deletable": obj.get("deletable"),
                }
                for obj in describe.get("sobjects", [])
            ]

            total = len(objects)
            if total > self.max_records:
                objects = objects[: self.max_records]

            return json.dumps({"total": total, "returned": len(objects), "objects": objects})
        except Exception as e:
            logger.exception("Error listing Salesforce objects")
            return json.dumps({"error": str(e)})

    def describe_object(self, sobject: str) -> str:
        """Get the schema for a Salesforce object including field names, types, and picklist values.

        Use this before creating or updating records to discover required fields.

        Args:
            sobject: API name of the Salesforce object (e.g. Account, Contact, Lead, Opportunity).

        Returns:
            JSON with object metadata and field definitions including type, nillable, and picklist values.
        """
        try:
            describe = getattr(self.sf, sobject).describe()
            all_fields = describe.get("fields", [])
            fields = []
            for field in all_fields[: self.max_fields]:
                field_info: Dict[str, Any] = {
                    "name": field.get("name"),
                    "label": field.get("label"),
                    "type": field.get("type"),
                    "nillable": field.get("nillable"),
                    "createable": field.get("createable"),
                    "updateable": field.get("updateable"),
                    "defaultedOnCreate": field.get("defaultedOnCreate"),
                }
                picklist = field.get("picklistValues")
                if picklist:
                    field_info["picklistValues"] = [
                        {"value": p.get("value"), "label": p.get("label")} for p in picklist if p.get("active")
                    ]
                if field.get("type") == "reference":
                    field_info["referenceTo"] = field.get("referenceTo")
                fields.append(field_info)

            return json.dumps(
                {
                    "name": describe.get("name"),
                    "label": describe.get("label"),
                    "createable": describe.get("createable"),
                    "updateable": describe.get("updateable"),
                    "deletable": describe.get("deletable"),
                    "totalFields": len(all_fields),
                    "returnedFields": len(fields),
                    "fields": fields,
                }
            )
        except Exception as e:
            logger.exception(f"Error describing Salesforce object {sobject}")
            return json.dumps({"error": str(e)})

    def get_record(self, sobject: str, record_id: str, fields: str = "") -> str:
        """Get a single Salesforce record by its ID.

        Args:
            sobject: API name of the Salesforce object.
            record_id: The 15 or 18 character Salesforce record ID.
            fields: Comma-separated field names to return. If empty, returns all fields.

        Returns:
            JSON with the record's field values.
        """
        try:
            if fields:
                field_list = fields.replace(" ", "")
                soql = f"SELECT {field_list} FROM {sobject} WHERE Id = '{record_id}'"
                result = self.sf.query(soql)
                records = result.get("records", [])
                if not records:
                    return json.dumps({"error": f"{sobject} record {record_id} not found."})
                return json.dumps(records[0])
            else:
                record = getattr(self.sf, sobject).get(record_id)
                return json.dumps(record)
        except Exception as e:
            logger.exception(f"Error getting {sobject} record {record_id}")
            return json.dumps({"error": str(e)})

    def create_record(self, sobject: str, record_data: str) -> str:
        """Create a new Salesforce record.

        Args:
            sobject: API name of the Salesforce object.
            record_data: JSON string of field name-value pairs.

        Returns:
            JSON with the new record's ID and success status.
        """
        try:
            data = json.loads(record_data) if isinstance(record_data, str) else record_data
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in record_data: {e}"})

        try:
            result = getattr(self.sf, sobject).create(data)
            return json.dumps({"id": result.get("id"), "success": result.get("success"), "sobject": sobject})
        except Exception as e:
            logger.exception(f"Error creating {sobject} record")
            return json.dumps({"error": str(e)})

    def update_record(self, sobject: str, record_id: str, record_data: str) -> str:
        """Update an existing Salesforce record.

        Args:
            sobject: API name of the Salesforce object.
            record_id: The Salesforce record ID to update.
            record_data: JSON string of field name-value pairs to update.

        Returns:
            JSON with success status and record ID.
        """
        try:
            data = json.loads(record_data) if isinstance(record_data, str) else record_data
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in record_data: {e}"})

        try:
            getattr(self.sf, sobject).update(record_id, data)
            return json.dumps({"status": "success", "id": record_id, "sobject": sobject})
        except Exception as e:
            logger.exception(f"Error updating {sobject} record {record_id}")
            return json.dumps({"error": str(e)})

    def delete_record(self, sobject: str, record_id: str) -> str:
        """Delete a Salesforce record.

        Args:
            sobject: API name of the Salesforce object.
            record_id: The Salesforce record ID to delete.

        Returns:
            JSON with success status and record ID.
        """
        try:
            getattr(self.sf, sobject).delete(record_id)
            return json.dumps({"status": "success", "id": record_id, "sobject": sobject})
        except Exception as e:
            logger.exception(f"Error deleting {sobject} record {record_id}")
            return json.dumps({"error": str(e)})

    def query(self, soql: str) -> str:
        """Execute a SOQL query against Salesforce.

        Args:
            soql: The SOQL query string.

        Returns:
            JSON with totalSize, returned count, and records array.
        """
        try:
            result = self.sf.query(soql)
            records = result.get("records", [])
            total_size = result.get("totalSize", len(records))

            if len(records) > self.max_records:
                records = records[: self.max_records]

            return json.dumps(
                {"totalSize": total_size, "returned": len(records), "done": result.get("done"), "records": records}
            )
        except Exception as e:
            logger.exception("Error executing SOQL query")
            return json.dumps({"error": str(e)})

    def search(self, sosl: str) -> str:
        """Execute a SOSL full-text search across Salesforce objects.

        Args:
            sosl: The SOSL search string.

        Returns:
            JSON with searchRecords array containing matching records.
        """
        try:
            result = self.sf.search(sosl)
            records = result.get("searchRecords", []) if isinstance(result, dict) else []
            if len(records) > self.max_records:
                result["searchRecords"] = records[: self.max_records]
            return json.dumps(result)
        except Exception as e:
            logger.exception("Error executing SOSL search")
            return json.dumps({"error": str(e)})

    def get_report(self, report_id: str) -> str:
        """Run a Salesforce report and return the results.

        Args:
            report_id: The Salesforce report ID (15 or 18 character).

        Returns:
            JSON with reportMetadata and factMap containing the report data.
        """
        try:
            response = self.sf.restful(f"analytics/reports/{report_id}", method="GET")
            if not isinstance(response, dict):
                return json.dumps({"error": "Unexpected report response format."})
            return json.dumps({"reportMetadata": response.get("reportMetadata"), "factMap": response.get("factMap")})
        except Exception as e:
            logger.exception(f"Error running report {report_id}")
            return json.dumps({"error": str(e)})
