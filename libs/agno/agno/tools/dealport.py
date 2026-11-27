"""Cited US private company, commercial building, and verified owner tools for Dealport."""

import json
import math
import re
from os import getenv
from typing import Any, Optional
from urllib.parse import quote, urlsplit

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error

DEFAULT_BASE_URL = "https://app.dealport.com/api/v1"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
SAFE_RECORD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
VALID_BOROUGHS = {"MN", "BK", "QN", "BX", "SI"}
VALID_LOAN_HOLDERS = {"agency", "cmbs", "bank"}
VALID_SIGNALS = {
    "rent_stabilized",
    "dob_penalties",
    "housing_court",
    "tax_lien",
    "ll97",
    "section8_expiring",
    "tax_credit_ending",
    "failing_inspection",
}


def _split_csv(value: Optional[str]) -> Optional[list[str]]:
    if not value or not value.strip():
        return None
    items = [part.strip() for part in value.split(",") if part.strip()]
    return items or None


def _clean_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None and v != "" and v != []}


class DealportTools(Toolkit):
    """Query Dealport's 28M+ US private companies, commercial buildings, and verified owners.

    Set DEALPORT_API_KEY or pass api_key (`dp_live_...`). Start new searches with
    preview_companies ($0.00) before unlocking paid company or building Records.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        enable_preview_companies: bool = True,
        enable_search_companies: bool = True,
        enable_search_buildings: bool = True,
        enable_get_record: bool = True,
        enable_find_owner: bool = True,
        enable_find_contact: bool = True,
        enable_match_company_list: bool = True,
        enable_get_balance: bool = True,
        all: bool = False,
        **kwargs: Any,
    ):
        """Configure Dealport authentication, endpoint bounds, and registered sync/async tools."""
        resolved_key = api_key if api_key is not None else getenv("DEALPORT_API_KEY", "")
        if not resolved_key.strip():
            raise ValueError("Provide api_key or set DEALPORT_API_KEY")
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")

        parsed = urlsplit(base_url.strip())
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.scheme not in {"http", "https"}
            or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError("base_url must be HTTPS, or HTTP on loopback, without credentials or query")

        self.api_key: str = resolved_key.strip()
        self.base_url: str = base_url.strip().rstrip("/")
        self.timeout: float = float(timeout)

        tools: list[Any] = []
        async_tools: list[tuple[Any, str]] = []
        if all or enable_preview_companies:
            tools.append(self.preview_companies)
            async_tools.append((self.apreview_companies, "preview_companies"))
        if all or enable_search_companies:
            tools.append(self.search_companies)
            async_tools.append((self.asearch_companies, "search_companies"))
        if all or enable_search_buildings:
            tools.append(self.search_buildings)
            async_tools.append((self.asearch_buildings, "search_buildings"))
        if all or enable_get_record:
            tools.append(self.get_record)
            async_tools.append((self.aget_record, "get_record"))
        if all or enable_find_owner:
            tools.append(self.find_owner)
            async_tools.append((self.afind_owner, "find_owner"))
        if all or enable_find_contact:
            tools.append(self.find_contact)
            async_tools.append((self.afind_contact, "find_contact"))
        if all or enable_match_company_list:
            tools.append(self.match_company_list)
            async_tools.append((self.amatch_company_list, "match_company_list"))
        if all or enable_get_balance:
            tools.append(self.get_balance)
            async_tools.append((self.aget_balance, "get_balance"))

        super().__init__(
            name="dealport_tools",
            tools=tools,
            async_tools=async_tools,
            timeout=math.ceil(self.timeout),
            **kwargs,
        )
        self.timeout = float(timeout)

    def _headers(self, has_json: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "agno-dealport-tools/1.0",
        }
        if has_json:
            headers["Content-Type"] = "application/json"
        return headers

    def _log_failure(self, operation: str, error: Exception) -> None:
        if isinstance(error, (httpx.HTTPError, OSError)):
            detail = "network request failed"
        elif isinstance(error, json.JSONDecodeError):
            detail = f"invalid JSON at line {error.lineno}, column {error.colno}"
        else:
            detail = str(error).replace(self.api_key, "[REDACTED]")[:500]
        log_error(f"Dealport {operation} failed ({type(error).__name__}): {detail}", exc_info=False)

    def _parse_response(self, status_code: int, raw: bytes) -> str:
        if 300 <= status_code < 400:
            raise ValueError(f"Dealport returned unexpected redirect (HTTP {status_code})")
        payload: Any = json.loads(raw.decode("utf-8")) if raw else {}
        if not 200 <= status_code < 300:
            detail = ""
            if isinstance(payload, dict):
                err = payload.get("error") or payload.get("message") or payload.get("detail")
                if isinstance(err, dict):
                    detail = str(err.get("message") or err.get("code") or "")
                elif err:
                    detail = str(err)
            clean_detail = detail.replace(self.api_key, "[REDACTED]")[:300]
            suffix = f": {clean_detail}" if clean_detail else ""
            raise ValueError(f"Dealport HTTP {status_code}{suffix}")
        if not isinstance(payload, dict):
            raise TypeError("Dealport returned a non-object JSON payload")
        return json.dumps(payload)

    def _request_sync(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> str:
        with httpx.stream(
            method,
            f"{self.base_url}{path}",
            headers=self._headers(has_json=json_body is not None),
            params=_clean_dict(params) if params else None,
            json=_clean_dict(json_body) if json_body is not None else None,
            timeout=self.timeout,
            follow_redirects=False,
        ) as response:
            buf = bytearray()
            for chunk in response.iter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_RESPONSE_BYTES:
                    raise ValueError("Dealport response exceeded maximum size")
            return self._parse_response(response.status_code, bytes(buf))

    async def _request_async(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> str:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            async with client.stream(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(has_json=json_body is not None),
                params=_clean_dict(params) if params else None,
                json=_clean_dict(json_body) if json_body is not None else None,
            ) as response:
                buf = bytearray()
                async for chunk in response.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > MAX_RESPONSE_BYTES:
                        raise ValueError("Dealport response exceeded maximum size")
                return self._parse_response(response.status_code, bytes(buf))

    def _build_preview_payload(
        self,
        q: Optional[str],
        state: Optional[str],
        cities: Optional[str],
        counties: Optional[str],
        naics: Optional[str],
        domain: Optional[str],
        min_employees: Optional[int],
        max_employees: Optional[int],
        min_revenue: Optional[float],
        max_revenue: Optional[float],
        independent: Optional[bool],
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        norm_state = state.strip().upper() if state else None
        if norm_state and len(norm_state) != 2:
            return None, json.dumps({"error": "state must be a two-letter US state code"})
        return (
            {
                "q": q.strip() if q else None,
                "state": norm_state,
                "cities": _split_csv(cities),
                "counties": _split_csv(counties),
                "naics": _split_csv(naics),
                "domain": domain.strip() if domain else None,
                "min_employees": min_employees,
                "max_employees": max_employees,
                "min_revenue": min_revenue,
                "max_revenue": max_revenue,
                "independent": independent,
            },
            None,
        )

    def _build_company_search_params(
        self,
        q: Optional[str],
        state: Optional[str],
        cities: Optional[str],
        counties: Optional[str],
        naics: Optional[str],
        domain: Optional[str],
        min_employees: Optional[int],
        max_employees: Optional[int],
        min_revenue: Optional[float],
        max_revenue: Optional[float],
        independent: Optional[bool],
        limit: int,
        cursor: Optional[str],
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        norm_state = state.strip().upper() if state else None
        if norm_state and len(norm_state) != 2:
            return None, json.dumps({"error": "state must be a two-letter US state code"})
        if isinstance(limit, bool) or limit < 1 or limit > 50:
            return None, json.dumps({"error": "limit must be between 1 and 50"})
        return (
            {
                "q": q.strip() if q else None,
                "state": norm_state,
                "cities": cities.strip() if cities else None,
                "counties": counties.strip() if counties else None,
                "naics": naics.strip() if naics else None,
                "domain": domain.strip() if domain else None,
                "min_employees": min_employees,
                "max_employees": max_employees,
                "min_revenue": min_revenue,
                "max_revenue": max_revenue,
                "independent": independent,
                "limit": limit,
                "cursor": cursor.strip() if cursor else None,
            },
            None,
        )

    def _build_building_params(
        self,
        borough: str,
        min_units: int,
        q: Optional[str],
        loan_due_by: Optional[int],
        loan_holder: Optional[str],
        signal: Optional[str],
        limit: int,
        cursor: Optional[str],
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        norm_borough = borough.strip().upper() if borough else ""
        if norm_borough not in VALID_BOROUGHS:
            return None, json.dumps({"error": "borough must be one of MN, BK, QN, BX, or SI"})
        norm_holder = loan_holder.strip().lower() if loan_holder else None
        if norm_holder and norm_holder not in VALID_LOAN_HOLDERS:
            return None, json.dumps({"error": "loan_holder must be one of agency, cmbs, or bank"})
        norm_signal = signal.strip().lower() if signal else None
        if norm_signal and norm_signal not in VALID_SIGNALS:
            return None, json.dumps({"error": "invalid signal value"})
        if isinstance(limit, bool) or limit < 1 or limit > 50:
            return None, json.dumps({"error": "limit must be between 1 and 50"})
        return (
            {
                "borough": norm_borough,
                "min_units": min_units,
                "q": q.strip() if q else None,
                "loan_due_by": loan_due_by,
                "loan_holder": norm_holder,
                "signal": norm_signal,
                "limit": limit,
                "cursor": cursor.strip() if cursor else None,
            },
            None,
        )

    def _build_match_body(
        self,
        csv: Optional[str],
        items_json: Optional[str],
    ) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        csv_clean = csv.strip() if csv else ""
        items_clean = items_json.strip() if items_json else ""
        if not csv_clean and not items_clean:
            return None, json.dumps({"error": "provide either csv or items_json"})
        body: dict[str, Any] = {"watch": False}
        if items_clean:
            try:
                parsed = json.loads(items_clean)
            except json.JSONDecodeError:
                return None, json.dumps({"error": "items_json must be valid JSON"})
            if (
                not isinstance(parsed, list)
                or not parsed
                or len(parsed) > 250
                or not all(isinstance(row, dict) for row in parsed)
            ):
                return None, json.dumps({"error": "items_json must be an array of 1 to 250 JSON objects"})
            body["items"] = parsed
        else:
            body["csv"] = csv_clean
        return body, None

    def preview_companies(
        self,
        q: Optional[str] = None,
        state: Optional[str] = None,
        cities: Optional[str] = None,
        counties: Optional[str] = None,
        naics: Optional[str] = None,
        domain: Optional[str] = None,
        min_employees: Optional[int] = None,
        max_employees: Optional[int] = None,
        min_revenue: Optional[float] = None,
        max_revenue: Optional[float] = None,
        independent: Optional[bool] = None,
    ) -> str:
        """Size a US private company market for free ($0.00) and inspect 5 sample companies."""
        body, err = self._build_preview_payload(
            q,
            state,
            cities,
            counties,
            naics,
            domain,
            min_employees,
            max_employees,
            min_revenue,
            max_revenue,
            independent,
        )
        if err:
            return err
        try:
            return self._request_sync("POST", "/companies/preview", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("preview_companies", error)
            return json.dumps({"error": "Dealport preview_companies request failed"})

    async def apreview_companies(
        self,
        q: Optional[str] = None,
        state: Optional[str] = None,
        cities: Optional[str] = None,
        counties: Optional[str] = None,
        naics: Optional[str] = None,
        domain: Optional[str] = None,
        min_employees: Optional[int] = None,
        max_employees: Optional[int] = None,
        min_revenue: Optional[float] = None,
        max_revenue: Optional[float] = None,
        independent: Optional[bool] = None,
    ) -> str:
        """Async variant of preview_companies ($0.00)."""
        body, err = self._build_preview_payload(
            q,
            state,
            cities,
            counties,
            naics,
            domain,
            min_employees,
            max_employees,
            min_revenue,
            max_revenue,
            independent,
        )
        if err:
            return err
        try:
            return await self._request_async("POST", "/companies/preview", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("preview_companies", error)
            return json.dumps({"error": "Dealport preview_companies request failed"})

    def search_companies(
        self,
        q: Optional[str] = None,
        state: Optional[str] = None,
        cities: Optional[str] = None,
        counties: Optional[str] = None,
        naics: Optional[str] = None,
        domain: Optional[str] = None,
        min_employees: Optional[int] = None,
        max_employees: Optional[int] = None,
        min_revenue: Optional[float] = None,
        max_revenue: Optional[float] = None,
        independent: Optional[bool] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> str:
        """Search 28M+ US private companies ($0.01 per new Record, $0.00 repeat within 30 days)."""
        params, err = self._build_company_search_params(
            q,
            state,
            cities,
            counties,
            naics,
            domain,
            min_employees,
            max_employees,
            min_revenue,
            max_revenue,
            independent,
            limit,
            cursor,
        )
        if err:
            return err
        try:
            return self._request_sync("GET", "/companies", params=params)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("search_companies", error)
            return json.dumps({"error": "Dealport search_companies request failed"})

    async def asearch_companies(
        self,
        q: Optional[str] = None,
        state: Optional[str] = None,
        cities: Optional[str] = None,
        counties: Optional[str] = None,
        naics: Optional[str] = None,
        domain: Optional[str] = None,
        min_employees: Optional[int] = None,
        max_employees: Optional[int] = None,
        min_revenue: Optional[float] = None,
        max_revenue: Optional[float] = None,
        independent: Optional[bool] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> str:
        """Async variant of search_companies ($0.01 per new Record, $0.00 repeat within 30 days)."""
        params, err = self._build_company_search_params(
            q,
            state,
            cities,
            counties,
            naics,
            domain,
            min_employees,
            max_employees,
            min_revenue,
            max_revenue,
            independent,
            limit,
            cursor,
        )
        if err:
            return err
        try:
            return await self._request_async("GET", "/companies", params=params)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("search_companies", error)
            return json.dumps({"error": "Dealport search_companies request failed"})

    def search_buildings(
        self,
        borough: str,
        min_units: int = 10,
        q: Optional[str] = None,
        loan_due_by: Optional[int] = None,
        loan_holder: Optional[str] = None,
        signal: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> str:
        """Search NYC commercial and multifamily buildings ($0.01 per new Record)."""
        params, err = self._build_building_params(
            borough, min_units, q, loan_due_by, loan_holder, signal, limit, cursor
        )
        if err:
            return err
        try:
            return self._request_sync("GET", "/buildings", params=params)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("search_buildings", error)
            return json.dumps({"error": "Dealport search_buildings request failed"})

    async def asearch_buildings(
        self,
        borough: str,
        min_units: int = 10,
        q: Optional[str] = None,
        loan_due_by: Optional[int] = None,
        loan_holder: Optional[str] = None,
        signal: Optional[str] = None,
        limit: int = 25,
        cursor: Optional[str] = None,
    ) -> str:
        """Async variant of search_buildings ($0.01 per new Record)."""
        params, err = self._build_building_params(
            borough, min_units, q, loan_due_by, loan_holder, signal, limit, cursor
        )
        if err:
            return err
        try:
            return await self._request_async("GET", "/buildings", params=params)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("search_buildings", error)
            return json.dumps({"error": "Dealport search_buildings request failed"})

    def get_record(self, record_id: str) -> str:
        """Open a cited Dealport company Record (UUID) or NYC building Record (10-digit BBL) ($0.01 per new Record)."""
        clean_id = record_id.strip() if record_id else ""
        if not SAFE_RECORD_ID_RE.match(clean_id):
            return json.dumps({"error": "record_id must be a valid Dealport UUID or 10-digit NYC BBL"})
        try:
            return self._request_sync("GET", f"/records/{quote(clean_id, safe='')}")
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("get_record", error)
            return json.dumps({"error": "Dealport get_record request failed"})

    async def aget_record(self, record_id: str) -> str:
        """Async variant of get_record ($0.01 per new Record)."""
        clean_id = record_id.strip() if record_id else ""
        if not SAFE_RECORD_ID_RE.match(clean_id):
            return json.dumps({"error": "record_id must be a valid Dealport UUID or 10-digit NYC BBL"})
        try:
            return await self._request_async("GET", f"/records/{quote(clean_id, safe='')}")
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("get_record", error)
            return json.dumps({"error": "Dealport get_record request failed"})

    def find_owner(self, company_id: str, person: Optional[str] = None) -> str:
        """Resolve verified human owner phones, emails, and profile ($0.09 per verified hit, $0.00 miss)."""
        clean_id = company_id.strip() if company_id else ""
        if not UUID_RE.match(clean_id):
            return json.dumps({"error": "company_id must be a valid Dealport company UUID"})
        body: dict[str, Any] = {"company_id": clean_id, "person": person.strip() if person else None}
        try:
            return self._request_sync("POST", "/owners", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("find_owner", error)
            return json.dumps({"error": "Dealport find_owner request failed"})

    async def afind_owner(self, company_id: str, person: Optional[str] = None) -> str:
        """Async variant of find_owner ($0.09 per verified hit, $0.00 miss)."""
        clean_id = company_id.strip() if company_id else ""
        if not UUID_RE.match(clean_id):
            return json.dumps({"error": "company_id must be a valid Dealport company UUID"})
        body: dict[str, Any] = {"company_id": clean_id, "person": person.strip() if person else None}
        try:
            return await self._request_async("POST", "/owners", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("find_owner", error)
            return json.dumps({"error": "Dealport find_owner request failed"})

    def find_contact(self, company_id: str, person: Optional[str] = None) -> str:
        """Find verified principal phones, emails, and profile ($0.09 per verified hit, $0.00 miss)."""
        clean_id = company_id.strip() if company_id else ""
        if not UUID_RE.match(clean_id):
            return json.dumps({"error": "company_id must be a valid Dealport company UUID"})
        body: dict[str, Any] = {"company_id": clean_id, "person": person.strip() if person else None}
        try:
            return self._request_sync("POST", "/contacts", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("find_contact", error)
            return json.dumps({"error": "Dealport find_contact request failed"})

    async def afind_contact(self, company_id: str, person: Optional[str] = None) -> str:
        """Async variant of find_contact ($0.09 per verified hit, $0.00 miss)."""
        clean_id = company_id.strip() if company_id else ""
        if not UUID_RE.match(clean_id):
            return json.dumps({"error": "company_id must be a valid Dealport company UUID"})
        body: dict[str, Any] = {"company_id": clean_id, "person": person.strip() if person else None}
        try:
            return await self._request_async("POST", "/contacts", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("find_contact", error)
            return json.dumps({"error": "Dealport find_contact request failed"})

    def match_company_list(self, csv: Optional[str] = None, items_json: Optional[str] = None) -> str:
        """Match CSV or JSON company rows against 28M+ Dealport Records ($0.00)."""
        body, err = self._build_match_body(csv, items_json)
        if err:
            return err
        try:
            return self._request_sync("POST", "/companies/match", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("match_company_list", error)
            return json.dumps({"error": "Dealport match_company_list request failed"})

    async def amatch_company_list(self, csv: Optional[str] = None, items_json: Optional[str] = None) -> str:
        """Async variant of match_company_list ($0.00)."""
        body, err = self._build_match_body(csv, items_json)
        if err:
            return err
        try:
            return await self._request_async("POST", "/companies/match", json_body=body)
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("match_company_list", error)
            return json.dumps({"error": "Dealport match_company_list request failed"})

    def get_balance(self) -> str:
        """Read workspace USD balance, monthly spend caps, key scopes, and rates ($0.00)."""
        try:
            return self._request_sync("GET", "/balance")
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("get_balance", error)
            return json.dumps({"error": "Dealport get_balance request failed"})

    async def aget_balance(self) -> str:
        """Async variant of get_balance ($0.00)."""
        try:
            return await self._request_async("GET", "/balance")
        except (httpx.HTTPError, OSError, ValueError, TypeError) as error:
            self._log_failure("get_balance", error)
            return json.dumps({"error": "Dealport get_balance request failed"})
