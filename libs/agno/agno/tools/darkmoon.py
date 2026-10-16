import json
import time
from os import getenv
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error

_TERMINAL_EVENTS = ("run_completed", "run_error")


class _DarkmoonRequestError(Exception):
    pass


class DarkmoonTools(Toolkit):
    """Tools for running autonomous penetration tests with a self-hosted Darkmoon instance.

    Darkmoon (https://github.com/ASCIT31/Dark-Moon) is a GPL-3.0 autonomous AI pentest platform.
    These tools call the Darkmoon Dashboard API of an instance you operate yourself; there is no
    public hosted endpoint. The Dashboard API belongs to the paid Pro edition of Darkmoon.

    Only assess systems you own or are explicitly authorised to test. Findings can include false
    positives and must be reviewed by a qualified human.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 60.0,
        enable_run_pentest: bool = True,
        enable_get_findings: bool = True,
        enable_list_campaigns: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize the Darkmoon toolkit.

        Args:
            base_url: Darkmoon Dashboard API base URL. Uses ``DARKMOON_BASE_URL`` when omitted.
            username: Dashboard username. Uses ``DARKMOON_USERNAME`` when omitted.
            password: Dashboard password. Uses ``DARKMOON_PASSWORD`` when omitted.
            timeout: Per-request timeout in seconds.
            enable_run_pentest: Register the run_pentest tool.
            enable_get_findings: Register the get_findings tool.
            enable_list_campaigns: Register the list_campaigns tool.
            all: Register all tools regardless of individual flags.
        """
        self.base_url = (base_url or getenv("DARKMOON_BASE_URL") or "").rstrip("/")
        self.username = username or getenv("DARKMOON_USERNAME")
        self.password = password or getenv("DARKMOON_PASSWORD")
        self.timeout = httpx.Timeout(timeout)
        self._token: Optional[str] = None

        if not (self.base_url and self.username and self.password):
            log_error(
                "Darkmoon connection incomplete. Set DARKMOON_BASE_URL, DARKMOON_USERNAME and "
                "DARKMOON_PASSWORD or pass base_url, username and password."
            )

        tools: List[Any] = []
        if all or enable_run_pentest:
            tools.append(self.run_pentest)
        if all or enable_get_findings:
            tools.append(self.get_findings)
        if all or enable_list_campaigns:
            tools.append(self.list_campaigns)

        name = kwargs.pop("name", "darkmoon_tools")
        super().__init__(name=name, tools=tools, **kwargs)

    # -- HTTP helpers -------------------------------------------------------
    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, authenticated: bool = True) -> Any:
        if not (self.base_url and self.username and self.password):
            raise _DarkmoonRequestError(
                "Missing Darkmoon connection settings (DARKMOON_BASE_URL, DARKMOON_USERNAME, DARKMOON_PASSWORD)"
            )
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._login()}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, f"{self.base_url}{path}", headers=headers, json=body)
        except httpx.RequestError as error:
            raise _DarkmoonRequestError(f"Request to Darkmoon failed: {error}") from error
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text
        if response.status_code >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else None
            raise _DarkmoonRequestError(
                f"Darkmoon API error {response.status_code}: "
                f"{detail if isinstance(detail, str) and detail else 'request failed'}"
            )
        return payload

    def _login(self) -> str:
        if self._token:
            return self._token
        payload = self._call(
            "POST",
            "/api/v1/auth/login",
            {"username": self.username, "password": self.password},
            authenticated=False,
        )
        token = payload.get("token") if isinstance(payload, dict) else None
        if not token:
            raise _DarkmoonRequestError("Darkmoon login did not return a token")
        self._token = str(token)
        return self._token

    def _campaigns(self) -> List[Dict[str, Any]]:
        payload = self._call("GET", "/api/v1/campaigns")
        data = payload.get("data") if isinstance(payload, dict) else None
        return data if isinstance(data, list) else []

    def _findings(self, campaign_id: str) -> Dict[str, Any]:
        payload = self._call("GET", f"/api/v1/vulnerabilities?campaign_id={quote(campaign_id, safe='')}")
        body = payload if isinstance(payload, dict) else {}
        return {
            "campaign_id": campaign_id,
            "total": body.get("total") or 0,
            "stats": body.get("stats") or {},
            "findings": body.get("data") or [],
        }

    def _wait_for_run(self, run_id: str, timeout_seconds: int, poll_interval_seconds: float) -> bool:
        """Poll the run log until a terminal event. Returns True when the wait timed out."""
        deadline = time.monotonic() + timeout_seconds
        path = f"/api/v1/run/logs/{quote(run_id, safe='')}"
        while True:
            try:
                payload = self._call("GET", path)
            except _DarkmoonRequestError as error:
                # The log does not exist until the run writes its first event.
                if " 404:" not in str(error):
                    raise
                payload = {}
            events = payload.get("data") if isinstance(payload, dict) else None
            if any(event.get("type") in _TERMINAL_EVENTS for event in events or []):
                return False
            if time.monotonic() >= deadline:
                return True
            time.sleep(poll_interval_seconds)

    # -- Tools --------------------------------------------------------------
    def run_pentest(
        self,
        target: str,
        wait_for_completion: bool = True,
        program: Optional[str] = None,
        focus: Optional[str] = None,
        severity: Optional[str] = None,
        timeout_seconds: int = 1800,
        poll_interval_seconds: float = 5.0,
    ) -> str:
        """Start an autonomous Darkmoon penetration test against one authorised target.

        Only use against targets the user owns or is authorised to test. Findings may contain
        false positives and need human review.

        Args:
            target: Host, URL or scope to assess.
            wait_for_completion: Wait for the run to finish and return its findings. When False, return the run id.
            program: Optional program name or rules-of-engagement note.
            focus: Optional comma separated focus areas, for example "auth, injection".
            severity: Optional minimum severity to report.
            timeout_seconds: Maximum time to wait for the run when wait_for_completion is True.
            poll_interval_seconds: Seconds between run status checks.

        Returns:
            JSON string with the run id, campaign id, severity statistics and findings, or an error.
        """
        target = (target or "").strip()
        if not target:
            return json.dumps({"error": "A target is required (a host, URL or scope you are authorised to test)."})

        params: Dict[str, Any] = {"target": target}
        if program and program.strip():
            params["program"] = program.strip()
        areas = [part.strip() for part in (focus or "").split(",") if part.strip()]
        if areas:
            params["focus"] = areas
        if severity and severity.strip():
            params["severity"] = severity.strip()

        try:
            known_ids = {campaign.get("id") for campaign in self._campaigns()}
            handle = self._call("POST", "/api/v1/run/campaign", params)
            run_id = handle.get("run_id") if isinstance(handle, dict) else None
            if not run_id:
                return json.dumps({"error": "Darkmoon did not return a run id"})
            if not wait_for_completion:
                return json.dumps({"status": "started", "run_id": run_id, "target": target})

            timed_out = self._wait_for_run(run_id, timeout_seconds, poll_interval_seconds)

            # The trigger returns a run id, not a campaign id: pick the campaign created by this run.
            fresh = [c for c in self._campaigns() if c.get("id") not in known_ids]
            fresh.sort(key=lambda c: str(c.get("date") or ""), reverse=True)
            campaign = next((c for c in fresh if target.lower() in str(c.get("id", "")).lower()), None)
            if campaign is None and fresh:
                campaign = fresh[0]

            result: Dict[str, Any] = {
                "run_id": run_id,
                "campaign_id": campaign.get("id") if campaign else None,
                "timed_out": timed_out,
                "total": 0,
                "stats": {},
                "findings": [],
            }
            if campaign and campaign.get("id"):
                findings = self._findings(str(campaign["id"]))
                result.update(total=findings["total"], stats=findings["stats"], findings=findings["findings"])
            return json.dumps(result)
        except _DarkmoonRequestError as error:
            log_error(str(error))
            return json.dumps({"error": str(error)})

    def get_findings(self, campaign_id: str) -> str:
        """Return the vulnerabilities and severity statistics Darkmoon recorded for a campaign.

        Findings may contain false positives and need human review.

        Args:
            campaign_id: Darkmoon campaign id, for example camp_20260922_abc123.

        Returns:
            JSON string with total, stats and findings, or an error.
        """
        campaign_id = (campaign_id or "").strip()
        if not campaign_id:
            return json.dumps({"error": "A campaign id is required."})
        try:
            return json.dumps(self._findings(campaign_id))
        except _DarkmoonRequestError as error:
            log_error(str(error))
            return json.dumps({"error": str(error)})

    def list_campaigns(self) -> str:
        """List the Darkmoon campaigns visible to the authenticated dashboard user.

        Returns:
            JSON string with the total and the list of campaigns, or an error.
        """
        try:
            campaigns = self._campaigns()
            return json.dumps({"total": len(campaigns), "campaigns": campaigns})
        except _DarkmoonRequestError as error:
            log_error(str(error))
            return json.dumps({"error": str(error)})
