import json
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger


class N8nTools(Toolkit):
    def __init__(
        self,
        base_url: str = "http://localhost:5678",
        api_key: Optional[str] = None,
        timeout: int = 30,
        all: bool = False,
        enable_list_workflows: bool = True,
        enable_get_workflow: bool = True,
        enable_activate_workflow: bool = True,
        enable_deactivate_workflow: bool = True,
        enable_list_executions: bool = True,
        enable_get_execution: bool = True,
        enable_delete_execution: bool = True,
        **kwargs: Any,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or getenv("N8N_API_KEY")
        if not self.api_key:
            logger.warning("No n8n API key provided. Set N8N_API_KEY or pass api_key.")
        self.timeout = timeout
        self._async_client: Optional[httpx.AsyncClient] = None

        tools: List[Any] = []
        async_tools: List[tuple[Any, str]] = []

        if all or enable_list_workflows:
            tools.append(self.list_workflows)
            async_tools.append((self.alist_workflows, "list_workflows"))
        if all or enable_get_workflow:
            tools.append(self.get_workflow)
            async_tools.append((self.aget_workflow, "get_workflow"))
        if all or enable_activate_workflow:
            tools.append(self.activate_workflow)
            async_tools.append((self.aactivate_workflow, "activate_workflow"))
        if all or enable_deactivate_workflow:
            tools.append(self.deactivate_workflow)
            async_tools.append((self.adeactivate_workflow, "deactivate_workflow"))
        if all or enable_list_executions:
            tools.append(self.list_executions)
            async_tools.append((self.alist_executions, "list_executions"))
        if all or enable_get_execution:
            tools.append(self.get_execution)
            async_tools.append((self.aget_execution, "get_execution"))
        if all or enable_delete_execution:
            tools.append(self.delete_execution)
            async_tools.append((self.adelete_execution, "delete_execution"))

        super().__init__(name="n8n", tools=tools, async_tools=async_tools, **kwargs)

    # ---- Internal helpers ----

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers for n8n API requests."""
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["X-N8N-API-KEY"] = self.api_key
        return headers

    def _build_url(self, endpoint: str) -> str:
        """Build full URL for the given n8n API endpoint."""
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{self.base_url}/api/v1{path}"

    def _json_error(self, message: str) -> str:
        """Return a JSON-encoded error string."""
        return json.dumps({"error": message})

    def _http_error_message(self, response: httpx.Response) -> str:
        """Extract a human-readable error message from an HTTP response."""
        detail: Optional[str] = None
        try:
            payload = response.json()
            if isinstance(payload, dict):
                msg = payload.get("message") or payload.get("error")
                if msg is not None:
                    detail = json.dumps(msg) if isinstance(msg, (dict, list)) else str(msg)
            elif isinstance(payload, list):
                detail = json.dumps(payload)
        except Exception:
            detail = None

        if not detail:
            raw_text = response.text.strip()
            detail = raw_text or response.reason_phrase or "HTTP error"
        return f"{response.status_code}: {detail}"

    def _get_async_client(self) -> httpx.AsyncClient:
        """Return a lazily-initialized async HTTP client."""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client

    async def aclose(self) -> None:
        """Close the async HTTP client and release resources."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    # ---- Sync methods ----

    def list_workflows(self, active_only: bool = False, limit: int = 100, cursor: Optional[str] = None) -> str:
        """List workflows in the n8n instance.

        Args:
            active_only: If True, return only active workflows.
            limit: Maximum number of workflows to return.
            cursor: Pagination cursor from a previous response.

        Returns:
            JSON string containing workflow data, count, and nextCursor.
        """
        try:
            params: Dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            log_debug(f"Listing n8n workflows (active_only={active_only})")
            response = httpx.get(
                self._build_url("/workflows"),
                headers=self._build_headers(),
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            next_cursor = data.get("nextCursor") if isinstance(data, dict) else None
            workflows = data.get("data", data) if isinstance(data, dict) else data
            if active_only and isinstance(workflows, list):
                workflows = [w for w in workflows if w.get("active")]
            return json.dumps({"data": workflows, "count": len(workflows), "nextCursor": next_cursor}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while listing workflows: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while listing workflows: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error while listing n8n workflows")
            return self._json_error(str(e))

    def get_workflow(self, workflow_id: str) -> str:
        """Get details of a specific workflow.

        Args:
            workflow_id: The ID of the workflow to retrieve.

        Returns:
            JSON string containing workflow details.
        """
        try:
            log_debug(f"Getting n8n workflow: {workflow_id}")
            response = httpx.get(
                self._build_url(f"/workflows/{workflow_id}"),
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while getting workflow {workflow_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while getting workflow {workflow_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting n8n workflow {workflow_id}")
            return self._json_error(str(e))

    def activate_workflow(self, workflow_id: str) -> str:
        """Activate a workflow so it can be triggered.

        Args:
            workflow_id: The ID of the workflow to activate.

        Returns:
            JSON string confirming activation.
        """
        try:
            log_debug(f"Activating n8n workflow: {workflow_id}")
            response = httpx.post(
                self._build_url(f"/workflows/{workflow_id}/activate"),
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while activating workflow {workflow_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while activating workflow {workflow_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while activating n8n workflow {workflow_id}")
            return self._json_error(str(e))

    def deactivate_workflow(self, workflow_id: str) -> str:
        """Deactivate a workflow so it stops being triggered.

        Args:
            workflow_id: The ID of the workflow to deactivate.

        Returns:
            JSON string confirming deactivation.
        """
        try:
            log_debug(f"Deactivating n8n workflow: {workflow_id}")
            response = httpx.post(
                self._build_url(f"/workflows/{workflow_id}/deactivate"),
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while deactivating workflow {workflow_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while deactivating workflow {workflow_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while deactivating n8n workflow {workflow_id}")
            return self._json_error(str(e))

    def list_executions(self, workflow_id: Optional[str] = None, limit: int = 20, cursor: Optional[str] = None) -> str:
        """List workflow executions.

        Args:
            workflow_id: Optional workflow ID to filter executions.
            limit: Maximum number of executions to return.
            cursor: Pagination cursor from a previous response.

        Returns:
            JSON string containing execution data, count, and nextCursor.
        """
        try:
            params: Dict[str, Any] = {"limit": limit}
            if workflow_id:
                params["workflowId"] = workflow_id
            if cursor:
                params["cursor"] = cursor
            log_debug(f"Listing n8n executions with params: {params}")
            response = httpx.get(
                self._build_url("/executions"),
                headers=self._build_headers(),
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            next_cursor = data.get("nextCursor") if isinstance(data, dict) else None
            executions = data.get("data", data) if isinstance(data, dict) else data
            return json.dumps({"data": executions, "count": len(executions), "nextCursor": next_cursor}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while listing executions: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while listing executions: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error while listing n8n executions")
            return self._json_error(str(e))

    def get_execution(self, execution_id: str) -> str:
        """Get details of a specific execution.

        Args:
            execution_id: The ID of the execution to retrieve.

        Returns:
            JSON string containing execution details.
        """
        try:
            log_debug(f"Getting n8n execution: {execution_id}")
            response = httpx.get(
                self._build_url(f"/executions/{execution_id}"),
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while getting execution {execution_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while getting execution {execution_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting n8n execution {execution_id}")
            return self._json_error(str(e))

    def delete_execution(self, execution_id: str) -> str:
        """Delete a specific execution record.

        Args:
            execution_id: The ID of the execution to delete.

        Returns:
            JSON string confirming deletion.
        """
        try:
            log_debug(f"Deleting n8n execution: {execution_id}")
            response = httpx.delete(
                self._build_url(f"/executions/{execution_id}"),
                headers=self._build_headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()
            return json.dumps({"status": "deleted", "execution_id": execution_id}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while deleting execution {execution_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while deleting execution {execution_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while deleting n8n execution {execution_id}")
            return self._json_error(str(e))

    # ---- Async methods ----

    async def alist_workflows(self, active_only: bool = False, limit: int = 100, cursor: Optional[str] = None) -> str:
        """List workflows in the n8n instance using async HTTP requests.

        Args:
            active_only: If True, return only active workflows.
            limit: Maximum number of workflows to return.
            cursor: Pagination cursor from a previous response.

        Returns:
            JSON string containing workflow data, count, and nextCursor.
        """
        try:
            params: Dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            log_debug(f"Listing n8n workflows async (active_only={active_only})")
            client = self._get_async_client()
            response = await client.get(
                self._build_url("/workflows"),
                headers=self._build_headers(),
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            next_cursor = data.get("nextCursor") if isinstance(data, dict) else None
            workflows = data.get("data", data) if isinstance(data, dict) else data
            if active_only and isinstance(workflows, list):
                workflows = [w for w in workflows if w.get("active")]
            return json.dumps({"data": workflows, "count": len(workflows), "nextCursor": next_cursor}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while listing workflows: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while listing workflows: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error while listing n8n workflows")
            return self._json_error(str(e))

    async def aget_workflow(self, workflow_id: str) -> str:
        """Get details of a specific workflow using async HTTP requests.

        Args:
            workflow_id: The ID of the workflow to retrieve.

        Returns:
            JSON string containing workflow details.
        """
        try:
            log_debug(f"Getting n8n workflow async: {workflow_id}")
            client = self._get_async_client()
            response = await client.get(
                self._build_url(f"/workflows/{workflow_id}"),
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while getting workflow {workflow_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while getting workflow {workflow_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting n8n workflow {workflow_id}")
            return self._json_error(str(e))

    async def aactivate_workflow(self, workflow_id: str) -> str:
        """Activate a workflow using async HTTP requests.

        Args:
            workflow_id: The ID of the workflow to activate.

        Returns:
            JSON string confirming activation.
        """
        try:
            log_debug(f"Activating n8n workflow async: {workflow_id}")
            client = self._get_async_client()
            response = await client.post(
                self._build_url(f"/workflows/{workflow_id}/activate"),
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while activating workflow {workflow_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while activating workflow {workflow_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while activating n8n workflow {workflow_id}")
            return self._json_error(str(e))

    async def adeactivate_workflow(self, workflow_id: str) -> str:
        """Deactivate a workflow using async HTTP requests.

        Args:
            workflow_id: The ID of the workflow to deactivate.

        Returns:
            JSON string confirming deactivation.
        """
        try:
            log_debug(f"Deactivating n8n workflow async: {workflow_id}")
            client = self._get_async_client()
            response = await client.post(
                self._build_url(f"/workflows/{workflow_id}/deactivate"),
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while deactivating workflow {workflow_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while deactivating workflow {workflow_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while deactivating n8n workflow {workflow_id}")
            return self._json_error(str(e))

    async def alist_executions(
        self, workflow_id: Optional[str] = None, limit: int = 20, cursor: Optional[str] = None
    ) -> str:
        """List workflow executions using async HTTP requests.

        Args:
            workflow_id: Optional workflow ID to filter executions.
            limit: Maximum number of executions to return.
            cursor: Pagination cursor from a previous response.

        Returns:
            JSON string containing execution data, count, and nextCursor.
        """
        try:
            params: Dict[str, Any] = {"limit": limit}
            if workflow_id:
                params["workflowId"] = workflow_id
            if cursor:
                params["cursor"] = cursor
            log_debug(f"Listing n8n executions async with params: {params}")
            client = self._get_async_client()
            response = await client.get(
                self._build_url("/executions"),
                headers=self._build_headers(),
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            next_cursor = data.get("nextCursor") if isinstance(data, dict) else None
            executions = data.get("data", data) if isinstance(data, dict) else data
            return json.dumps({"data": executions, "count": len(executions), "nextCursor": next_cursor}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while listing executions: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while listing executions: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error while listing n8n executions")
            return self._json_error(str(e))

    async def aget_execution(self, execution_id: str) -> str:
        """Get details of a specific execution using async HTTP requests.

        Args:
            execution_id: The ID of the execution to retrieve.

        Returns:
            JSON string containing execution details.
        """
        try:
            log_debug(f"Getting n8n execution async: {execution_id}")
            client = self._get_async_client()
            response = await client.get(
                self._build_url(f"/executions/{execution_id}"),
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while getting execution {execution_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while getting execution {execution_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting n8n execution {execution_id}")
            return self._json_error(str(e))

    async def adelete_execution(self, execution_id: str) -> str:
        """Delete a specific execution record using async HTTP requests.

        Args:
            execution_id: The ID of the execution to delete.

        Returns:
            JSON string confirming deletion.
        """
        try:
            log_debug(f"Deleting n8n execution async: {execution_id}")
            client = self._get_async_client()
            response = await client.delete(
                self._build_url(f"/executions/{execution_id}"),
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return json.dumps({"status": "deleted", "execution_id": execution_id}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            logger.error(f"n8n API error while deleting execution {execution_id}: {message}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.error(f"n8n request error while deleting execution {execution_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while deleting n8n execution {execution_id}")
            return self._json_error(str(e))
