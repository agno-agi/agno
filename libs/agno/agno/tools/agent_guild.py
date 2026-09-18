from os import getenv
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from agno.tools import Toolkit

DEFAULT_BASE_URL = "https://agent-guild-5d5r.onrender.com"


class AgentGuildTools(Toolkit):
    """Tools for discovering, vetting, and verifying autonomous agents with Agent Guild.

    Agent Guild is a trust and settlement layer for AI agents. Read-only tools are
    enabled by default. Identity registration and free trial provisioning are
    opt-in because both create server-side state.

    Args:
        api_key: Agent Guild API key for metered trust reads. Uses
            ``AGENT_GUILD_API_KEY`` when omitted.
        base_url: Agent Guild API base URL.
        timeout: Per-request timeout in seconds.
        enable_check_agent: Register the capability-based trust check tool.
        enable_list_capabilities: Register the free supply and demand map tool.
        enable_get_passport: Register the free Agent Passport retrieval tool.
        enable_verify_passport: Register the free signed-passport verification tool.
        enable_register_agent: Register the identity-creation tool. Disabled by default.
        enable_request_trial: Register the free-trial provisioning tool. Disabled by default.
        all: Register all tools regardless of individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        enable_check_agent: bool = True,
        enable_list_capabilities: bool = True,
        enable_get_passport: bool = True,
        enable_verify_passport: bool = True,
        enable_register_agent: bool = False,
        enable_request_trial: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("AGENT_GUILD_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)

        tools: List[Any] = []
        async_tools: List[tuple] = []
        tool_pairs = [
            (all or enable_check_agent, self.check_agent, self.acheck_agent, "check_agent"),
            (
                all or enable_list_capabilities,
                self.list_capabilities,
                self.alist_capabilities,
                "list_capabilities",
            ),
            (all or enable_get_passport, self.get_passport, self.aget_passport, "get_passport"),
            (all or enable_verify_passport, self.verify_passport, self.averify_passport, "verify_passport"),
            (all or enable_register_agent, self.register_agent, self.aregister_agent, "register_agent"),
            (all or enable_request_trial, self.request_trial, self.arequest_trial, "request_trial"),
        ]
        for enabled, sync_tool, async_tool, name in tool_pairs:
            if enabled:
                tools.append(sync_tool)
                async_tools.append((async_tool, name))

        name = kwargs.pop("name", "agent_guild_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "agno-agent-guild/1.0",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    @staticmethod
    def _error(response: httpx.Response) -> Dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = {"detail": response.text}

        if response.status_code == 402:
            detail = body.get("detail", body) if isinstance(body, dict) else body
            accepts = detail.get("accepts", []) if isinstance(detail, dict) else []
            return {
                "error": "Agent Guild trust checks are metered",
                "status_code": 402,
                "detail": "Pass AGENT_GUILD_API_KEY or explicitly enable request_trial to get free evaluation credits.",
                "payment_options": accepts,
            }

        detail = body.get("detail", body) if isinstance(body, dict) else body
        return {
            "error": "Agent Guild API request failed",
            "status_code": response.status_code,
            "detail": detail,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers=self._headers(),
                    params=params,
                    json=json,
                )
                response.raise_for_status()
                result = response.json()
                return result if isinstance(result, dict) else {"result": result}
        except httpx.HTTPStatusError as error:
            return self._error(error.response)
        except httpx.RequestError as error:
            return {"error": "Agent Guild API request failed", "detail": str(error)}

    async def _arequest(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers=self._headers(),
                    params=params,
                    json=json,
                )
                response.raise_for_status()
                result = response.json()
                return result if isinstance(result, dict) else {"result": result}
        except httpx.HTTPStatusError as error:
            return self._error(error.response)
        except httpx.RequestError as error:
            return {"error": "Agent Guild API request failed", "detail": str(error)}

    def check_agent(self, capability: str, signed: bool = False, ttl_seconds: int = 3600) -> Dict[str, Any]:
        """Find the safest reachable agent for a capability using trust evidence.

        This is a metered read. It uses ``AGENT_GUILD_API_KEY`` when configured
        and otherwise returns the available payment or free-trial options without
        spending money.

        Args:
            capability: Capability required for the planned delegation.
            signed: Return an offline-verifiable signed AGD-1 decision.
            ttl_seconds: Signed-decision validity window, from 60 to 604800 seconds.
        """
        return self._request(
            "GET",
            "/check",
            params={"capability": capability, "signed": signed, "ttl_seconds": ttl_seconds},
        )

    async def acheck_agent(self, capability: str, signed: bool = False, ttl_seconds: int = 3600) -> Dict[str, Any]:
        """Asynchronously find the safest reachable agent for a capability."""
        return await self._arequest(
            "GET",
            "/check",
            params={"capability": capability, "signed": signed, "ttl_seconds": ttl_seconds},
        )

    def list_capabilities(self) -> Dict[str, Any]:
        """List supplied capabilities and unmet demand recorded by Agent Guild."""
        return self._request("GET", "/capabilities")

    async def alist_capabilities(self) -> Dict[str, Any]:
        """Asynchronously list supplied capabilities and unmet demand."""
        return await self._arequest("GET", "/capabilities")

    def get_passport(self, agent_id: str) -> Dict[str, Any]:
        """Fetch an agent's free, portable, Guild-signed reputation passport.

        Args:
            agent_id: Agent Guild identifier, for example ``agent_abc123``.
        """
        return self._request("GET", f"/agents/{quote(agent_id, safe='')}/passport")

    async def aget_passport(self, agent_id: str) -> Dict[str, Any]:
        """Asynchronously fetch an agent's signed reputation passport."""
        return await self._arequest("GET", f"/agents/{quote(agent_id, safe='')}/passport")

    def verify_passport(self, credential: Dict[str, Any]) -> Dict[str, Any]:
        """Verify a Guild-signed Agent Passport and retrieve live reputation.

        Args:
            credential: The complete Agent Passport credential object to verify.
        """
        return self._request("POST", "/credentials/verify", json=credential)

    async def averify_passport(self, credential: Dict[str, Any]) -> Dict[str, Any]:
        """Asynchronously verify an Agent Passport and retrieve live reputation."""
        return await self._arequest("POST", "/credentials/verify", json=credential)

    def register_agent(
        self,
        name: str,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        public_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a free Agent Guild identity and return its DID and API key.

        This tool creates server-side state and is disabled unless
        ``enable_register_agent=True`` or ``all=True`` is set.

        Args:
            name: Human- or agent-readable handle.
            capabilities: Capabilities this agent supplies.
            metadata: Optional discovery metadata such as an A2A endpoint.
            public_key: Optional Ed25519 public key in hexadecimal form.
        """
        body: Dict[str, Any] = {
            "name": name,
            "capabilities": capabilities or [],
            "metadata": metadata or {},
            "src": "agno_toolkit",
        }
        if public_key:
            body["public_key"] = public_key
        return self._request("POST", "/agents/register", json=body)

    async def aregister_agent(
        self,
        name: str,
        capabilities: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        public_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Asynchronously create a free Agent Guild identity."""
        body: Dict[str, Any] = {
            "name": name,
            "capabilities": capabilities or [],
            "metadata": metadata or {},
            "src": "agno_toolkit",
        }
        if public_key:
            body["public_key"] = public_key
        return await self._arequest("POST", "/agents/register", json=body)

    def request_trial(self) -> Dict[str, Any]:
        """Provision free evaluation credits and use the returned key for later reads.

        This tool creates a capped trial account but never starts a checkout or
        spends money. It is disabled unless ``enable_request_trial=True`` or
        ``all=True`` is set.
        """
        result = self._request("POST", "/billing/trial")
        if isinstance(result.get("key"), str):
            self.api_key = result["key"]
        return result

    async def arequest_trial(self) -> Dict[str, Any]:
        """Asynchronously provision free evaluation credits for later reads."""
        result = await self._arequest("POST", "/billing/trial")
        if isinstance(result.get("key"), str):
            self.api_key = result["key"]
        return result
