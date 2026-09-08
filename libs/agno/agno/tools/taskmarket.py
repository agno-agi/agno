"""TaskMarket requester toolkit for Agno agents.

Funded creation is delegated to the official TaskMarket CLI. This toolkit
never requests, stores, logs, or commits private keys. Submissions are
listed for human review and are never auto-accepted or auto-rejected.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

DEFAULT_API_URL = "https://api.taskmarket.dev"
DEFAULT_MAX_SPEND_USDC = 10.0
DEFAULT_NETWORK = "base"
ALLOWED_NETWORKS = frozenset({"base", "base-mainnet"})
CONFIRM_TTL_SECONDS = 30 * 60
CLI_TIMEOUT_SECONDS = 120
USDC_DECIMALS = 6
APP_URL = "https://taskmarket.dev/tasks"


def usdc_to_base_units(amount: float) -> str:
    if amount < 0:
        raise ValueError("amount must be >= 0")
    return str(int(round(float(amount) * (10 ** USDC_DECIMALS))))


def canonical_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def is_unknown_settlement(text: str) -> bool:
    lowered = (text or "").lower()
    needles = (
        "settlement status unknown",
        "unknown settlement",
        "settlement pending",
        "payment pending",
        "pending settlement",
        "status is unknown",
    )
    return any(n in lowered for n in needles)


class TaskMarketTools(Toolkit):
    """Requester-side TaskMarket tools. No keys. No silent settlement."""

    def __init__(self, api_url=None, max_spend_usdc=None, network=None, cli_bin=None, enable_accept_reject=False, **kwargs):
        self.api_url = (api_url or os.getenv("TASKMARKET_API_URL") or DEFAULT_API_URL).rstrip("/")
        env_max = os.getenv("TASKMARKET_MAX_SPEND_USDC")
        self.max_spend_usdc = float(max_spend_usdc if max_spend_usdc is not None else (env_max or DEFAULT_MAX_SPEND_USDC))
        self.network = (network or os.getenv("TASKMARKET_NETWORK") or DEFAULT_NETWORK).strip().lower()
        self.cli_bin = cli_bin or os.getenv("TASKMARKET_CLI") or "taskmarket"
        self.enable_accept_reject = enable_accept_reject
        self._pending_confirms = {}
        tools = [self.preview_task, self.create_task, self.get_task, self.get_status, self.list_submissions]
        if enable_accept_reject:
            tools.extend([self.accept_submission, self.reject_submission])
        super().__init__(name="taskmarket", tools=tools, **kwargs)

    def _network_error(self):
        if self.network not in ALLOWED_NETWORKS:
            return "Unsupported network %r. TaskMarket requester payments are restricted to Base mainnet (TASKMARKET_NETWORK=base)." % (self.network,)
        return None

    def _purge(self):
        now = time.time()
        for key, value in list(self._pending_confirms.items()):
            if now - float(value["created"]) > CONFIRM_TTL_SECONDS:
                self._pending_confirms.pop(key, None)

    def _issue_token(self, payload):
        self._purge()
        nonce = secrets.token_hex(16)
        token = hashlib.sha256(("%s:%s" % (nonce, canonical_payload(payload))).encode("utf-8")).hexdigest()
        self._pending_confirms[token] = {"payload": payload, "created": time.time()}
        return token

    def _task_url(self, task_id):
        return "%s/%s" % (APP_URL, task_id)

    def _http_get(self, path):
        url = "%s%s" % (self.api_url, path)
        req = Request(url, headers={"Accept": "application/json", "User-Agent": "agno-taskmarket-tools/1.0"})
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError("TaskMarket GET %s failed: HTTP %s" % (path, exc.code)) from exc
        except URLError as exc:
            raise RuntimeError("TaskMarket GET %s failed: %s" % (path, exc.reason)) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("TaskMarket GET %s returned non-JSON" % path) from exc

    def _run_cli(self, args):
        binary = self.cli_bin if os.path.sep in self.cli_bin else shutil.which(self.cli_bin)
        if not binary:
            raise RuntimeError("Official TaskMarket CLI not found on PATH. See https://docs.taskmarket.dev/ for install, then run taskmarket init. This toolkit never stores keys.")
        cmd = [binary] + list(args)
        log_debug("Running TaskMarket CLI")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS, check=False)

    def _preview_payload(self, description, reward_usdc, duration_hours, deliverables, mode, tags):
        if not description or not str(description).strip():
            raise ValueError("description is required")
        if not deliverables or not str(deliverables).strip():
            raise ValueError("deliverables is required")
        if float(reward_usdc) <= 0:
            raise ValueError("reward_usdc must be > 0")
        if float(duration_hours) <= 0:
            raise ValueError("duration_hours must be > 0")
        if float(reward_usdc) > self.max_spend_usdc:
            raise ValueError("reward_usdc exceeds max spend %s USDC" % self.max_spend_usdc)
        deadline = (datetime.now(timezone.utc) + timedelta(hours=float(duration_hours))).replace(microsecond=0).isoformat()
        tag_list = [item.strip() for item in str(tags or "").split(",") if item.strip()]
        return {
            "description": str(description).strip(),
            "deliverables": str(deliverables).strip(),
            "reward_usdc": float(reward_usdc),
            "reward_base_units": usdc_to_base_units(float(reward_usdc)),
            "duration_hours": float(duration_hours),
            "deadline_utc": deadline,
            "mode": mode or "bounty",
            "tags": tag_list,
            "network": "base",
            "chain": "Base mainnet",
            "max_spend_usdc": float(self.max_spend_usdc),
        }

    def _durable(self, payload):
        keys = ("description", "deliverables", "reward_usdc", "reward_base_units", "duration_hours", "mode", "tags", "network")
        return {key: payload[key] for key in keys}

    def preview_task(self, description, reward_usdc, duration_hours, deliverables, mode="bounty", tags=""):
        """Preview a TaskMarket task. Does not create or fund anything.

        Shows description, reward, deadline, deliverables, Base network, and max spend.
        Returns a one-time confirm_token for create_task.
        """
        net_err = self._network_error()
        if net_err:
            return json.dumps({"ok": False, "error": net_err, "paid": False})
        try:
            payload = self._preview_payload(description, reward_usdc, duration_hours, deliverables, mode, tags)
        except ValueError as exc:
            return json.dumps({"ok": False, "error": str(exc), "paid": False})
        token = self._issue_token(payload)
        return json.dumps({
            "ok": True,
            "paid": False,
            "requires_confirmation": True,
            "confirm_token": token,
            "confirm_ttl_seconds": CONFIRM_TTL_SECONDS,
            "preview": payload,
            "notice": "Preview only. Creating this task spends USDC on Base. Call create_task with confirm=True and this confirm_token.",
        })

    def create_task(self, description, reward_usdc, duration_hours, deliverables, confirm=False, confirm_token="", mode="bounty", tags=""):
        """Create and fund a task via the official CLI after explicit confirmation.

        Requires confirm=True and a confirm_token from preview_task for this payload.
        Does not retry when settlement status is unknown.
        """
        net_err = self._network_error()
        if net_err:
            return json.dumps({"ok": False, "error": net_err, "paid": False, "retry": False})
        if not confirm:
            return json.dumps({"ok": False, "error": "Fresh explicit confirmation is required. Call preview_task first, then create_task with confirm=True and the confirm_token.", "paid": False, "retry": False})
        if not confirm_token:
            return json.dumps({"ok": False, "error": "confirm_token is required", "paid": False, "retry": False})
        self._purge()
        pending = self._pending_confirms.pop(confirm_token, None)
        if pending is None:
            return json.dumps({"ok": False, "error": "confirm_token is invalid, expired, or already used. Run preview_task again.", "paid": False, "retry": False})
        try:
            payload = self._preview_payload(description, reward_usdc, duration_hours, deliverables, mode, tags)
        except ValueError as exc:
            return json.dumps({"ok": False, "error": str(exc), "paid": False, "retry": False})
        if self._durable(payload) != self._durable(pending["payload"]):
            return json.dumps({"ok": False, "error": "create_task arguments do not match the confirmed preview.", "paid": False, "retry": False})
        return self._cli_create(payload)

    def _cli_create(self, payload):
        composed = payload["description"]
        if "Deliverables" not in composed:
            composed = "%s\n\n## Deliverables\n%s" % (composed, payload["deliverables"])
        duration_value = payload["duration_hours"]
        duration_arg = str(int(duration_value) if duration_value == int(duration_value) else duration_value)
        args = ["task", "create", "--description", composed, "--reward", str(payload["reward_usdc"]), "--duration", duration_arg, "--mode", str(payload["mode"])]
        if payload["tags"]:
            args.extend(["--tags", ",".join(payload["tags"])])
        try:
            proc = self._run_cli(args)
        except RuntimeError as exc:
            return json.dumps({"ok": False, "error": str(exc), "paid": False, "retry": False})
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": "CLI timed out. Settlement status unknown; not retrying.", "settlement": "unknown", "paid": False, "retry": False})
        combined = "%s\n%s" % (proc.stdout or "", proc.stderr or "")
        if is_unknown_settlement(combined):
            log_warning("TaskMarket settlement unknown; not retrying")
            return json.dumps({"ok": False, "error": "Payment settlement status is unknown. Not retrying.", "settlement": "unknown", "paid": False, "retry": False, "cli_exit": proc.returncode})
        if proc.returncode != 0:
            log_error("TaskMarket CLI create failed")
            return json.dumps({"ok": False, "error": "CLI failed. Not retrying automatically.", "settlement": "failed", "paid": False, "retry": False, "cli_exit": proc.returncode, "cli_stderr_tail": (proc.stderr or "")[-400:]})
        task_id = None
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                task_id = parsed.get("taskId") or (parsed.get("data") or {}).get("taskId")
        except json.JSONDecodeError:
            task_id = None
        if not task_id:
            return json.dumps({"ok": False, "error": "CLI succeeded but no taskId parsed. Not retrying.", "settlement": "unknown", "paid": False, "retry": False})
        return json.dumps({"ok": True, "task_id": task_id, "url": self._task_url(task_id), "network": "base", "reward_usdc": payload["reward_usdc"], "paid": True, "retry": False, "status_hint": "Call get_status or get_task. list_submissions is for human review only."})

    def get_task(self, task_id):
        """Fetch live TaskMarket task details by id (public GET)."""
        if not task_id or not str(task_id).startswith("0x"):
            return json.dumps({"ok": False, "error": "task_id must be a 0x TaskMarket id"})
        try:
            data = self._http_get("/api/tasks/%s" % task_id)
        except RuntimeError as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        if data is None:
            return json.dumps({"ok": False, "error": "task not found", "task_id": task_id})
        return json.dumps({"ok": True, "task_id": task_id, "url": self._task_url(task_id), "task": data})

    def get_status(self, task_id):
        """Compact live status for a TaskMarket task."""
        parsed = json.loads(self.get_task(task_id))
        if not parsed.get("ok"):
            return json.dumps(parsed)
        task = parsed.get("task") or {}
        return json.dumps({"ok": True, "task_id": task_id, "url": self._task_url(task_id), "status": task.get("status"), "phase": task.get("phase"), "reward": task.get("reward"), "expiry_time": task.get("expiryTime"), "submission_count": task.get("submissionCount"), "submission_window_open": task.get("submissionWindowOpen"), "review_required": True, "auto_accept": False})

    def list_submissions(self, task_id):
        """List submissions for human review. Never accepts or rejects them."""
        if not task_id or not str(task_id).startswith("0x"):
            return json.dumps({"ok": False, "error": "task_id must be a 0x TaskMarket id"})
        try:
            data = self._http_get("/api/tasks/%s/submissions" % task_id)
        except RuntimeError as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("submissions") or data.get("data") or []
        else:
            rows = []
        return json.dumps({"ok": True, "task_id": task_id, "url": self._task_url(task_id), "count": len(rows), "submissions": rows, "review": "human", "auto_accept": False, "auto_reject": False, "notice": "Present these to a human. Do not accept or reject without a separate explicit confirmation."})

    def accept_submission(self, task_id, worker, confirm=False):
        """Accept one worker after a second explicit human confirmation."""
        if not self.enable_accept_reject:
            return json.dumps({"ok": False, "error": "accept/reject is disabled on this toolkit"})
        if not confirm:
            return json.dumps({"ok": False, "error": "Accepting requires confirm=True after human review.", "retry": False})
        if not task_id or not worker:
            return json.dumps({"ok": False, "error": "task_id and worker are required", "retry": False})
        try:
            proc = self._run_cli(["task", "accept", task_id, "--worker", worker])
        except RuntimeError as exc:
            return json.dumps({"ok": False, "error": str(exc), "retry": False})
        combined = "%s\n%s" % (proc.stdout or "", proc.stderr or "")
        if is_unknown_settlement(combined):
            return json.dumps({"ok": False, "error": "Settlement status unknown. Not retrying.", "retry": False})
        if proc.returncode != 0:
            return json.dumps({"ok": False, "error": "CLI accept failed. Not retrying.", "retry": False, "cli_exit": proc.returncode})
        return json.dumps({"ok": True, "task_id": task_id, "worker": worker, "action": "accept"})

    def reject_submission(self, task_id, worker, confirm=False):
        """Reject one worker after a second explicit human confirmation."""
        if not self.enable_accept_reject:
            return json.dumps({"ok": False, "error": "accept/reject is disabled on this toolkit"})
        if not confirm:
            return json.dumps({"ok": False, "error": "Rejecting requires confirm=True after human review.", "retry": False})
        if not task_id or not worker:
            return json.dumps({"ok": False, "error": "task_id and worker are required", "retry": False})
        try:
            proc = self._run_cli(["task", "reject-submission", task_id, "--worker", worker])
        except RuntimeError as exc:
            return json.dumps({"ok": False, "error": str(exc), "retry": False})
        combined = "%s\n%s" % (proc.stdout or "", proc.stderr or "")
        if is_unknown_settlement(combined):
            return json.dumps({"ok": False, "error": "Settlement status unknown. Not retrying.", "retry": False})
        if proc.returncode != 0:
            return json.dumps({"ok": False, "error": "CLI reject failed. Not retrying.", "retry": False, "cli_exit": proc.returncode})
        return json.dumps({"ok": True, "task_id": task_id, "worker": worker, "action": "reject"})
