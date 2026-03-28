"""
Salesforce CRM tools for Agno agents.

Provides CRUD operations, SOQL queries, SOSL search, and metadata discovery
for any Salesforce object (standard or custom).
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

# Maximum response size to return to the agent (characters)
_MAX_RESPONSE_CHARS = 50_000

# Maximum records for query results
_MAX_QUERY_RECORDS = 200


class SalesforceTools(Toolkit):
    """
    A toolkit for interacting with Salesforce CRM via the REST API.

    Supports CRUD operations on any Salesforce object (standard or custom),
    SOQL queries, SOSL full-text search, and metadata discovery.

    Requires:
        - ``simple-salesforce`` library

    Environment variables:
        - ``SALESFORCE_USERNAME``: Salesforce username
        - ``SALESFORCE_PASSWORD``: Salesforce password
        - ``SALESFORCE_SECURITY_TOKEN``: Security token (from Salesforce settings)
        - ``SALESFORCE_DOMAIN``: ``login`` (production) or ``test`` (sandbox)
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        security_token: Optional[str] = None,
        domain: Optional[str] = None,
        instance_url: Optional[str] = None,
        session_id: Optional[str] = None,
        cache_metadata: bool = True,
        enable_list_objects: bool = True,
        enable_describe_object: bool = True,
        enable_get_record: bool = True,
        enable_create_record: bool = True,
        enable_update_record: bool = True,
        enable_delete_record: bool = True,
        enable_query: bool = True,
        enable_search: bool = True,
        enable_get_report: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize SalesforceTools.

        Args:
            username: Salesforce username. Falls back to ``SALESFORCE_USERNAME`` env var.
            password: Salesforce password. Falls back to ``SALESFORCE_PASSWORD`` env var.
            security_token: Security token. Falls back to ``SALESFORCE_SECURITY_TOKEN`` env var.
            domain: ``login`` for production, ``test`` for sandbox.
                Falls back to ``SALESFORCE_DOMAIN`` env var. Default: ``login``.
            instance_url: Direct instance URL (alternative to username/password auth).
            session_id: Session ID (alternative to username/password auth).
            cache_metadata: Cache object metadata to reduce API calls.
            enable_list_objects: Enable the list_objects function.
            enable_describe_object: Enable the describe_object function.
            enable_get_record: Enable the get_record function.
            enable_create_record: Enable the create_record function.
            enable_update_record: Enable the update_record function.
            enable_delete_record: Enable the delete_record function.
            enable_query: Enable the query function.
            enable_search: Enable the search function.
            enable_get_report: Enable the get_report function.
            all: Enable all functions.
        """
        self.username = username or getenv("SALESFORCE_USERNAME")
        self.password = password or getenv("SALESFORCE_PASSWORD")
        self.security_token = security_token or getenv("SALESFORCE_SECURITY_TOKEN")
        self.domain = domain or getenv("SALESFORCE_DOMAIN", "login")
        self.instance_url = instance_url
        self.session_id = session_id
        self.cache_metadata = cache_metadata

        # Metadata caches
        self._objects_cache: Optional[List[Dict[str, Any]]] = None
        self._describe_cache: Dict[str, Dict[str, Any]] = {}

        # Lazy connection
        self._sf: Optional[Salesforce] = None

        tools: List[Any] = []
        if all or enable_list_objects:
            tools.append(self.list_objects)
        if all or enable_describe_object:
            tools.append(self.describe_object)
        if all or enable_get_record:
            tools.append(self.get_record)
        if all or enable_create_record:
            tools.append(self.create_record)
        if all or enable_update_record:
            tools.append(self.update_record)
        if all or enable_delete_record:
            tools.append(self.delete_record)
        if all or enable_query:
            tools.append(self.query)
        if all or enable_search:
            tools.append(self.search)
        if all or enable_get_report:
            tools.append(self.get_report)

        super().__init__(name="salesforce_tools", tools=tools, **kwargs)

    def _get_client(self) -> Optional[Salesforce]:
        """Get or create the Salesforce client (lazy initialization)."""
        if self._sf is not None:
            return self._sf

        try:
            if self.instance_url and self.session_id:
                # Direct session auth
                self._sf = Salesforce(instance_url=self.instance_url, session_id=self.session_id)
            elif self.username and self.password:
                # Username/password auth
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
        except SalesforceAuthenticationFailed as e:
            logger.error(f"Salesforce authentication failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Salesforce connection error: {e}")
            return None

    def _truncate(self, text: str) -> str:
        """Truncate response text to avoid blowing up agent context."""
        if len(text) > _MAX_RESPONSE_CHARS:
            return text[:_MAX_RESPONSE_CHARS] + "\n... [truncated]"
        return text

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
            # Use cache if available
            if self.cache_metadata and self._objects_cache is not None:
                objects = self._objects_cache
            else:
                describe = sf.describe()
                if not isinstance(describe, dict):
                    return json.dumps({"error": "Unexpected response from Salesforce."})
                objects = describe.get("sobjects", [])
                if self.cache_metadata:
                    self._objects_cache = objects

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

            return self._truncate(json.dumps(result))
        except SalesforceError as e:
            logger.error(f"Salesforce API error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error listing objects: {e}")
            return json.dumps({"error": str(e)})

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
            # Use cache if available
            if self.cache_metadata and sobject in self._describe_cache:
                describe = self._describe_cache[sobject]
            else:
                sf_object = getattr(sf, sobject)
                describe = sf_object.describe()
                if self.cache_metadata:
                    self._describe_cache[sobject] = describe

            # Extract key field info
            fields = []
            for field in describe.get("fields", []):
                field_info: Dict[str, Any] = {
                    "name": field.get("name"),
                    "label": field.get("label"),
                    "type": field.get("type"),
                    "required": not field.get("nillable", True) and field.get("createable", False),
                    "createable": field.get("createable"),
                    "updateable": field.get("updateable"),
                }
                # Include picklist values if present
                picklist = field.get("picklistValues")
                if picklist:
                    field_info["picklistValues"] = [
                        {"value": p.get("value"), "label": p.get("label")} for p in picklist if p.get("active")
                    ]
                # Include reference info for lookup fields
                if field.get("type") == "reference":
                    field_info["referenceTo"] = field.get("referenceTo")
                fields.append(field_info)

            result = {
                "name": describe.get("name"),
                "label": describe.get("label"),
                "createable": describe.get("createable"),
                "updateable": describe.get("updateable"),
                "deletable": describe.get("deletable"),
                "fields": fields,
            }

            return self._truncate(json.dumps(result))
        except SalesforceError as e:
            logger.error(f"Salesforce API error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error describing object {sobject}: {e}")
            return json.dumps({"error": str(e)})

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
                # Use SOQL for field filtering
                field_list = fields.replace(" ", "")
                soql = f"SELECT {field_list} FROM {sobject} WHERE Id = '{record_id}'"
                result = sf.query(soql)
                records = result.get("records", [])
                if not records:
                    return json.dumps({"error": f"{sobject} record {record_id} not found."})
                return json.dumps(records[0])
            else:
                record = sf_object.get(record_id)
                return self._truncate(json.dumps(record))
        except SalesforceError as e:
            logger.error(f"Salesforce API error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error getting {sobject} record: {e}")
            return json.dumps({"error": str(e)})

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

        try:
            data = json.loads(record_data) if isinstance(record_data, str) else record_data
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in record_data: {e}"})

        if not isinstance(data, dict):
            return json.dumps({"error": "record_data must be a JSON object."})

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
            logger.error(f"Salesforce API error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error creating {sobject} record: {e}")
            return json.dumps({"error": str(e)})

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

        try:
            data = json.loads(record_data) if isinstance(record_data, str) else record_data
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in record_data: {e}"})

        if not isinstance(data, dict):
            return json.dumps({"error": "record_data must be a JSON object."})

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
            logger.error(f"Salesforce API error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error updating {sobject} record: {e}")
            return json.dumps({"error": str(e)})

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
            logger.error(f"Salesforce API error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error deleting {sobject} record: {e}")
            return json.dumps({"error": str(e)})

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

            # Cap records to prevent context overflow
            if len(records) > _MAX_QUERY_RECORDS:
                records = records[:_MAX_QUERY_RECORDS]

            return self._truncate(
                json.dumps(
                    {
                        "totalSize": result.get("totalSize"),
                        "done": result.get("done"),
                        "records": records,
                    }
                )
            )
        except SalesforceError as e:
            logger.error(f"Salesforce SOQL error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error executing SOQL: {e}")
            return json.dumps({"error": str(e)})

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
            return self._truncate(json.dumps(result))
        except SalesforceError as e:
            logger.error(f"Salesforce SOSL error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error executing SOSL: {e}")
            return json.dumps({"error": str(e)})

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
            # Use the Analytics API to run the report
            report_url = f"analytics/reports/{report_id}"
            response = sf.restful(report_url, method="GET")

            if not isinstance(response, dict):
                return json.dumps({"error": "Unexpected report response format."})

            # Extract key info
            result: Dict[str, Any] = {
                "reportMetadata": response.get("reportMetadata"),
                "factMap": response.get("factMap"),
            }

            return self._truncate(json.dumps(result))
        except SalesforceError as e:
            logger.error(f"Salesforce report error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error(f"Error running report {report_id}: {e}")
            return json.dumps({"error": str(e)})
