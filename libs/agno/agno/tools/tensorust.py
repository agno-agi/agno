import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

DEFAULT_BASE_URL = "https://shop.tensorust.com/api/mcp"

# Fields of the vendor screen kept in screen_counterparty's answer. The full screen also
# carries per-line funding and ledger-join sections that only matter for purchase files.
_SCREEN_FIELDS = ("as_of", "lists_pulled", "matched_lines", "by_vendor", "by_rule")


class TensorustTools(Toolkit):
    """Ownership, credit and compliance lookups from US public records, via the Tensorust Ontology.

    The Tensorust Ontology joins county property rolls, state business registries, SEC
    filings (subsidiary lists and BDC schedules of investments), FCC licensing, federal
    awards, OFAC lists and the CMS Federal IDR public use file. The toolkit calls its
    public JSON-RPC endpoint with ``tools/call``, so it needs no SDK and no MCP session.

    It is **keyless by default**: every tool answers with a free preview. Setting
    ``TENSORUST_API_KEY`` (a ``tdk_...`` key) sends it as a bearer token and asks for the
    full record (every linked object, every lender's mark) instead of the preview.

    Requests go through ``httpx``, already an Agno dependency, so this toolkit needs no
    additional install.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_lookup_organization: bool = True,
        enable_who_owns_home: bool = True,
        enable_get_lender_marks: bool = True,
        enable_get_contractor_credit: bool = True,
        enable_screen_counterparty: bool = True,
        enable_get_idr_offer: bool = False,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        """Initialize TensorustTools.

        Args:
            api_key: Tensorust API key (tdk_...). Optional. Falls back to the TENSORUST_API_KEY
                env var; with neither, every tool returns the free preview.
            base_url: Endpoint URL. Falls back to the TENSORUST_API_URL env var, then to
                https://shop.tensorust.com/api/mcp. Must be https (http is allowed only for a
                loopback host, for local development).
            enable_lookup_organization: Register lookup_organization. Defaults to True.
            enable_who_owns_home: Register who_owns_home. Defaults to True.
            enable_get_lender_marks: Register get_lender_marks. Defaults to True.
            enable_get_contractor_credit: Register get_contractor_credit. Defaults to True.
            enable_screen_counterparty: Register screen_counterparty. Defaults to True.
            enable_get_idr_offer: Register get_idr_offer (No Surprises Act arbitration data).
                Defaults to False.
            all: Register all available functions. Defaults to False.
            timeout: Request timeout in seconds. Defaults to 30.
            **kwargs: Additional arguments passed to Toolkit.
        """
        self.api_key: Optional[str] = api_key or getenv("TENSORUST_API_KEY")
        self.base_url: str = (base_url or getenv("TENSORUST_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.timeout: int = timeout

        tools: List[Any] = []
        # Async variants are registered under the same names, for agent.arun() and agent.aprint_response().
        async_tools: List[Tuple[Callable[..., Any], str]] = []
        if enable_lookup_organization or all:
            tools.append(self.lookup_organization)
            async_tools.append((self.alookup_organization, "lookup_organization"))
        if enable_who_owns_home or all:
            tools.append(self.who_owns_home)
            async_tools.append((self.awho_owns_home, "who_owns_home"))
        if enable_get_lender_marks or all:
            tools.append(self.get_lender_marks)
            async_tools.append((self.aget_lender_marks, "get_lender_marks"))
        if enable_get_contractor_credit or all:
            tools.append(self.get_contractor_credit)
            async_tools.append((self.aget_contractor_credit, "get_contractor_credit"))
        if enable_screen_counterparty or all:
            tools.append(self.screen_counterparty)
            async_tools.append((self.ascreen_counterparty, "screen_counterparty"))
        if enable_get_idr_offer or all:
            tools.append(self.get_idr_offer)
            async_tools.append((self.aget_idr_offer, "get_idr_offer"))

        super().__init__(name="tensorust_tools", tools=tools, async_tools=async_tools, **kwargs)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def lookup_organization(self, name: str) -> str:
        """Use this function to find out who owns or controls a US company or organization.

        Resolves the name to its legal entity or control group and returns its data sources,
        linked objects by type (subsidiaries, parent, homes owned, FCC licenses, federal awards,
        lobbying) and the federal rules that apply to it, with other close name matches.

        Args:
            name (str): Organization name, e.g. "Invitation Homes" or "Lockheed Martin".

        Returns:
            str: The organization card as JSON, or an error message.
        """
        if not name or not name.strip():
            return "Error: an organization name is required."
        return self._call("lookup_organization", self._with_full({"name": name.strip()}))

    async def alookup_organization(self, name: str) -> str:
        """Use this function to find out who owns or controls a US company or organization.

        Resolves the name to its legal entity or control group and returns its data sources,
        linked objects by type (subsidiaries, parent, homes owned, FCC licenses, federal awards,
        lobbying) and the federal rules that apply to it, with other close name matches.

        Args:
            name (str): Organization name, e.g. "Invitation Homes" or "Lockheed Martin".

        Returns:
            str: The organization card as JSON, or an error message.
        """
        if not name or not name.strip():
            return "Error: an organization name is required."
        return await self._acall("lookup_organization", self._with_full({"name": name.strip()}))

    def who_owns_home(self, address: str, zip_code: str) -> str:
        """Use this function to find the owner of record of a US single-family home.

        Returns the owner of record and, when it is a business entity, its parent control group
        and how many homes the group holds. Coverage is entity-owned homes in 17 large counties
        (Houston, Dallas, Fort Worth, San Antonio, Austin, Phoenix, Las Vegas, Atlanta, Tampa,
        Orlando, Jacksonville, Charlotte, Memphis and others).

        Args:
            address (str): Street address, e.g. "2746 Lofty Elm St".
            zip_code (str): 5-digit ZIP code.

        Returns:
            str: The owner and control group as JSON, or an error message.
        """
        if not address or not address.strip() or not zip_code or not zip_code.strip():
            return "Error: both a street address and a ZIP code are required."
        return self._call("who_owns_home", {"address": address.strip(), "zip": zip_code.strip()})

    async def awho_owns_home(self, address: str, zip_code: str) -> str:
        """Use this function to find the owner of record of a US single-family home.

        Returns the owner of record and, when it is a business entity, its parent control group
        and how many homes the group holds. Coverage is entity-owned homes in 17 large counties
        (Houston, Dallas, Fort Worth, San Antonio, Austin, Phoenix, Las Vegas, Atlanta, Tampa,
        Orlando, Jacksonville, Charlotte, Memphis and others).

        Args:
            address (str): Street address, e.g. "2746 Lofty Elm St".
            zip_code (str): 5-digit ZIP code.

        Returns:
            str: The owner and control group as JSON, or an error message.
        """
        if not address or not address.strip() or not zip_code or not zip_code.strip():
            return "Error: both a street address and a ZIP code are required."
        return await self._acall("who_owns_home", {"address": address.strip(), "zip": zip_code.strip()})

    def get_lender_marks(self, company: str) -> str:
        """Use this function to see what private credit lenders say a company's loan is worth.

        Returns the fair value that each BDC (business development company) fund holding the
        company's first-lien term loan reported in its latest 10-Q, as a share of par, with the
        manager (Ares, Blue Owl, Golub, Blackrock...) and the gap between the lowest and highest
        mark. A wide gap or a low mark is an early sign of credit stress at a private company.

        Args:
            company (str): Borrower name, e.g. "Pluralsight".

        Returns:
            str: The lender marks as JSON, or an error message.
        """
        if not company or not company.strip():
            return "Error: a company name is required."
        return self._call("lender_marks", self._with_full({"name": company.strip()}))

    async def aget_lender_marks(self, company: str) -> str:
        """Use this function to see what private credit lenders say a company's loan is worth.

        Returns the fair value that each BDC (business development company) fund holding the
        company's first-lien term loan reported in its latest 10-Q, as a share of par, with the
        manager (Ares, Blue Owl, Golub, Blackrock...) and the gap between the lowest and highest
        mark. A wide gap or a low mark is an early sign of credit stress at a private company.

        Args:
            company (str): Borrower name, e.g. "Pluralsight".

        Returns:
            str: The lender marks as JSON, or an error message.
        """
        if not company or not company.strip():
            return "Error: a company name is required."
        return await self._acall("lender_marks", self._with_full({"name": company.strip()}))

    def get_contractor_credit(self, company: str) -> str:
        """Use this function to check the credit health of a US federal contractor.

        For a contractor financed by private credit funds, returns its federal obligations by
        agency, what each lender marks its first-lien loan at and how that mark moved over the
        last quarters, its workforce headcount trend and any stress signals.

        Args:
            company (str): Contractor name, 12-character UEI or 9-digit EIN, e.g. "Peraton".

        Returns:
            str: The contractor credit card as JSON, or an error message.
        """
        if not company or not company.strip():
            return "Error: a company name, UEI or EIN is required."
        return self._call("contractor_credit", self._with_full({"name": company.strip()}))

    async def aget_contractor_credit(self, company: str) -> str:
        """Use this function to check the credit health of a US federal contractor.

        For a contractor financed by private credit funds, returns its federal obligations by
        agency, what each lender marks its first-lien loan at and how that mark moved over the
        last quarters, its workforce headcount trend and any stress signals.

        Args:
            company (str): Contractor name, 12-character UEI or 9-digit EIN, e.g. "Peraton".

        Returns:
            str: The contractor credit card as JSON, or an error message.
        """
        if not company or not company.strip():
            return "Error: a company name, UEI or EIN is required."
        return await self._acall("contractor_credit", self._with_full({"name": company.strip()}))

    def screen_counterparty(self, name: str) -> str:
        """Use this function to screen a company or vendor name against US sanctions and banned-vendor lists.

        Checks the name against the OFAC sanctions lists and against the US restricted-vendor
        lists (DoD 1260H Chinese military companies, Section 889 telecom and video surveillance,
        FCC Covered List, UFLPA forced-labor entity list, BIOSECURE), and returns each hit with
        the rule it triggers and the citation. A screen is a starting point for review, not a
        legal determination.

        Args:
            name (str): Company or vendor name, e.g. "Hikvision".

        Returns:
            str: JSON with the sanctions matches and the restricted-vendor screen, or an error message.
        """
        if not name or not name.strip():
            return "Error: a company or vendor name is required."
        sanctions_args, vendor_args = self._screen_args(name.strip())
        sanctions = self._call("query_ontology", sanctions_args)
        vendors = self._call("exposure_screen_purchases", vendor_args)
        return self._merge_screen(name.strip(), sanctions, vendors)

    async def ascreen_counterparty(self, name: str) -> str:
        """Use this function to screen a company or vendor name against US sanctions and banned-vendor lists.

        Checks the name against the OFAC sanctions lists and against the US restricted-vendor
        lists (DoD 1260H Chinese military companies, Section 889 telecom and video surveillance,
        FCC Covered List, UFLPA forced-labor entity list, BIOSECURE), and returns each hit with
        the rule it triggers and the citation. A screen is a starting point for review, not a
        legal determination.

        Args:
            name (str): Company or vendor name, e.g. "Hikvision".

        Returns:
            str: JSON with the sanctions matches and the restricted-vendor screen, or an error message.
        """
        if not name or not name.strip():
            return "Error: a company or vendor name is required."
        sanctions_args, vendor_args = self._screen_args(name.strip())
        sanctions = await self._acall("query_ontology", sanctions_args)
        vendors = await self._acall("exposure_screen_purchases", vendor_args)
        return self._merge_screen(name.strip(), sanctions, vendors)

    def get_idr_offer(
        self, code: str, payer: Optional[str] = None, state: Optional[str] = None, qpa: Optional[float] = None
    ) -> str:
        """Use this function to look up No Surprises Act arbitration (federal IDR) outcomes for a billing code.

        From the CMS Federal IDR public use file: for a CPT/HCPCS code, payer and state, how many
        disputes were decided, how often the provider won and the offer band (as multiples of the
        qualifying payment amount) that won.

        Args:
            code (str): CPT or HCPCS code, e.g. "99284".
            payer (Optional[str]): Payer email domain or common name, e.g. "uhc.com" or "Aetna".
            state (Optional[str]): Two-letter state of service, e.g. "TX".
            qpa (Optional[float]): Qualifying payment amount in dollars, to get the band in dollars.

        Returns:
            str: The dispute statistics as JSON, or an error message.
        """
        if not code or not code.strip():
            return "Error: a CPT or HCPCS code is required."
        return self._call("idr_offer", self._idr_args(code, payer, state, qpa))

    async def aget_idr_offer(
        self, code: str, payer: Optional[str] = None, state: Optional[str] = None, qpa: Optional[float] = None
    ) -> str:
        """Use this function to look up No Surprises Act arbitration (federal IDR) outcomes for a billing code.

        From the CMS Federal IDR public use file: for a CPT/HCPCS code, payer and state, how many
        disputes were decided, how often the provider won and the offer band (as multiples of the
        qualifying payment amount) that won.

        Args:
            code (str): CPT or HCPCS code, e.g. "99284".
            payer (Optional[str]): Payer email domain or common name, e.g. "uhc.com" or "Aetna".
            state (Optional[str]): Two-letter state of service, e.g. "TX".
            qpa (Optional[float]): Qualifying payment amount in dollars, to get the band in dollars.

        Returns:
            str: The dispute statistics as JSON, or an error message.
        """
        if not code or not code.strip():
            return "Error: a CPT or HCPCS code is required."
        return await self._acall("idr_offer", self._idr_args(code, payer, state, qpa))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call(self, tool: str, arguments: Dict[str, Any]) -> str:
        """Call one Tensorust tool and return its text answer."""
        try:
            url = self._resolved_base_url()
            log_debug(f"Calling Tensorust tool {tool}")
            response = httpx.post(
                url, json=self._payload(tool, arguments), headers=self._headers(), timeout=self.timeout
            )
        except (httpx.HTTPError, ValueError) as e:
            log_error(f"Tensorust request failed: {e}")
            return f"Error calling Tensorust: {e}"
        return self._parse_response(response)

    async def _acall(self, tool: str, arguments: Dict[str, Any]) -> str:
        """Call one Tensorust tool asynchronously and return its text answer."""
        try:
            url = self._resolved_base_url()
            log_debug(f"Calling Tensorust tool {tool}")
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=self._payload(tool, arguments), headers=self._headers())
        except (httpx.HTTPError, ValueError) as e:
            log_error(f"Tensorust request failed: {e}")
            return f"Error calling Tensorust: {e}"
        return self._parse_response(response)

    @staticmethod
    def _payload(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}

    def _with_full(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Ask for the full record when a key is configured; without one the API returns the preview."""
        if (self.api_key or "").strip():
            return {**arguments, "full": True}
        return arguments

    @staticmethod
    def _screen_args(name: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        sanctions_args = {"name": name, "type": "Sanction", "limit": 10}
        vendor_args = {"lines": [{"vendor": name}]}
        return sanctions_args, vendor_args

    @staticmethod
    def _idr_args(code: str, payer: Optional[str], state: Optional[str], qpa: Optional[float]) -> Dict[str, Any]:
        arguments: Dict[str, Any] = {"code": code.strip()}
        if payer and payer.strip():
            arguments["payer"] = payer.strip()
        if state and state.strip():
            arguments["state"] = state.strip().upper()
        if qpa is not None:
            arguments["qpa"] = qpa
        return arguments

    @staticmethod
    def _merge_screen(name: str, sanctions: str, vendors: str) -> str:
        """Combine the sanctions search and the restricted-vendor screen into one answer."""
        result: Dict[str, Any] = {"name": name}
        try:
            found = json.loads(sanctions)
            result["sanctions"] = {
                "source": "OFAC sanctions lists",
                "total": found.get("total", 0),
                "matches": found.get("items", []),
            }
        except (ValueError, AttributeError):
            result["sanctions"] = {"error": sanctions}
        try:
            screen = json.loads(vendors)
            result["restricted_vendor_lists"] = {key: screen[key] for key in _SCREEN_FIELDS if key in screen}
            flags = [flag for item in screen.get("items", []) for flag in item.get("flags", [])]
            result["restricted_vendor_lists"]["flags"] = flags
        except (ValueError, AttributeError, TypeError):
            result["restricted_vendor_lists"] = {"error": vendors}
        return json.dumps(result, indent=2)

    @staticmethod
    def _parse_response(response: httpx.Response) -> str:
        """Turn a JSON-RPC response into the tool's text, or an error the agent can act on."""
        if not response.is_success:
            label = {
                401: "Tensorust authentication failed (401): check TENSORUST_API_KEY",
                429: "Tensorust rate limit exceeded (429)",
            }.get(response.status_code, f"Tensorust API error ({response.status_code})")
            log_error(label)
            return f"Error: {label}"

        try:
            body = response.json()
        except ValueError:
            return "Error: the Tensorust API returned a non-JSON response."
        if not isinstance(body, dict):
            return "Error: unexpected response from the Tensorust API."

        if body.get("error"):
            error = body["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            log_error(f"Tensorust API error: {message}")
            return f"Error: {message}"

        result = body.get("result")
        if not isinstance(result, dict):
            return "Error: unexpected response from the Tensorust API."
        content = result.get("content")
        if not isinstance(content, list):
            return "Error: unexpected response from the Tensorust API."

        text = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        if result.get("isError"):
            return f"Error: {text}"
        return text

    def _resolved_base_url(self) -> str:
        """Return the endpoint URL, enforcing https outside of loopback (the API key is a bearer token)."""
        parsed = urlsplit(self.base_url)
        if parsed.hostname:
            if parsed.scheme == "https":
                return self.base_url
            if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
                return self.base_url
        raise ValueError(f"Tensorust base URL must be an https:// URL with a host, got {self.base_url!r}")

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "agno-tensorust-tools",
        }
        key = (self.api_key or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers
