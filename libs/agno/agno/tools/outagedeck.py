"""OutageDeck toolkit for vendor-published provider, incident, and service status.

OutageDeck (https://outagedeck.com) aggregates operational status and incident
history for infrastructure providers. Its public API does not require an API
key, so this toolkit works without setup or credentials.

API documentation:
https://outagedeck.com/docs/api?utm_source=agno&utm_medium=integration&utm_campaign=agno_toolkit
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install it via `pip install httpx`.")

from agno.tools import Toolkit
from agno.utils.log import log_info, logger

API_BASE_URL = "https://outagedeck.com/api/v1"
SITE_BASE_URL = "https://outagedeck.com"
USER_AGENT = "Agno-OutageDeck/1.0"
ATTRIBUTION_PARAMS = {
    "utm_source": "agno",
    "utm_medium": "integration",
    "utm_campaign": "agno_toolkit",
}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VALID_INCIDENT_STATES = {"active", "resolved"}
VALID_SEVERITIES = {"minor", "major", "critical", "maintenance"}


class OutageDeckTools(Toolkit):
    """Toolkit for checking vendor-published operational status through OutageDeck.

    Args:
        timeout (float): Per-request HTTP timeout in seconds. Default is 20.
        enable_provider_status (bool): Enable `get_provider_status`. Default is True.
        enable_incidents (bool): Enable `list_incidents`. Default is True.
        enable_service_status (bool): Enable `get_service_status`. Default is True.
        all (bool): Enable all tools regardless of individual flags. Default is False.
    """

    def __init__(
        self,
        timeout: float = 20.0,
        enable_provider_status: bool = True,
        enable_incidents: bool = True,
        enable_service_status: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.timeout = httpx.Timeout(timeout)

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []

        if all or enable_provider_status:
            tools.append(self.get_provider_status)
            async_tools.append((self.aget_provider_status, "get_provider_status"))
        if all or enable_incidents:
            tools.append(self.list_incidents)
            async_tools.append((self.alist_incidents, "list_incidents"))
        if all or enable_service_status:
            tools.append(self.get_service_status)
            async_tools.append((self.aget_service_status, "get_service_status"))

        name = kwargs.pop("name", "outagedeck_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    @staticmethod
    def _headers() -> Dict[str, str]:
        return {"Accept": "application/json", "User-Agent": USER_AGENT}

    @staticmethod
    def _slug(value: str, kind: str) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
        slug = value.strip().lower()
        if not SLUG_PATTERN.fullmatch(slug):
            return None, {"error": f"Invalid {kind} slug. Use lowercase letters, numbers, and single hyphens only."}
        return slug, None

    @staticmethod
    def _attributed_url(path: str) -> str:
        return f"{SITE_BASE_URL}{path}?{urlencode(ATTRIBUTION_PARAMS)}"

    @staticmethod
    def _http_error(exc: "httpx.HTTPStatusError", resource: str) -> Dict[str, str]:
        status = exc.response.status_code
        if status == 404:
            return {"error": f"OutageDeck could not find {resource}."}
        if status == 429:
            return {"error": "OutageDeck rate limit exceeded. Try again later."}
        if status in (401, 403):
            return {"error": "OutageDeck rejected the request."}
        return {"error": f"OutageDeck API error: HTTP {status}."}

    @staticmethod
    def _request_error(exc: Exception) -> Dict[str, str]:
        logger.exception("Error requesting OutageDeck")
        return {"error": f"Could not reach OutageDeck: {exc}"}

    @staticmethod
    def _response_error(exc: ValueError) -> Dict[str, str]:
        logger.exception("Invalid response from OutageDeck")
        return {"error": f"OutageDeck returned an invalid JSON response: {exc}"}

    @staticmethod
    def _data(payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    @classmethod
    def _incident(cls, incident: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(incident, dict):
            return None
        provider = incident.get("provider")
        affected_services = incident.get("affectedServices")
        slug = incident.get("slug")
        result = {
            "slug": slug,
            "title": incident.get("title"),
            "summary": incident.get("summary"),
            "status": incident.get("status"),
            "severity": incident.get("severity"),
            "started_at": incident.get("startedAt"),
            "updated_at": incident.get("updatedAt"),
            "resolved_at": incident.get("resolvedAt"),
            "provider": {
                "slug": provider.get("slug"),
                "name": provider.get("name"),
            }
            if isinstance(provider, dict)
            else None,
            "affected_services": [
                {"slug": service.get("slug"), "name": service.get("name")}
                for service in affected_services
                if isinstance(service, dict)
            ]
            if isinstance(affected_services, list)
            else [],
        }
        if isinstance(slug, str) and SLUG_PATTERN.fullmatch(slug):
            result["outagedeck_url"] = cls._attributed_url(f"/incidents/{slug}")
        return result

    @classmethod
    def _parse_provider(cls, payload: Any) -> Dict[str, Any]:
        data = cls._data(payload)
        if data is None:
            return {"error": "OutageDeck returned an unexpected provider response."}

        status = data.get("currentStatus")
        counts = data.get("counts")
        services = data.get("services")
        incidents = data.get("activeIncidents")
        slug = data.get("slug")
        if not isinstance(status, dict) or not isinstance(slug, str):
            return {"error": "OutageDeck returned an unexpected provider response."}

        return {
            "provider": {"slug": slug, "name": data.get("name")},
            "status": {
                "code": status.get("code"),
                "label": status.get("label"),
                "headline": status.get("headline"),
                "summary": status.get("summary"),
                "captured_at": status.get("capturedAt"),
            },
            "counts": counts if isinstance(counts, dict) else {},
            "services": [
                {
                    "slug": service.get("slug"),
                    "name": service.get("name"),
                    "category": service.get("category"),
                    "status": service.get("status"),
                    "summary": service.get("summary"),
                }
                for service in services
                if isinstance(service, dict)
            ]
            if isinstance(services, list)
            else [],
            "active_incidents": [parsed for item in incidents if (parsed := cls._incident(item)) is not None][:10]
            if isinstance(incidents, list)
            else [],
            "outagedeck_url": cls._attributed_url(f"/providers/{slug}"),
        }

    @classmethod
    def _parse_incidents(cls, payload: Any) -> Dict[str, Any]:
        data = cls._data(payload)
        if data is None or not isinstance(data.get("incidents"), list):
            return {"error": "OutageDeck returned an unexpected incident response."}

        incidents = [parsed for item in data["incidents"] if (parsed := cls._incident(item)) is not None]
        return {
            "count": data.get("count", len(incidents)),
            "page": data.get("page"),
            "total_pages": data.get("totalPages"),
            "total_incidents": data.get("totalIncidents"),
            "incidents": incidents,
            "outagedeck_url": cls._attributed_url("/incidents"),
        }

    @classmethod
    def _parse_service(cls, payload: Any) -> Dict[str, Any]:
        data = cls._data(payload)
        if data is None:
            return {"error": "OutageDeck returned an unexpected service response."}

        slug = data.get("slug")
        provider = data.get("provider")
        incidents = data.get("incidents")
        if not isinstance(slug, str) or not isinstance(provider, dict):
            return {"error": "OutageDeck returned an unexpected service response."}

        return {
            "service": {
                "slug": slug,
                "name": data.get("name"),
                "category": data.get("category"),
                "status": data.get("status"),
                "summary": data.get("summary"),
            },
            "provider": {"slug": provider.get("slug"), "name": provider.get("name")},
            "counts": data.get("counts") if isinstance(data.get("counts"), dict) else {},
            "recent_incidents": [parsed for item in incidents if (parsed := cls._incident(item)) is not None][:10]
            if isinstance(incidents, list)
            else [],
            "outagedeck_url": cls._attributed_url(f"/services/{slug}"),
        }

    def get_provider_status(self, provider_slug: str) -> Dict[str, Any]:
        """Get the current status, services, and active incidents for a provider.

        Args:
            provider_slug (str): OutageDeck provider slug, for example `github`, `openai`, or `cloudflare`.

        Returns:
            Dict[str, Any]: Current provider status and active incidents, or an error.
        """
        slug, invalid = self._slug(provider_slug, "provider")
        if invalid:
            return invalid
        log_info(f"Checking OutageDeck provider status: {slug}")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{API_BASE_URL}/providers/{slug}", headers=self._headers())
                response.raise_for_status()
                return self._parse_provider(response.json())
        except httpx.HTTPStatusError as exc:
            return self._http_error(exc, f"provider '{slug}'")
        except httpx.RequestError as exc:
            return self._request_error(exc)
        except ValueError as exc:
            return self._response_error(exc)

    async def aget_provider_status(self, provider_slug: str) -> Dict[str, Any]:
        """Get current provider status and active incidents asynchronously."""
        slug, invalid = self._slug(provider_slug, "provider")
        if invalid:
            return invalid
        log_info(f"Checking OutageDeck provider status: {slug}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{API_BASE_URL}/providers/{slug}", headers=self._headers())
                response.raise_for_status()
                return self._parse_provider(response.json())
        except httpx.HTTPStatusError as exc:
            return self._http_error(exc, f"provider '{slug}'")
        except httpx.RequestError as exc:
            return self._request_error(exc)
        except ValueError as exc:
            return self._response_error(exc)

    def list_incidents(
        self,
        provider: Optional[str] = None,
        state: Optional[str] = None,
        severity: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """List current or historical incidents, optionally filtered by provider.

        Args:
            provider (Optional[str]): Provider slug, such as `github` or `openai`.
            state (Optional[str]): Lifecycle filter: `active` or `resolved`.
            severity (Optional[str]): `minor`, `major`, `critical`, or `maintenance`.
            page (int): 1-based result page. Default is 1.
            limit (int): Results per page from 1 through 100. Default is 20.

        Returns:
            Dict[str, Any]: Paginated incidents and metadata, or an error.
        """
        params, invalid = self._incident_params(provider, state, severity, page, limit)
        if invalid:
            return invalid
        log_info("Listing OutageDeck incidents")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{API_BASE_URL}/incidents", params=params, headers=self._headers())
                response.raise_for_status()
                return self._parse_incidents(response.json())
        except httpx.HTTPStatusError as exc:
            return self._http_error(exc, "the requested incidents")
        except httpx.RequestError as exc:
            return self._request_error(exc)
        except ValueError as exc:
            return self._response_error(exc)

    async def alist_incidents(
        self,
        provider: Optional[str] = None,
        state: Optional[str] = None,
        severity: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """List incidents asynchronously with optional provider and lifecycle filters."""
        params, invalid = self._incident_params(provider, state, severity, page, limit)
        if invalid:
            return invalid
        log_info("Listing OutageDeck incidents")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{API_BASE_URL}/incidents", params=params, headers=self._headers())
                response.raise_for_status()
                return self._parse_incidents(response.json())
        except httpx.HTTPStatusError as exc:
            return self._http_error(exc, "the requested incidents")
        except httpx.RequestError as exc:
            return self._request_error(exc)
        except ValueError as exc:
            return self._response_error(exc)

    @classmethod
    def _incident_params(
        cls,
        provider: Optional[str],
        state: Optional[str],
        severity: Optional[str],
        page: int,
        limit: int,
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, str]]]:
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            return params, {"error": "Page must be an integer greater than or equal to 1."}
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            return params, {"error": "Limit must be an integer from 1 through 100."}
        if provider is not None:
            slug, invalid = cls._slug(provider, "provider")
            if invalid:
                return params, invalid
            params["provider"] = slug
        if state is not None:
            normalized_state = state.strip().lower()
            if normalized_state not in VALID_INCIDENT_STATES:
                return params, {"error": "State must be 'active' or 'resolved'."}
            params["state"] = normalized_state
        if severity is not None:
            normalized_severity = severity.strip().lower()
            if normalized_severity not in VALID_SEVERITIES:
                return params, {"error": "Severity must be 'minor', 'major', 'critical', or 'maintenance'."}
            params["severity"] = normalized_severity
        return params, None

    def get_service_status(self, service_slug: str) -> Dict[str, Any]:
        """Get current status and recent incidents for a provider service.

        Args:
            service_slug (str): OutageDeck service slug, for example `github-actions` or `openai-api`.

        Returns:
            Dict[str, Any]: Service status, provider, counts, and up to 10 recent incidents, or an error.
        """
        slug, invalid = self._slug(service_slug, "service")
        if invalid:
            return invalid
        log_info(f"Checking OutageDeck service status: {slug}")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{API_BASE_URL}/services/{slug}", headers=self._headers())
                response.raise_for_status()
                return self._parse_service(response.json())
        except httpx.HTTPStatusError as exc:
            return self._http_error(exc, f"service '{slug}'")
        except httpx.RequestError as exc:
            return self._request_error(exc)
        except ValueError as exc:
            return self._response_error(exc)

    async def aget_service_status(self, service_slug: str) -> Dict[str, Any]:
        """Get current service status and recent incidents asynchronously."""
        slug, invalid = self._slug(service_slug, "service")
        if invalid:
            return invalid
        log_info(f"Checking OutageDeck service status: {slug}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{API_BASE_URL}/services/{slug}", headers=self._headers())
                response.raise_for_status()
                return self._parse_service(response.json())
        except httpx.HTTPStatusError as exc:
            return self._http_error(exc, f"service '{slug}'")
        except httpx.RequestError as exc:
            return self._request_error(exc)
        except ValueError as exc:
            return self._response_error(exc)
