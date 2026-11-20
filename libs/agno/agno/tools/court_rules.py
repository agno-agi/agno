"""
Court Rules toolkit for U.S. court filing rules, judge standing orders and court holidays.

Court Rules (https://www.courtrules.app/) is a free reference for U.S. federal and state
court rules, local rules and judge standing orders. This toolkit reads the same data through
the Court Rules REST API (https://docs.courtrules.app), so an agent can look up the rules that
apply to a filing before it is drafted: page limits, courtesy copies, pre-motion conferences,
e-filing, service, fees and court closures. Every rule carries the source document it was
extracted from.

Prerequisites:
- Sign in at https://console.courtrules.app (Google or email) and copy an API key.
- Set the environment variable `COURT_RULES_API_KEY`, or pass `api_key="..."` when
  constructing the toolkit.
"""

import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

# Structured filing rule types accepted by the `logic_type` filter of the rules search.
LogicType = Literal[
    "CourtesyCopyRule",
    "PageWordLimitRule",
    "PreMotionConferenceRule",
    "AdjournmentRequirementRule",
    "BundlingRule",
    "FormatConstraint",
    "DocumentRequirement",
    "CommunicationRule",
    "SealingProcedure",
    "ElectronicFilingRule",
    "FilingTimingRule",
    "ServiceRule",
    "FilingFeeRule",
    "JuniorLawyerIncentive",
]

# Document scopes accepted by the rules endpoint for courts that have a compliance profile.
DocumentScope = Literal[
    "brief_support",
    "brief_reply",
    "brief_opposition",
    "reconsideration_support",
    "reconsideration_reply",
    "letter",
    "discovery_letter",
    "proposed_findings",
    "affidavit",
    "settlement_statement",
    "objection_response",
    "rule_56_1_statement",
]

# Motion types accepted by the rules endpoint for courts that have a compliance profile.
MotionType = Literal[
    "Rule_12",
    "Rule_56",
    "Rule_50",
    "Rule_59",
    "Rule_60",
    "Daubert",
    "TRO",
    "preliminary_injunction",
    "reconsideration",
    "discovery",
    "motion_to_amend",
    "motion_in_limine",
    "general",
]

COURT_RULES_INSTRUCTIONS = """\
Use the Court Rules tools to look up U.S. court filing rules before answering a question about a filing.
- Call list_courts to turn a court name into a district_id, then list_judges to turn a judge name into a judge_slug.
- Call get_judge_rules for the rules that apply to one judge, or search_filing_rules to look up a topic such as \
page limits, courtesy copies, pre-motion conferences, e-filing, service or fees.
- Use judge_slug "court" with search_filing_rules to read a court's court-wide rules.
- Call list_court_holidays for the dates a court is closed.
- Quote the rule and give its source_url so the user can read the official text. Rules are extracted from documents \
that courts publish, so tell the user to confirm them against the official source before filing. This is not legal \
advice."""

# Largest page a single search_filing_rules call can return, to keep tool output within a model's context.
MAX_SEARCH_LIMIT = 50


def _dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


class CourtRulesTools(Toolkit):
    """Toolkit for looking up U.S. court filing rules, judge standing orders and court holidays.

    Args:
        api_key (Optional[str]): Court Rules API key. If not provided, the `COURT_RULES_API_KEY`
            environment variable is used. Get a key at https://console.courtrules.app.
        base_url (str): Base URL of the Court Rules API. Default is https://api.courtrules.app.
        timeout (float): Per-request HTTP timeout in seconds. Default is 30.
        max_rules (int): Most rules `get_judge_rules` returns per group (court-wide, judge, FRCP, ...).
            Use `search_filing_rules` to page through the rest. Default is 50.
        enable_list_courts (bool): Enable the `list_courts` tool. Default is True.
        enable_list_judges (bool): Enable the `list_judges` tool. Default is True.
        enable_get_judge_rules (bool): Enable the `get_judge_rules` tool. Default is True.
        enable_search_filing_rules (bool): Enable the `search_filing_rules` tool. Default is True.
        enable_list_court_holidays (bool): Enable the `list_court_holidays` tool. Default is True.
        all (bool): Enable all tools regardless of the individual flags. Default is False.
        instructions (Optional[str]): Override the default toolkit instructions.
        add_instructions (bool): Whether to add the instructions to the agent's system message. Default is True.
        **kwargs: Other `Toolkit` options, for example `cache_results=True` to reuse the result of identical calls.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.courtrules.app",
        timeout: float = 30.0,
        max_rules: int = 50,
        enable_list_courts: bool = True,
        enable_list_judges: bool = True,
        enable_get_judge_rules: bool = True,
        enable_search_filing_rules: bool = True,
        enable_list_court_holidays: bool = True,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        self.api_key = api_key or getenv("COURT_RULES_API_KEY")
        if not self.api_key:
            log_error(
                "COURT_RULES_API_KEY not set. Get a key at https://console.courtrules.app "
                "and set the COURT_RULES_API_KEY environment variable."
            )

        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)
        self.max_rules = max(1, max_rules)

        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []

        if all or enable_list_courts:
            tools.append(self.list_courts)
            async_tools.append((self.alist_courts, "list_courts"))
        if all or enable_list_judges:
            tools.append(self.list_judges)
            async_tools.append((self.alist_judges, "list_judges"))
        if all or enable_get_judge_rules:
            tools.append(self.get_judge_rules)
            async_tools.append((self.aget_judge_rules, "get_judge_rules"))
        if all or enable_search_filing_rules:
            tools.append(self.search_filing_rules)
            async_tools.append((self.asearch_filing_rules, "search_filing_rules"))
        if all or enable_list_court_holidays:
            tools.append(self.list_court_holidays)
            async_tools.append((self.alist_court_holidays, "list_court_holidays"))

        name = kwargs.pop("name", "court_rules_tools")
        super().__init__(
            name=name,
            tools=tools,
            async_tools=async_tools,
            instructions=instructions or COURT_RULES_INSTRUCTIONS,
            add_instructions=add_instructions,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "agno",
        }

    @staticmethod
    def _clean_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Drop parameters that were not set so they are not sent as empty values."""
        if not params:
            return {}
        return {key: value for key, value in params.items() if value is not None and value != ""}

    @staticmethod
    def _missing_key_error() -> Dict[str, Any]:
        return {
            "error": "Court Rules API key is required. Set COURT_RULES_API_KEY or pass api_key.",
            "suggestion": "Get a key at https://console.courtrules.app.",
        }

    @staticmethod
    def _http_error(response: httpx.Response) -> Dict[str, Any]:
        """Turn a failed response into an error dict, keeping the API's own `error` and `suggestion`."""
        status = response.status_code
        error: Dict[str, Any] = {
            "error": f"Court Rules API request failed with status {status}",
            "status_code": status,
        }
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            if body.get("error"):
                error["error"] = str(body["error"])
            for key in ("suggestion", "details", "docs_url"):
                if body.get(key):
                    error[key] = body[key]
        if status in (401, 403) and "suggestion" not in error:
            error["suggestion"] = "Check COURT_RULES_API_KEY. Get a key at https://console.courtrules.app."
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                error["retry_after"] = retry_after
        return error

    @staticmethod
    def _parse_response(response: httpx.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {"error": "Court Rules API returned a response that is not valid JSON."}
        if not isinstance(data, dict):
            return {"error": "Court Rules API returned an unexpected response."}
        return data

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.api_key:
            return self._missing_key_error()
        log_debug(f"Requesting Court Rules {path}")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(
                    f"{self.base_url}{path}", headers=self._headers(), params=self._clean_params(params)
                )
                response.raise_for_status()
                return self._parse_response(response)
        except httpx.HTTPStatusError as e:
            return self._http_error(e.response)
        except httpx.RequestError as e:
            return {"error": "Court Rules API request failed", "detail": str(e)}

    async def _arequest(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.api_key:
            return self._missing_key_error()
        log_debug(f"Requesting Court Rules {path}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}{path}", headers=self._headers(), params=self._clean_params(params)
                )
                response.raise_for_status()
                return self._parse_response(response)
        except httpx.HTTPStatusError as e:
            return self._http_error(e.response)
        except httpx.RequestError as e:
            return {"error": "Court Rules API request failed", "detail": str(e)}

    # ------------------------------------------------------------------
    # Formatting helpers (no I/O)
    # ------------------------------------------------------------------
    @staticmethod
    def _require(value: Optional[str], field: str) -> Optional[str]:
        """Return a JSON error string when a required text argument is empty, otherwise None."""
        if value is None or not str(value).strip():
            return _dump({"error": f"{field} is required."})
        return None

    @staticmethod
    def _matches(query: Optional[str], *fields: Optional[str]) -> bool:
        """True when every word of the query appears in at least one of the fields (case-insensitive)."""
        if not query or not query.strip():
            return True
        haystack = " ".join(field for field in fields if field).lower()
        return all(word in haystack for word in query.lower().split())

    @staticmethod
    def _page(total: int, offset: int, returned: int) -> Dict[str, Any]:
        next_offset = offset + returned
        return {
            "total_matches": total,
            "returned": returned,
            "offset": offset,
            "next_offset": next_offset if next_offset < total else None,
        }

    def _format_courts(
        self, data: Dict[str, Any], query: Optional[str], only_live: bool, limit: int, offset: int
    ) -> str:
        if "error" in data:
            return _dump(data)
        limit = max(1, min(limit, 100))
        offset = max(0, offset)
        matches = [
            court
            for court in data.get("courts") or []
            if (not only_live or court.get("status") == "live")
            and self._matches(
                query, court.get("district_id"), court.get("name"), court.get("state"), court.get("circuit")
            )
        ]
        page = matches[offset : offset + limit]
        courts = [
            {
                "district_id": court.get("district_id"),
                "name": court.get("name"),
                "circuit": court.get("circuit"),
                "state": court.get("state"),
                "status": court.get("status"),
                "judges_mapped": court.get("judges_mapped"),
            }
            for court in page
        ]
        return _dump({"courts": courts, "meta": self._page(len(matches), offset, len(courts))})

    def _format_judges(self, data: Dict[str, Any], district_id: str, name: Optional[str], limit: int) -> str:
        if "error" in data:
            return _dump(data)
        limit = max(1, min(limit, 200))
        matches = [
            judge for judge in data.get("judges") or [] if self._matches(name, judge.get("name"), judge.get("slug"))
        ]
        judges = []
        for judge in matches[:limit]:
            entry = {
                "slug": judge.get("slug"),
                "name": judge.get("name"),
                "judge_type": judge.get("judge_type"),
                "status": judge.get("status"),
                "has_rules": judge.get("has_rules"),
                "has_profile": judge.get("has_profile"),
                "chambers": judge.get("chambers"),
                "profile_url": judge.get("profile_url"),
            }
            judges.append({key: value for key, value in entry.items() if value is not None})
        meta = data.get("meta") or {}
        result: Dict[str, Any] = {
            "district_id": data.get("district_id", district_id),
            "judges": judges,
            "meta": {
                "total_in_court": meta.get("total", len(data.get("judges") or [])),
                "matched": len(matches),
                "returned": len(judges),
                "court_level_rules": meta.get("court_level_rules"),
            },
        }
        if len(matches) > len(judges):
            result["note"] = "More judges match. Pass a name to narrow the list."
        return _dump(result)

    @staticmethod
    def _condense_rule(rule: Any) -> Any:
        """Keep what a model needs from an extracted rule and drop internal ids and empty fields."""
        content = rule.get("content") if isinstance(rule, dict) else None
        if not isinstance(content, dict):
            # Compliance-profile rules (FRCP, local rules, standing orders) are already compact.
            return rule
        condensed = {
            "district_id": rule.get("district_id"),
            "judge_slug": rule.get("judge_slug"),
            "logic_type": rule.get("logic_type"),
            "workflow_phase": rule.get("workflow_phase"),
            "severity": content.get("visual_severity"),
            "summary": content.get("summary"),
            "source_text": content.get("source_text"),
            "structured_data": content.get("structured_data"),
            "citation_source": content.get("citation_source"),
            "source_url": rule.get("source_url"),
            "doc_kind": rule.get("doc_kind"),
            "document_type": content.get("document_type"),
            "case_types": content.get("case_type_applicability"),
            "tags": content.get("rule_tags"),
        }
        return {key: value for key, value in condensed.items() if value is not None and value != [] and value != {}}

    def _format_judge_rules(self, data: Dict[str, Any]) -> str:
        if "error" in data:
            return _dump(data)
        groups = data.get("rules") or {}
        rules: Dict[str, Any] = {}
        truncated: Dict[str, Any] = {}
        for group, items in groups.items():
            if not isinstance(items, list):
                continue
            rules[group] = [self._condense_rule(item) for item in items[: self.max_rules]]
            if len(items) > self.max_rules:
                truncated[group] = {"returned": self.max_rules, "total": len(items)}
        result: Dict[str, Any] = {"judge": data.get("judge")}
        if data.get("district_id"):
            result["district_id"] = data["district_id"]
        result["rules"] = rules
        result["meta"] = data.get("meta")
        if truncated:
            result["truncated"] = truncated
            result["note"] = (
                "Some groups were cut to keep the answer short. "
                "Use search_filing_rules with district_id, judge_slug and a query to read the rest."
            )
        return _dump(result)

    def _format_rules_search(self, data: Dict[str, Any]) -> str:
        if "error" in data:
            return _dump(data)
        rules = [self._condense_rule(rule) for rule in data.get("rules") or []]
        return _dump({"rules": rules, "meta": data.get("meta")})

    @staticmethod
    def _judge_rules_params(
        district_id: str,
        judge_slug: str,
        document_scope: Optional[str],
        motion_type: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "district_id": district_id.strip(),
            "judge_slug": judge_slug.strip(),
            "document_scope": document_scope,
            "motion_type": motion_type,
        }

    @staticmethod
    def _search_params(
        query: Optional[str],
        district_id: Optional[str],
        judge_slug: Optional[str],
        logic_type: Optional[str],
        limit: int,
        offset: int,
    ) -> Dict[str, Any]:
        return {
            "q": query.strip() if query else None,
            "district_id": district_id.strip() if district_id else None,
            "judge_slug": judge_slug.strip() if judge_slug else None,
            "logic_type": logic_type,
            "limit": max(1, min(limit, MAX_SEARCH_LIMIT)),
            "offset": max(0, offset),
        }

    @staticmethod
    def _check_search_args(
        query: Optional[str], district_id: Optional[str], judge_slug: Optional[str], logic_type: Optional[str]
    ) -> Optional[str]:
        """Return a JSON error string when a search has nothing to search for or is too long, otherwise None."""
        if not any(value and str(value).strip() for value in (query, district_id, judge_slug, logic_type)):
            return _dump({"error": "Provide a query, district_id, judge_slug or logic_type to search for."})
        if query and len(query.strip()) > 200:
            return _dump({"error": "query must be 200 characters or fewer."})
        return None

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    def list_courts(
        self,
        query: Optional[str] = None,
        only_live: bool = True,
        limit: int = 25,
        offset: int = 0,
    ) -> str:
        """Find courts covered by Court Rules and get the district_id the other tools need.

        Args:
            query (Optional[str]): Words to look for in the court id, name, state or circuit,
                e.g. "eastern district new york", "los angeles superior" or "edny".
            only_live (bool): Return only courts that have rules loaded. Defaults to True.
            limit (int): Maximum number of courts to return, from 1 to 100. Defaults to 25.
            offset (int): Number of matching courts to skip, for paging. Defaults to 0.

        Returns:
            str: JSON with the matching courts (district_id, name, circuit, state, status, judges_mapped)
            and paging details, or an error.
        """
        data = self._request("/api/v1/courts")
        return self._format_courts(data, query, only_live, limit, offset)

    async def alist_courts(
        self,
        query: Optional[str] = None,
        only_live: bool = True,
        limit: int = 25,
        offset: int = 0,
    ) -> str:
        """Find courts covered by Court Rules and get the district_id the other tools need (async).

        Args:
            query (Optional[str]): Words to look for in the court id, name, state or circuit,
                e.g. "eastern district new york", "los angeles superior" or "edny".
            only_live (bool): Return only courts that have rules loaded. Defaults to True.
            limit (int): Maximum number of courts to return, from 1 to 100. Defaults to 25.
            offset (int): Number of matching courts to skip, for paging. Defaults to 0.

        Returns:
            str: JSON with the matching courts (district_id, name, circuit, state, status, judges_mapped)
            and paging details, or an error.
        """
        data = await self._arequest("/api/v1/courts")
        return self._format_courts(data, query, only_live, limit, offset)

    def list_judges(self, district_id: str, name: Optional[str] = None, limit: int = 50) -> str:
        """List the judges of a court and get the judge_slug the other tools need.

        Args:
            district_id (str): Court identifier from list_courts, e.g. "edny" or "ca-los-angeles-superior".
            name (Optional[str]): Words to look for in the judge's name, e.g. "garaufis".
            limit (int): Maximum number of judges to return, from 1 to 200. Defaults to 50.

        Returns:
            str: JSON with the judges (slug, name, judge_type, status, has_rules, chambers, profile_url)
            and whether the court has court-wide rules, or an error.
        """
        error = self._require(district_id, "district_id")
        if error:
            return error
        data = self._request("/api/v1/judges", {"district_id": district_id.strip()})
        return self._format_judges(data, district_id.strip(), name, limit)

    async def alist_judges(self, district_id: str, name: Optional[str] = None, limit: int = 50) -> str:
        """List the judges of a court and get the judge_slug the other tools need (async).

        Args:
            district_id (str): Court identifier from list_courts, e.g. "edny" or "ca-los-angeles-superior".
            name (Optional[str]): Words to look for in the judge's name, e.g. "garaufis".
            limit (int): Maximum number of judges to return, from 1 to 200. Defaults to 50.

        Returns:
            str: JSON with the judges (slug, name, judge_type, status, has_rules, chambers, profile_url)
            and whether the court has court-wide rules, or an error.
        """
        error = self._require(district_id, "district_id")
        if error:
            return error
        data = await self._arequest("/api/v1/judges", {"district_id": district_id.strip()})
        return self._format_judges(data, district_id.strip(), name, limit)

    def get_judge_rules(
        self,
        district_id: str,
        judge_slug: str,
        document_scope: Optional[DocumentScope] = None,
        motion_type: Optional[MotionType] = None,
    ) -> str:
        """Get the filing rules that apply to one judge: standing orders, individual practices and court rules.

        Each rule cites the official document it came from. For courts with a compliance profile
        (today the Eastern District of New York, "edny") the rules come grouped as FRCP, local
        rules and standing order, and document_scope and motion_type narrow them. For other
        courts the rules come as court-wide rules and the judge's own rules, and document_scope
        and motion_type have no effect.

        Args:
            district_id (str): Court identifier from list_courts, e.g. "edny".
            judge_slug (str): Judge identifier from list_judges, e.g. "nicholas-g-garaufis".
            document_scope (Optional[str]): Kind of document to file, e.g. "brief_support" or "letter".
            motion_type (Optional[str]): Kind of motion, e.g. "Rule_56" or "Rule_12".

        Returns:
            str: JSON with the judge, the rules grouped by source and a rule count, or an error.
        """
        for value, field in ((district_id, "district_id"), (judge_slug, "judge_slug")):
            error = self._require(value, field)
            if error:
                return error
        params = self._judge_rules_params(district_id, judge_slug, document_scope, motion_type)
        data = self._request("/api/v1/rules", params)
        return self._format_judge_rules(data)

    async def aget_judge_rules(
        self,
        district_id: str,
        judge_slug: str,
        document_scope: Optional[DocumentScope] = None,
        motion_type: Optional[MotionType] = None,
    ) -> str:
        """Get the filing rules that apply to one judge: standing orders, individual practices and court rules (async).

        Each rule cites the official document it came from. For courts with a compliance profile
        (today the Eastern District of New York, "edny") the rules come grouped as FRCP, local
        rules and standing order, and document_scope and motion_type narrow them. For other
        courts the rules come as court-wide rules and the judge's own rules, and document_scope
        and motion_type have no effect.

        Args:
            district_id (str): Court identifier from list_courts, e.g. "edny".
            judge_slug (str): Judge identifier from list_judges, e.g. "nicholas-g-garaufis".
            document_scope (Optional[str]): Kind of document to file, e.g. "brief_support" or "letter".
            motion_type (Optional[str]): Kind of motion, e.g. "Rule_56" or "Rule_12".

        Returns:
            str: JSON with the judge, the rules grouped by source and a rule count, or an error.
        """
        for value, field in ((district_id, "district_id"), (judge_slug, "judge_slug")):
            error = self._require(value, field)
            if error:
                return error
        params = self._judge_rules_params(district_id, judge_slug, document_scope, motion_type)
        data = await self._arequest("/api/v1/rules", params)
        return self._format_judge_rules(data)

    def search_filing_rules(
        self,
        query: Optional[str] = None,
        district_id: Optional[str] = None,
        judge_slug: Optional[str] = None,
        logic_type: Optional[LogicType] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> str:
        """Search extracted filing rules by topic, court, judge or rule type.

        Covers e-filing, service, fees, timing, courtesy copies, page and word limits, pre-motion
        conferences and courtroom preferences. Each rule has a plain-English summary, the source
        text it came from and a link to the official document. Narrow a search with district_id,
        judge_slug or logic_type. Use judge_slug "court" for a court's court-wide rules.

        Args:
            query (Optional[str]): Words to look for in rule summaries and source text, up to 200
                characters, e.g. "courtesy copies" or "rejected filing cure".
            district_id (Optional[str]): Court identifier from list_courts, e.g. "il-cook-circuit".
            judge_slug (Optional[str]): Judge identifier from list_judges, or "court" for court-wide rules.
            logic_type (Optional[str]): Rule type, e.g. "PageWordLimitRule", "CourtesyCopyRule",
                "PreMotionConferenceRule", "ElectronicFilingRule", "ServiceRule" or "FilingFeeRule".
            limit (int): Maximum number of rules to return, from 1 to 50. Defaults to 10.
            offset (int): Number of matching rules to skip. Use meta.next_offset from the previous
                call to read the next page. Defaults to 0.

        Returns:
            str: JSON with the matching rules and paging details (meta.total, meta.next_offset), or an error.
        """
        error = self._check_search_args(query, district_id, judge_slug, logic_type)
        if error:
            return error
        data = self._request(
            "/api/v1/extracted-rules",
            self._search_params(query, district_id, judge_slug, logic_type, limit, offset),
        )
        return self._format_rules_search(data)

    async def asearch_filing_rules(
        self,
        query: Optional[str] = None,
        district_id: Optional[str] = None,
        judge_slug: Optional[str] = None,
        logic_type: Optional[LogicType] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> str:
        """Search extracted filing rules by topic, court, judge or rule type (async).

        Covers e-filing, service, fees, timing, courtesy copies, page and word limits, pre-motion
        conferences and courtroom preferences. Each rule has a plain-English summary, the source
        text it came from and a link to the official document. Narrow a search with district_id,
        judge_slug or logic_type. Use judge_slug "court" for a court's court-wide rules.

        Args:
            query (Optional[str]): Words to look for in rule summaries and source text, up to 200
                characters, e.g. "courtesy copies" or "rejected filing cure".
            district_id (Optional[str]): Court identifier from list_courts, e.g. "il-cook-circuit".
            judge_slug (Optional[str]): Judge identifier from list_judges, or "court" for court-wide rules.
            logic_type (Optional[str]): Rule type, e.g. "PageWordLimitRule", "CourtesyCopyRule",
                "PreMotionConferenceRule", "ElectronicFilingRule", "ServiceRule" or "FilingFeeRule".
            limit (int): Maximum number of rules to return, from 1 to 50. Defaults to 10.
            offset (int): Number of matching rules to skip. Use meta.next_offset from the previous
                call to read the next page. Defaults to 0.

        Returns:
            str: JSON with the matching rules and paging details (meta.total, meta.next_offset), or an error.
        """
        error = self._check_search_args(query, district_id, judge_slug, logic_type)
        if error:
            return error
        data = await self._arequest(
            "/api/v1/extracted-rules",
            self._search_params(query, district_id, judge_slug, logic_type, limit, offset),
        )
        return self._format_rules_search(data)

    def list_court_holidays(self, district_id: str, year: Optional[int] = None) -> str:
        """List the dates a court is closed, with the official source of each date.

        Args:
            district_id (str): Court identifier from list_courts, e.g. "edny".
            year (Optional[int]): Calendar year, e.g. 2026. Covers all stored years when omitted.

        Returns:
            str: JSON with the holidays (holiday_date, holiday_name, source_url, last_checked_at), or an error.
        """
        error = self._require(district_id, "district_id")
        if error:
            return error
        data = self._request("/api/v1/holidays", {"district_id": district_id.strip(), "year": year})
        return _dump(data)

    async def alist_court_holidays(self, district_id: str, year: Optional[int] = None) -> str:
        """List the dates a court is closed, with the official source of each date (async).

        Args:
            district_id (str): Court identifier from list_courts, e.g. "edny".
            year (Optional[int]): Calendar year, e.g. 2026. Covers all stored years when omitted.

        Returns:
            str: JSON with the holidays (holiday_date, holiday_name, source_url, last_checked_at), or an error.
        """
        error = self._require(district_id, "district_id")
        if error:
            return error
        data = await self._arequest("/api/v1/holidays", {"district_id": district_id.strip(), "year": year})
        return _dump(data)
