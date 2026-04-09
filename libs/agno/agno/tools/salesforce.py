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
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from simple_salesforce import Salesforce, SalesforceAuthenticationFailed, SalesforceError
except ImportError:
    raise ImportError("`simple-salesforce` not installed. Please install using `pip install simple-salesforce`.")


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
        # Read operations — enabled by default
        enable_list_objects: bool = True,
        enable_describe_object: bool = True,
        enable_get_record: bool = True,
        enable_query: bool = True,
        enable_search: bool = True,
        # Write operations — disabled by default for safety
        enable_create_record: bool = False,
        enable_update_record: bool = False,
        enable_delete_record: bool = False,
        enable_get_report: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.username = username or getenv("SALESFORCE_USERNAME")
        self.password = password or getenv("SALESFORCE_PASSWORD")
        self.security_token = security_token or getenv("SALESFORCE_SECURITY_TOKEN")
        self.domain = domain or getenv("SALESFORCE_DOMAIN", "login")
        self.instance_url = instance_url
        self.session_id = session_id
        self.max_records = max(max_records, 1)
        self.max_fields = max(max_fields, 1)
        self._sf: Optional[Salesforce] = None

        tools: List[Any] = []
        if all or enable_list_objects:
            tools.append(self.list_objects)
        if all or enable_describe_object:
            tools.append(self.describe_object)
        if all or enable_get_record:
            tools.append(self.get_record)
        if all or enable_query:
            tools.append(self.query)
        if all or enable_search:
            tools.append(self.search)
        if all or enable_create_record:
            tools.append(self.create_record)
        if all or enable_update_record:
            tools.append(self.update_record)
        if all or enable_delete_record:
            tools.append(self.delete_record)
        if all or enable_get_report:
            tools.append(self.get_report)

        super().__init__(name="salesforce_tools", tools=tools, **kwargs)

    def _get_client(self) -> Optional[Salesforce]:
        if self._sf is not None:
            return self._sf

        try:
            if self.instance_url and self.session_id:
                self._sf = Salesforce(instance_url=self.instance_url, session_id=self.session_id)
            elif self.username and self.password:
                self._sf = Salesforce(
                    username=self.username,
                    password=self.password,
                    security_token=self.security_token or "",
                    domain=self.domain,
                )
            else:
                logger.error(
                    "Salesforce credentials not configured. "
                    "Set SALESFORCE_USERNAME, SALESFORCE_PASSWORD, and SALESFORCE_SECURITY_TOKEN."
                )
                return None
            return self._sf
        except SalesforceAuthenticationFailed:
            logger.exception("Salesforce authentication failed")
            return None
        except Exception:
            logger.exception("Salesforce connection error")
            return None

    @staticmethod
    def _error(msg: str) -> str:
        return json.dumps({"error": msg})

    @staticmethod
    def _parse_record_data(record_data: str) -> tuple:
        """Returns (data_dict, None) on success or (None, error_json) on failure."""
        try:
            data = json.loads(record_data) if isinstance(record_data, str) else record_data
        except json.JSONDecodeError as e:
            return None, json.dumps({"error": f"Invalid JSON in record_data: {e}"})
        if not isinstance(data, dict):
            return None, json.dumps({"error": "record_data must be a JSON object."})
        return data, None

    def list_objects(self, include_custom: bool = True) -> str:
        """
        List all available Salesforce objects in the org.

        Args:
            include_custom: Include custom objects (ending in __c).

        Returns:
            str: JSON string with list of objects (name, label, queryable, createable).
        """
        log_debug("Listing Salesforce objects")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        try:
            describe = sf.describe()
            if not isinstance(describe, dict):
                return json.dumps({"error": "Unexpected response from Salesforce."})
            objects = describe.get("sobjects", [])

            result = []
            for obj in objects:
                name = obj.get("name", "")
                if not include_custom and name.endswith("__c"):
                    continue
                result.append(
                    {
                        "name": name,
                        "label": obj.get("label"),
                        "queryable": obj.get("queryable"),
                        "createable": obj.get("createable"),
                        "updateable": obj.get("updateable"),
                        "deletable": obj.get("deletable"),
                    }
                )

            total = len(result)
            if total > self.max_records:
                result = result[: self.max_records]

            return json.dumps({"total": total, "returned": len(result), "objects": result})
        except SalesforceError as e:
            logger.exception("Salesforce API error")
            return self._error(str(e))
        except Exception as e:
            logger.exception("Error listing objects")
            return self._error(str(e))

    def describe_object(self, sobject: str) -> str:
        """
        Get the schema/metadata for a Salesforce object.

        Returns field names, types, labels, and picklist values.

        Args:
            sobject: The API name of the object (e.g. ``Account``, ``Contact``,
                ``Custom_Object__c``).

        Returns:
            str: JSON string with object metadata including fields.
        """
        if not sobject:
            return json.dumps({"error": "sobject name is required."})

        log_debug(f"Describing Salesforce object: {sobject}")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        try:
            sf_object = getattr(sf, sobject)
            describe = sf_object.describe()

            all_fields = describe.get("fields", [])
            fields = []
            for field in all_fields[: self.max_fields]:
                field_info: Dict[str, Any] = {
                    "name": field.get("name"),
                    "label": field.get("label"),
                    "type": field.get("type"),
                    "required": not field.get("nillable", True) and field.get("createable", False),
                    "createable": field.get("createable"),
                    "updateable": field.get("updateable"),
                }
                picklist = field.get("picklistValues")
                if picklist:
                    field_info["picklistValues"] = [
                        {"value": p.get("value"), "label": p.get("label")} for p in picklist if p.get("active")
                    ]
                if field.get("type") == "reference":
                    field_info["referenceTo"] = field.get("referenceTo")
                fields.append(field_info)

            result: Dict[str, Any] = {
                "name": describe.get("name"),
                "label": describe.get("label"),
                "createable": describe.get("createable"),
                "updateable": describe.get("updateable"),
                "deletable": describe.get("deletable"),
                "totalFields": len(all_fields),
                "returnedFields": len(fields),
                "fields": fields,
            }

            return json.dumps(result)
        except SalesforceError as e:
            logger.exception("Salesforce API error")
            return self._error(str(e))
        except Exception as e:
            logger.exception(f"Error describing object {sobject}")
            return self._error(str(e))

    def get_record(
        self,
        sobject: str,
        record_id: str,
        fields: str = "",
    ) -> str:
        """
        Get a single Salesforce record by its ID.

        Args:
            sobject: The API name of the object (e.g. ``Account``, ``Contact``).
            record_id: The Salesforce record ID (18-char or 15-char).
            fields: Comma-separated list of fields to return.
                If empty, returns all fields.

        Returns:
            str: JSON string with the record data.
        """
        if not sobject or not record_id:
            return json.dumps({"error": "sobject and record_id are required."})

        log_debug(f"Getting Salesforce {sobject} record: {record_id}")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        try:
            sf_object = getattr(sf, sobject)
            if fields:
                field_list = fields.replace(" ", "")
                soql = f"SELECT {field_list} FROM {sobject} WHERE Id = '{record_id}'"
                result = sf.query(soql)
                records = result.get("records", [])
                if not records:
                    return json.dumps({"error": f"{sobject} record {record_id} not found."})
                return json.dumps(records[0])
            else:
                record = sf_object.get(record_id)
                return json.dumps(record)
        except SalesforceError as e:
            logger.exception("Salesforce API error")
            return self._error(str(e))
        except Exception as e:
            logger.exception(f"Error getting {sobject} record")
            return self._error(str(e))

    def create_record(self, sobject: str, record_data: str) -> str:
        """
        Create a new Salesforce record.

        Args:
            sobject: The API name of the object (e.g. ``Account``, ``Contact``).
            record_data: JSON string of field name-value pairs.
                Example: ``{"LastName": "Doe", "Email": "doe@example.com"}``

        Returns:
            str: JSON string with the created record ID and success status.
        """
        if not sobject or not record_data:
            return json.dumps({"error": "sobject and record_data are required."})

        log_debug(f"Creating Salesforce {sobject} record")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        data, err = self._parse_record_data(record_data)
        if err:
            return err

        try:
            sf_object = getattr(sf, sobject)
            result = sf_object.create(data)
            return json.dumps(
                {
                    "id": result.get("id"),
                    "success": result.get("success"),
                    "sobject": sobject,
                }
            )
        except SalesforceError as e:
            logger.exception("Salesforce API error")
            return self._error(str(e))
        except Exception as e:
            logger.exception(f"Error creating {sobject} record")
            return self._error(str(e))

    def update_record(self, sobject: str, record_id: str, record_data: str) -> str:
        """
        Update an existing Salesforce record.

        Args:
            sobject: The API name of the object (e.g. ``Account``, ``Contact``).
            record_id: The Salesforce record ID to update.
            record_data: JSON string of field name-value pairs to update.
                Example: ``{"Email": "new@example.com"}``

        Returns:
            str: JSON string indicating success or error.
        """
        if not sobject or not record_id or not record_data:
            return json.dumps({"error": "sobject, record_id, and record_data are required."})

        log_debug(f"Updating Salesforce {sobject} record: {record_id}")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        data, err = self._parse_record_data(record_data)
        if err:
            return err

        try:
            sf_object = getattr(sf, sobject)
            sf_object.update(record_id, data)
            return json.dumps(
                {
                    "status": "success",
                    "id": record_id,
                    "sobject": sobject,
                }
            )
        except SalesforceError as e:
            logger.exception("Salesforce API error")
            return self._error(str(e))
        except Exception as e:
            logger.exception(f"Error updating {sobject} record")
            return self._error(str(e))

    def delete_record(self, sobject: str, record_id: str) -> str:
        """
        Delete a Salesforce record.

        Args:
            sobject: The API name of the object (e.g. ``Account``, ``Contact``).
            record_id: The Salesforce record ID to delete.

        Returns:
            str: JSON string indicating success or error.
        """
        if not sobject or not record_id:
            return json.dumps({"error": "sobject and record_id are required."})

        log_debug(f"Deleting Salesforce {sobject} record: {record_id}")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        try:
            sf_object = getattr(sf, sobject)
            sf_object.delete(record_id)
            return json.dumps(
                {
                    "status": "success",
                    "id": record_id,
                    "sobject": sobject,
                }
            )
        except SalesforceError as e:
            logger.exception("Salesforce API error")
            return self._error(str(e))
        except Exception as e:
            logger.exception(f"Error deleting {sobject} record")
            return self._error(str(e))

    def query(self, soql: str) -> str:
        """
        Execute a SOQL query against Salesforce.

        Args:
            soql: The SOQL query string.
                Example: ``SELECT Id, Name FROM Account WHERE Industry = 'Technology' LIMIT 10``

        Returns:
            str: JSON string with query results (records and totalSize).
        """
        if not soql:
            return json.dumps({"error": "soql query string is required."})

        log_debug(f"Executing Salesforce SOQL: {soql}")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        try:
            result = sf.query(soql)
            records = result.get("records", [])
            total_size = result.get("totalSize", len(records))

            if len(records) > self.max_records:
                records = records[: self.max_records]

            return json.dumps(
                {
                    "totalSize": total_size,
                    "returned": len(records),
                    "done": result.get("done"),
                    "records": records,
                }
            )
        except SalesforceError as e:
            logger.exception("Salesforce SOQL error")
            return self._error(str(e))
        except Exception as e:
            logger.exception("Error executing SOQL")
            return self._error(str(e))

    def search(self, sosl: str) -> str:
        """
        Execute a SOSL full-text search across Salesforce objects.

        Args:
            sosl: The SOSL search string.
                Example: ``FIND {John} IN ALL FIELDS RETURNING Contact(Id, Name, Email), Lead(Id, Name)``

        Returns:
            str: JSON string with search results.
        """
        if not sosl:
            return json.dumps({"error": "sosl search string is required."})

        log_debug(f"Executing Salesforce SOSL: {sosl}")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        try:
            result = sf.search(sosl)
            records = result.get("searchRecords", []) if isinstance(result, dict) else []
            if len(records) > self.max_records:
                result["searchRecords"] = records[: self.max_records]
            return json.dumps(result)
        except SalesforceError as e:
            logger.exception("Salesforce SOSL error")
            return self._error(str(e))
        except Exception as e:
            logger.exception("Error executing SOSL")
            return self._error(str(e))

    def get_report(self, report_id: str) -> str:
        """
        Run a Salesforce report and return the results.

        Args:
            report_id: The Salesforce report ID (15 or 18 character).

        Returns:
            str: JSON string with report metadata and fact data.
        """
        if not report_id:
            return json.dumps({"error": "report_id is required."})

        log_debug(f"Running Salesforce report: {report_id}")

        sf = self._get_client()
        if sf is None:
            return json.dumps({"error": "Salesforce not connected."})

        try:
            # Reports are read-only via the Analytics API; standard REST objects don't expose them
            response = sf.restful(f"analytics/reports/{report_id}", method="GET")

            if not isinstance(response, dict):
                return json.dumps({"error": "Unexpected report response format."})

            result: Dict[str, Any] = {
                "reportMetadata": response.get("reportMetadata"),
                "factMap": response.get("factMap"),
            }

            return json.dumps(result)
        except SalesforceError as e:
            logger.exception("Salesforce report error")
            return self._error(str(e))
        except Exception as e:
            logger.exception(f"Error running report {report_id}")
            return self._error(str(e))
