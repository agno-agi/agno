import json
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

BASE_URL = "https://ah-api.merge.dev/api/v1"


class MergeAgentHandlerTools(Toolkit):
    """Toolkit for calling Merge Agent Handler tool packs through MCP."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        tool_pack_id: Optional[str] = None,
        registered_user_id: Optional[str] = None,
        environment: str = "production",
        enable_list_tool_packs: bool = True,
        enable_list_registered_users: bool = True,
        enable_list_tools: bool = True,
        enable_call_tool: bool = True,
        all: bool = False,
        timeout: float = 30.0,
        **kwargs,
    ):
        """
        Initialize Merge Agent Handler toolkit.

        Args:
            api_key: Merge Agent Handler API key. If not provided, uses MERGE_API_KEY environment variable.
            tool_pack_id: Default tool pack ID used by list_tools and call_tool.
            registered_user_id: Default registered user ID used by list_tools and call_tool.
            environment: Default environment used by list_registered_users. Must be "production" or "test".
            enable_list_tool_packs: Enable list_tool_packs tool.
            enable_list_registered_users: Enable list_registered_users tool.
            enable_list_tools: Enable list_tools tool.
            enable_call_tool: Enable call_tool tool.
            all: Enable all tools regardless of individual flags.
            timeout: HTTP timeout (seconds) for Merge API calls.
        """
        self.api_key = api_key or getenv("MERGE_API_KEY")
        if not self.api_key:
            raise ValueError("Merge API key is required. Provide api_key or set MERGE_API_KEY environment variable.")

        self.tool_pack_id = tool_pack_id
        self.registered_user_id = registered_user_id
        self.environment = environment

        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-Source": "agno-toolkit",
            },
        )

        tools: List[Any] = []
        if all or enable_list_tool_packs:
            tools.append(self.list_tool_packs)
        if all or enable_list_registered_users:
            tools.append(self.list_registered_users)
        if all or enable_list_tools:
            tools.append(self.list_tools)
        if all or enable_call_tool:
            tools.append(self.call_tool)

        super().__init__(name="merge_agent_handler_tools", tools=tools, **kwargs)

    def close(self) -> None:
        """Close the shared HTTP client."""
        self._client.close()

    def _resolve_environment(self, environment: Optional[str]) -> str:
        resolved_environment = (environment or self.environment or "production").strip().lower()
        if resolved_environment not in {"production", "test"}:
            raise ValueError("environment must be either 'production' or 'test'")
        return resolved_environment

    def _resolve_identifiers(
        self,
        tool_pack_id: Optional[str],
        registered_user_id: Optional[str],
    ) -> Tuple[str, str]:
        resolved_tool_pack_id = tool_pack_id or self.tool_pack_id
        resolved_registered_user_id = registered_user_id or self.registered_user_id

        if not resolved_tool_pack_id:
            raise ValueError("tool_pack_id is required. Pass it in __init__ or this tool call.")
        if not resolved_registered_user_id:
            raise ValueError("registered_user_id is required. Pass it in __init__ or this tool call.")

        return resolved_tool_pack_id, resolved_registered_user_id

    def _fetch_all_pages(self, path: str, params: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        all_results: List[Dict[str, Any]] = []
        page = 1
        query: Dict[str, str] = dict(params or {})

        while True:
            response = self._client.get(path, params={**query, "page": str(page)})
            response.raise_for_status()
            payload = response.json()

            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]

            if not isinstance(payload, dict):
                raise ValueError("Unexpected API response format.")

            results = payload.get("results", [])
            if not isinstance(results, list):
                raise ValueError("Unexpected API response format for `results`.")

            for result in results:
                if isinstance(result, dict):
                    all_results.append(result)

            if not payload.get("next"):
                break
            page += 1

        return all_results

    def _post_mcp(
        self,
        tool_pack_id: str,
        registered_user_id: str,
        rpc_request: Dict[str, Any],
    ) -> Dict[str, Any]:
        path = f"/tool-packs/{tool_pack_id}/registered-users/{registered_user_id}/mcp"
        response = self._client.post(path, json=rpc_request)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected MCP response format.")
        return payload

    def _parse_arguments(self, arguments: str) -> Dict[str, Any]:
        try:
            parsed_arguments = json.loads(arguments)
        except json.JSONDecodeError as e:
            raise ValueError("arguments must be a valid JSON string representing an object.") from e

        if parsed_arguments is None:
            return {}
        if not isinstance(parsed_arguments, dict):
            raise ValueError("arguments must decode to a JSON object.")

        return parsed_arguments

    def _extract_text(self, content: Any) -> str:
        if not isinstance(content, list):
            return ""
        text_chunks: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text_chunks.append(item["text"])
        return "\n".join(text_chunks).strip()

    def list_tool_packs(self) -> str:
        """List Merge tool packs available to the API key."""
        try:
            log_debug("Listing Merge tool packs")
            tool_packs = self._fetch_all_pages("/tool-packs/")
            normalized_tool_packs: List[Dict[str, Any]] = []

            for tool_pack in tool_packs:
                raw_connectors = tool_pack.get("connectors")
                connectors = raw_connectors if isinstance(raw_connectors, list) else []
                normalized_tool_packs.append(
                    {
                        "id": tool_pack.get("id"),
                        "name": tool_pack.get("name"),
                        "description": tool_pack.get("description"),
                        "connectors": [
                            {"name": connector.get("name"), "slug": connector.get("slug")}
                            for connector in connectors
                            if isinstance(connector, dict)
                        ],
                    }
                )

            return json.dumps(normalized_tool_packs)
        except Exception as e:
            logger.exception(e)
            return json.dumps({"error": str(e)})

    def list_registered_users(self, environment: Optional[str] = None) -> str:
        """List registered users filtered by environment (`production` or `test`)."""
        try:
            resolved_environment = self._resolve_environment(environment)
            is_test = resolved_environment == "test"
            users = self._fetch_all_pages("/registered-users", {"is_test": str(is_test).lower()})
            normalized_users: List[Dict[str, Any]] = []

            for user in users:
                normalized_users.append(
                    {
                        "id": user.get("id"),
                        "origin_user_id": user.get("origin_user_id"),
                        "origin_user_name": user.get("origin_user_name"),
                        "shared_credential_group": user.get("shared_credential_group"),
                        "user_type": user.get("user_type"),
                        "authenticated_connectors": user.get("authenticated_connectors"),
                        "is_test": user.get("is_test"),
                    }
                )

            return json.dumps(normalized_users)
        except Exception as e:
            logger.exception(e)
            return json.dumps({"error": str(e)})

    def list_tools(self, tool_pack_id: Optional[str] = None, registered_user_id: Optional[str] = None) -> str:
        """List MCP tools for a tool pack and registered user."""
        try:
            resolved_tool_pack_id, resolved_registered_user_id = self._resolve_identifiers(
                tool_pack_id=tool_pack_id, registered_user_id=registered_user_id
            )
            rpc_request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            response = self._post_mcp(resolved_tool_pack_id, resolved_registered_user_id, rpc_request)

            if "error" in response:
                error = response.get("error", {})
                if isinstance(error, dict):
                    return json.dumps(
                        {
                            "error": f"MCP tools/list failed: {error.get('message', 'Unknown error')}",
                            "code": error.get("code"),
                            "data": error.get("data"),
                        }
                    )
                return json.dumps({"error": "MCP tools/list failed: Unknown error"})

            tools = response.get("result", {}).get("tools", [])
            return json.dumps(tools)
        except Exception as e:
            logger.exception(e)
            return json.dumps({"error": str(e)})

    def call_tool(
        self,
        tool_name: str,
        arguments: str = "{}",
        tool_pack_id: Optional[str] = None,
        registered_user_id: Optional[str] = None,
    ) -> str:
        """Call an MCP tool in Merge Agent Handler."""
        try:
            resolved_tool_pack_id, resolved_registered_user_id = self._resolve_identifiers(
                tool_pack_id=tool_pack_id, registered_user_id=registered_user_id
            )
            parsed_arguments = self._parse_arguments(arguments)

            rpc_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": {"input": parsed_arguments},
                },
            }
            response = self._post_mcp(resolved_tool_pack_id, resolved_registered_user_id, rpc_request)

            if "error" in response:
                error = response.get("error", {})
                if isinstance(error, dict):
                    return json.dumps(
                        {
                            "error": f'Tool "{tool_name}" returned error: {error.get("message", "Unknown error")}',
                            "code": error.get("code"),
                            "data": error.get("data"),
                        }
                    )
                return json.dumps({"error": f'Tool "{tool_name}" returned error: Unknown error'})

            result = response.get("result")
            if not isinstance(result, dict):
                return json.dumps({"error": "MCP response was missing a result payload."})

            if result.get("isError"):
                error_text = self._extract_text(result.get("content")) or "Unknown error"
                return json.dumps({"error": f'Tool "{tool_name}" failed: {error_text}'})

            return json.dumps(result)
        except Exception as e:
            logger.exception(e)
            return json.dumps({"error": str(e)})
