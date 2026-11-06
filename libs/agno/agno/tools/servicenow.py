import json
import re
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`.")

# Allowed table names: alphanumeric and underscores only
_TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Maximum response size to return to the agent (characters)
_MAX_RESPONSE_CHARS = 50_000


class ServiceNowTools(Toolkit):
    """
    A toolkit for interacting with the ServiceNow Table API.

    Supports ITSM operations including incidents, change requests,
    and generic table queries via ServiceNow's REST API.

    Requires:
        - ``requests`` library

    Environment variables:
        - ``SERVICENOW_INSTANCE``: The ServiceNow instance name (e.g. ``dev12345``)
        - ``SERVICENOW_USERNAME``: Username for basic auth
        - ``SERVICENOW_PASSWORD``: Password for basic auth
    """

    def __init__(
        self,
        instance: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        enable_get_incident: bool = True,
        enable_create_incident: bool = True,
        enable_update_incident: bool = True,
        enable_query_incidents: bool = True,
        enable_add_comment: bool = True,
        enable_get_change_request: bool = True,
        enable_create_change_request: bool = True,
        enable_query_table: bool = True,
        enable_get_user: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """
        Initialize ServiceNowTools.

        Args:
            instance: The ServiceNow instance name (e.g. ``dev12345``).
                Falls back to ``SERVICENOW_INSTANCE`` env var.
            username: Username for basic auth.
                Falls back to ``SERVICENOW_USERNAME`` env var.
            password: Password for basic auth.
                Falls back to ``SERVICENOW_PASSWORD`` env var.
            timeout: Request timeout in seconds.
            max_retries: Number of retries on transient failures (429, 502, 503, 504).
            enable_get_incident: Enable the get_incident function.
            enable_create_incident: Enable the create_incident function.
            enable_update_incident: Enable the update_incident function.
            enable_query_incidents: Enable the query_incidents function.
            enable_add_comment: Enable the add_comment function.
            enable_get_change_request: Enable the get_change_request function.
            enable_create_change_request: Enable the create_change_request function.
            enable_query_table: Enable the query_table function.
            enable_get_user: Enable the get_user function.
            all: Enable all functions.
        """
        self.instance = instance or getenv("SERVICENOW_INSTANCE")
        self.username = username or getenv("SERVICENOW_USERNAME")
        self.password = password or getenv("SERVICENOW_PASSWORD")

        # Normalize instance: strip protocol and domain suffix if provided
        if self.instance:
            self.instance = self.instance.replace("https://", "").replace("http://", "")
            if self.instance.endswith(".service-now.com"):
                self.instance = self.instance[: -len(".service-now.com")]
            self.instance = self.instance.strip("/")

        if not self.instance:
            logger.error("ServiceNow instance not provided. Set SERVICENOW_INSTANCE env var.")
        if not self.username or not self.password:
            logger.error(
                "ServiceNow credentials not provided. Set SERVICENOW_USERNAME and SERVICENOW_PASSWORD env vars."
            )

        self.base_url = f"https://{self.instance}.service-now.com/api/now/table" if self.instance else ""
        self.timeout = timeout

        # Use a session for connection reuse across multiple API calls
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})
        if self.username and self.password:
            self._session.auth = (self.username, self.password)

        # Retry on transient errors (rate limits, gateway errors)
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET", "PATCH", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)

        tools: List[Any] = []
        if all or enable_get_incident:
            tools.append(self.get_incident)
        if all or enable_create_incident:
            tools.append(self.create_incident)
        if all or enable_update_incident:
            tools.append(self.update_incident)
        if all or enable_query_incidents:
            tools.append(self.query_incidents)
        if all or enable_add_comment:
            tools.append(self.add_comment)
        if all or enable_get_change_request:
            tools.append(self.get_change_request)
        if all or enable_create_change_request:
            tools.append(self.create_change_request)
        if all or enable_query_table:
            tools.append(self.query_table)
        if all or enable_get_user:
            tools.append(self.get_user)

        super().__init__(name="servicenow_tools", tools=tools, **kwargs)

    def _validate_table_name(self, table: str) -> Optional[str]:
        """Validate a table name to prevent path traversal. Returns error string or None."""
        if not table or not _TABLE_NAME_RE.match(table):
            return f"Invalid table name: {table!r}. Must be alphanumeric with underscores."
        return None

    def _truncate(self, text: str) -> str:
        """Truncate response text to avoid blowing up agent context."""
        if len(text) > _MAX_RESPONSE_CHARS:
            return text[:_MAX_RESPONSE_CHARS] + "\n... [truncated]"
        return text

    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request to the ServiceNow API."""
        if not self.base_url:
            return {"error": "ServiceNow instance not configured."}

        if not self._session.auth:
            return {"error": "ServiceNow credentials not configured."}

        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "unknown"
            text = e.response.text if e.response is not None else str(e)
            logger.error(f"ServiceNow API HTTP error: {status_code} {text}")
            return {"error": f"HTTP {status_code}: {text}"}
        except requests.exceptions.Timeout:
            logger.error(f"ServiceNow API request timed out after {self.timeout}s: {method} {url}")
            return {"error": f"Request timed out after {self.timeout}s."}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"ServiceNow API connection error: {e}")
            return {"error": f"Connection error: {e}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"ServiceNow API request error: {e}")
            return {"error": str(e)}

    def get_incident(self, number: Optional[str] = None, sys_id: Optional[str] = None) -> str:
        """
        Retrieve a ServiceNow incident by number or sys_id.

        Args:
            number: The incident number (e.g. ``INC0010001``).
            sys_id: The sys_id of the incident record.

        Returns:
            str: JSON string with incident details.
        """
        if not number and not sys_id:
            return json.dumps({"error": "Provide either number or sys_id."})

        log_debug(f"Getting ServiceNow incident: number={number}, sys_id={sys_id}")

        if sys_id:
            url = f"{self.base_url}/incident/{sys_id}"
            result = self._make_request("GET", url)
        else:
            url = f"{self.base_url}/incident"
            result = self._make_request("GET", url, params={"sysparm_query": f"number={number}", "sysparm_limit": "1"})

        if "error" in result:
            return json.dumps(result)

        record = result.get("result")
        if isinstance(record, list):
            if not record:
                return json.dumps({"error": f"Incident {number} not found."})
            record = record[0]

        if not isinstance(record, dict):
            return json.dumps({"error": "Unexpected response format."})

        return json.dumps(
            {
                "sys_id": record.get("sys_id"),
                "number": record.get("number"),
                "short_description": record.get("short_description"),
                "description": record.get("description"),
                "state": record.get("state"),
                "priority": record.get("priority"),
                "urgency": record.get("urgency"),
                "impact": record.get("impact"),
                "category": record.get("category"),
                "assignment_group": record.get("assignment_group"),
                "assigned_to": record.get("assigned_to"),
                "caller_id": record.get("caller_id"),
                "opened_at": record.get("opened_at"),
                "resolved_at": record.get("resolved_at"),
                "closed_at": record.get("closed_at"),
            }
        )

    def create_incident(
        self,
        short_description: str,
        description: str = "",
        urgency: str = "2",
        impact: str = "2",
        category: str = "",
        assignment_group: str = "",
        caller_id: str = "",
    ) -> str:
        """
        Create a new incident in ServiceNow.

        Args:
            short_description: Brief summary of the incident.
            description: Detailed description of the incident.
            urgency: Urgency level (1=High, 2=Medium, 3=Low).
            impact: Impact level (1=High, 2=Medium, 3=Low).
            category: Incident category.
            assignment_group: The sys_id of the assignment group (preferred)
                or group name.
            caller_id: The sys_id of the caller (preferred) or user_name.

        Returns:
            str: JSON string with the created incident number and sys_id.
        """
        log_debug(f"Creating ServiceNow incident: {short_description}")

        payload: Dict[str, str] = {
            "short_description": short_description,
            "description": description,
            "urgency": urgency,
            "impact": impact,
        }
        if category:
            payload["category"] = category
        if assignment_group:
            payload["assignment_group"] = assignment_group
        if caller_id:
            payload["caller_id"] = caller_id

        url = f"{self.base_url}/incident"
        result = self._make_request("POST", url, data=payload)

        if "error" in result:
            return json.dumps(result)

        record = result.get("result", {})
        return json.dumps(
            {
                "sys_id": record.get("sys_id"),
                "number": record.get("number"),
                "short_description": record.get("short_description"),
                "state": record.get("state"),
            }
        )

    def update_incident(self, sys_id: str, **fields: str) -> str:
        """
        Update an existing incident in ServiceNow.

        Args:
            sys_id: The sys_id of the incident to update.
            **fields: Key-value pairs of fields to update.
                Common fields: state, urgency, impact, priority,
                assignment_group, assigned_to, short_description,
                work_notes, close_code, close_notes.

        Returns:
            str: JSON string with the updated incident details.
        """
        if not sys_id:
            return json.dumps({"error": "sys_id is required."})

        log_debug(f"Updating ServiceNow incident: {sys_id}")

        url = f"{self.base_url}/incident/{sys_id}"
        result = self._make_request("PATCH", url, data=dict(fields))

        if "error" in result:
            return json.dumps(result)

        record = result.get("result", {})
        return json.dumps(
            {
                "sys_id": record.get("sys_id"),
                "number": record.get("number"),
                "short_description": record.get("short_description"),
                "state": record.get("state"),
            }
        )

    def query_incidents(
        self,
        query: str = "",
        state: str = "",
        priority: str = "",
        assignment_group: str = "",
        limit: int = 20,
    ) -> str:
        """
        Query incidents from ServiceNow using encoded query syntax.

        Args:
            query: ServiceNow encoded query string
                (e.g. ``active=true^priority=1``).
            state: Filter by state (1=New, 2=In Progress, 3=On Hold,
                6=Resolved, 7=Closed).
            priority: Filter by priority (1=Critical, 2=High, 3=Moderate,
                4=Low, 5=Planning).
            assignment_group: Filter by assignment group name.
            limit: Maximum number of results to return.

        Returns:
            str: JSON string with a list of matching incidents.
        """
        log_debug(f"Querying ServiceNow incidents: query={query}")

        query_parts: List[str] = []
        if query:
            query_parts.append(query)
        if state:
            query_parts.append(f"state={state}")
        if priority:
            query_parts.append(f"priority={priority}")
        if assignment_group:
            query_parts.append(f"assignment_group.name={assignment_group}")

        encoded_query = "^".join(query_parts) if query_parts else "active=true"
        limit = min(limit, 200)  # Cap to prevent excessive data retrieval

        url = f"{self.base_url}/incident"
        params = {
            "sysparm_query": encoded_query,
            "sysparm_limit": str(limit),
            "sysparm_fields": "sys_id,number,short_description,state,priority,urgency,impact,assignment_group,assigned_to,opened_at",
        }

        result = self._make_request("GET", url, params=params)

        if "error" in result:
            return json.dumps(result)

        records = result.get("result", [])
        return self._truncate(json.dumps(records))

    def add_comment(self, sys_id: str, comment: str, is_work_note: bool = True) -> str:
        """
        Add a comment or work note to a ServiceNow incident.

        Args:
            sys_id: The sys_id of the incident.
            comment: The comment text to add.
            is_work_note: If True, adds as a work note (internal).
                If False, adds as a customer-visible comment.

        Returns:
            str: JSON string indicating success or error.
        """
        if not sys_id:
            return json.dumps({"error": "sys_id is required."})

        log_debug(f"Adding comment to ServiceNow incident: {sys_id}")

        field = "work_notes" if is_work_note else "comments"
        url = f"{self.base_url}/incident/{sys_id}"
        result = self._make_request("PATCH", url, data={field: comment})

        if "error" in result:
            return json.dumps(result)

        return json.dumps({"status": "success", "sys_id": sys_id, "field": field})

    def get_change_request(self, number: Optional[str] = None, sys_id: Optional[str] = None) -> str:
        """
        Retrieve a ServiceNow change request by number or sys_id.

        Args:
            number: The change request number (e.g. ``CHG0010001``).
            sys_id: The sys_id of the change request record.

        Returns:
            str: JSON string with change request details.
        """
        if not number and not sys_id:
            return json.dumps({"error": "Provide either number or sys_id."})

        log_debug(f"Getting ServiceNow change request: number={number}, sys_id={sys_id}")

        if sys_id:
            url = f"{self.base_url}/change_request/{sys_id}"
            result = self._make_request("GET", url)
        else:
            url = f"{self.base_url}/change_request"
            result = self._make_request("GET", url, params={"sysparm_query": f"number={number}", "sysparm_limit": "1"})

        if "error" in result:
            return json.dumps(result)

        record = result.get("result")
        if isinstance(record, list):
            if not record:
                return json.dumps({"error": f"Change request {number} not found."})
            record = record[0]

        if not isinstance(record, dict):
            return json.dumps({"error": "Unexpected response format."})

        return json.dumps(
            {
                "sys_id": record.get("sys_id"),
                "number": record.get("number"),
                "short_description": record.get("short_description"),
                "description": record.get("description"),
                "state": record.get("state"),
                "type": record.get("type"),
                "priority": record.get("priority"),
                "risk": record.get("risk"),
                "impact": record.get("impact"),
                "assignment_group": record.get("assignment_group"),
                "assigned_to": record.get("assigned_to"),
                "start_date": record.get("start_date"),
                "end_date": record.get("end_date"),
            }
        )

    def create_change_request(
        self,
        short_description: str,
        description: str = "",
        change_type: str = "normal",
        priority: str = "3",
        risk: str = "3",
        impact: str = "3",
        assignment_group: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> str:
        """
        Create a new change request in ServiceNow.

        Args:
            short_description: Brief summary of the change.
            description: Detailed description of the change.
            change_type: Change type (``normal``, ``standard``, ``emergency``).
            priority: Priority level (1=Critical, 2=High, 3=Moderate, 4=Low).
            risk: Risk level (1=High, 2=Moderate, 3=Low).
            impact: Impact level (1=High, 2=Medium, 3=Low).
            assignment_group: The sys_id of the assignment group.
            start_date: Planned start date (format: ``YYYY-MM-DD HH:MM:SS``).
            end_date: Planned end date (format: ``YYYY-MM-DD HH:MM:SS``).

        Returns:
            str: JSON string with the created change request number and sys_id.
        """
        log_debug(f"Creating ServiceNow change request: {short_description}")

        payload: Dict[str, str] = {
            "short_description": short_description,
            "description": description,
            "type": change_type,
            "priority": priority,
            "risk": risk,
            "impact": impact,
        }
        if assignment_group:
            payload["assignment_group"] = assignment_group
        if start_date:
            payload["start_date"] = start_date
        if end_date:
            payload["end_date"] = end_date

        url = f"{self.base_url}/change_request"
        result = self._make_request("POST", url, data=payload)

        if "error" in result:
            return json.dumps(result)

        record = result.get("result", {})
        return json.dumps(
            {
                "sys_id": record.get("sys_id"),
                "number": record.get("number"),
                "short_description": record.get("short_description"),
                "state": record.get("state"),
                "type": record.get("type"),
            }
        )

    def query_table(
        self,
        table: str,
        query: str = "active=true",
        limit: int = 20,
        fields: str = "",
    ) -> str:
        """
        Query any ServiceNow table using encoded query syntax.

        This is a generic method that works with any ServiceNow table
        (e.g. ``incident``, ``change_request``, ``problem``, ``cmdb_ci``,
        ``sc_request``, ``sys_user``).

        Args:
            table: The ServiceNow table name.
            query: Encoded query string (e.g. ``active=true^priority=1``).
            limit: Maximum number of results to return.
            fields: Comma-separated list of fields to return.
                If empty, returns all fields.

        Returns:
            str: JSON string with a list of matching records.
        """
        log_debug(f"Querying ServiceNow table {table}: query={query}")

        validation_error = self._validate_table_name(table)
        if validation_error:
            return json.dumps({"error": validation_error})

        url = f"{self.base_url}/{table}"
        limit = min(limit, 200)  # Cap to prevent excessive data retrieval
        params: Dict[str, str] = {
            "sysparm_query": query,
            "sysparm_limit": str(limit),
        }
        if fields:
            params["sysparm_fields"] = fields

        result = self._make_request("GET", url, params=params)

        if "error" in result:
            return json.dumps(result)

        records = result.get("result", [])
        return self._truncate(json.dumps(records))

    def get_user(self, user_name: Optional[str] = None, email: Optional[str] = None) -> str:
        """
        Look up a ServiceNow user by username or email.

        Args:
            user_name: The user's username.
            email: The user's email address.

        Returns:
            str: JSON string with user details.
        """
        if not user_name and not email:
            return json.dumps({"error": "Provide either user_name or email."})

        log_debug(f"Looking up ServiceNow user: user_name={user_name}, email={email}")

        query = f"user_name={user_name}" if user_name else f"email={email}"
        url = f"{self.base_url}/sys_user"
        params = {
            "sysparm_query": query,
            "sysparm_limit": "1",
            "sysparm_fields": "sys_id,user_name,email,first_name,last_name,title,department,active",
        }

        result = self._make_request("GET", url, params=params)

        if "error" in result:
            return json.dumps(result)

        records = result.get("result", [])
        if not records:
            return json.dumps({"error": "User not found."})

        return json.dumps(records[0])
