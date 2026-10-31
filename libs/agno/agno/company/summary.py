"""Product reports use the configured interface's existing outbound transport."""

import asyncio
import inspect
import json
import os
import time
from contextvars import ContextVar
from functools import wraps
from typing import Any, Dict, Sequence, Tuple

from agno.fs import FileSystem

_STATE_PATH = "delivery.md"
_LOCK_PATH = "delivery-lock.md"
_delivery_deadline: ContextVar[float] = ContextVar("company_delivery_deadline", default=0)


def _claim_content(existing: Any) -> str:
    if existing is not None and json.loads(existing.content).get("expires_at", 0) > time.time():
        raise ValueError("Another Summary delivery is in progress; retry after it finishes")
    return json.dumps({"expires_at": time.time() + 600})


def _serialized_summary(fn):
    """Serialize reports per Product through a recoverable versioned filesystem lease.

    Transport still has at-least-once semantics across a crash after sending and
    before saving its receipt. The lease prevents concurrent healthy runs from
    delivering the same baseline and expires after a worker is lost.
    """
    if inspect.iscoroutinefunction(fn):

        @wraps(fn)
        async def async_wrapped(self, *, product_id, **kwargs):
            from agno.company.playbook import _require_product_scope

            product = await self.get(product_id)
            if product is None:
                raise LookupError("Product not found")
            _require_product_scope(product)
            filesystem = _summary_state_filesystem(self.db, product_id)
            existing = await filesystem.aread_with_meta(_LOCK_PATH)
            content = _claim_content(existing)
            saved = await filesystem.awrite(
                _LOCK_PATH, content, expected_version=existing.metadata.version if existing else 0
            )
            token = _delivery_deadline.set(json.loads(content)["expires_at"])
            try:
                return await fn(self, product_id=product_id, **kwargs)
            finally:
                _delivery_deadline.reset(token)
                await filesystem.awrite(_LOCK_PATH, '{"expires_at": 0}', expected_version=saved.version)

        return async_wrapped

    @wraps(fn)
    def wrapped(self, *, product_id, **kwargs):
        from agno.company.playbook import _require_product_scope

        product = self.get(product_id)
        if product is None:
            raise LookupError("Product not found")
        _require_product_scope(product)
        filesystem = _summary_state_filesystem(self.db, product_id)
        existing = filesystem.read_with_meta(_LOCK_PATH)
        content = _claim_content(existing)
        saved = filesystem.write(_LOCK_PATH, content, expected_version=existing.metadata.version if existing else 0)
        token = _delivery_deadline.set(json.loads(content)["expires_at"])
        try:
            return fn(self, product_id=product_id, **kwargs)
        finally:
            _delivery_deadline.reset(token)
            filesystem.write(_LOCK_PATH, '{"expires_at": 0}', expected_version=saved.version)

    return wrapped


def _delivery_state(report: str) -> str:
    """Keep only the delivered baseline and receipts, outside the expiring wiki."""
    import re

    baseline = re.findall(r"<!-- Company delivered snapshot: [A-Za-z0-9+/=]+ -->", report)
    receipts = re.findall(r"<!-- Delivered run: [a-f0-9]{64} -->", report)
    return "\n" + "\n".join([*baseline[-1:], *dict.fromkeys(receipts)]) + "\n"


def _summary_state_filesystem(db: Any, product_id: str) -> FileSystem:
    return FileSystem(db, namespace=f"company/products/{product_id}/summary-state", user_scoped=False)


def _load_summary_state(db: Any, product_id: str, legacy_report: str) -> Tuple[FileSystem, str, int]:
    """Migrate legacy receipts before the report can expire; writes use filesystem versions."""
    filesystem = _summary_state_filesystem(db, product_id)
    existing = filesystem.read_with_meta(_STATE_PATH)
    if existing is not None:
        assert existing.metadata.version is not None, "Summary delivery state requires a versioned filesystem"
        return filesystem, existing.content, existing.metadata.version
    content = _delivery_state(legacy_report)
    saved = filesystem.write(_STATE_PATH, content, expected_version=0)
    assert saved.version is not None, "Summary delivery state requires a versioned filesystem"
    return filesystem, content, saved.version


async def _aload_summary_state(db: Any, product_id: str, legacy_report: str) -> Tuple[FileSystem, str, int]:
    """Asynchronously preserve delivery state independently of report retention."""
    filesystem = _summary_state_filesystem(db, product_id)
    existing = await filesystem.aread_with_meta(_STATE_PATH)
    if existing is not None:
        assert existing.metadata.version is not None, "Summary delivery state requires a versioned filesystem"
        return filesystem, existing.content, existing.metadata.version
    content = _delivery_state(legacy_report)
    saved = await filesystem.awrite(_STATE_PATH, content, expected_version=0)
    assert saved.version is not None, "Summary delivery state requires a versioned filesystem"
    return filesystem, content, saved.version


def _summary_report(product: Any, counts: Any, tasks: Any, narrative: str, previous: str) -> str:
    """Compare stored Task facts with the preceding report and retain the executor's narrative."""
    import base64
    import json
    import re

    if not isinstance(narrative, str) or not narrative.strip():
        raise ValueError("Summary requires the executor's narrative")
    prior: Dict[str, Any] = {}
    snapshots = re.findall(r"<!-- Company delivered snapshot: ([A-Za-z0-9+/=]+) -->", previous)
    if snapshots:
        try:
            prior = json.loads(base64.b64decode(snapshots[-1]))
            if not isinstance(prior, dict):
                prior = {}
        except (ValueError, UnicodeDecodeError):
            prior = {}
    current: Dict[str, Any] = {}
    failures = []
    waiting = []
    for task in tasks:
        result = task.get("result") or {}
        status = str(result.get("status") or "").upper()
        error = (
            str(result.get("error") or result.get("content") or "No failure detail recorded")
            if status in {"ERROR", "FAILED", "CANCELLED"}
            else None
        )
        current[task["id"]] = {"title": task["title"], "status": task["status"], "run_status": status, "error": error}
        if error and task["status"] == "in_progress" and result.get("status") in {"ERROR", "CANCELLED"}:
            failures.append("- " + task["title"] + " (" + task["id"] + "): " + status + ": " + error)
        if task["status"] in {"backlog", "in_review"}:
            waiting.append("- " + task["title"] + ": " + task["status"])
    changes = []
    for task_id, state in current.items():
        old = prior.get(task_id)
        if old is None:
            changes.append("- Added " + state["title"] + ": " + state["status"])
        elif old != state:
            changes.append(
                "- "
                + state["title"]
                + ": "
                + str(old.get("status"))
                + " → "
                + state["status"]
                + ("; run " + state["run_status"] if state["run_status"] else "")
            )
    for task_id in prior.keys() - current.keys():
        changes.append("- No longer visible: " + str(prior[task_id].get("title", task_id)))
    snapshot = base64.b64encode(json.dumps(current, sort_keys=True).encode()).decode()
    return (
        "# "
        + product["name"]
        + " summary\n\n"
        + "\n".join(f"{name}: {count}" for name, count in counts.items())
        + "\n\n## Narrative\n\n"
        + narrative.strip()
        + "\n\n## What changed\n\n"
        + ("\n".join(changes) or "No Task changes since the last delivered summary.")
        + "\n\n## Waiting on the owner\n\n"
        + ("\n".join(waiting) or "Nothing awaiting the owner.")
        + "\n\n## Failed Tasks\n\n"
        + ("\n".join(failures) or "No failed Tasks.")
        + ("\n\nQuiet successful check: no work requires attention." if not tasks else "")
        + "\n\n<!-- Company summary snapshot: "
        + snapshot
        + " -->\n"
    )


def _summary_page(previous: str, run_id: str, report: str):
    """Build the report using durable delivery receipts, including intervening runs."""
    import re

    from agno.utils.string import hash_string_sha256

    if not run_id:
        raise ValueError("Summary requires a run id")
    marker = "\n<!-- Delivered run: " + hash_string_sha256(run_id) + " -->\n"
    receipts = ["\n" + receipt + "\n" for receipt in re.findall(r"<!-- Delivered run: [a-f0-9]{64} -->", previous)]
    baseline = re.findall(r"<!-- Company delivered snapshot: ([A-Za-z0-9+/=]+) -->", previous)
    # Legacy or never-delivered pages have no trusted delivery baseline: report all current Tasks once.
    snapshot = baseline[-1] if baseline else "e30="
    pending = report + "\n<!-- Company delivered snapshot: " + snapshot + " -->\n" + "".join(receipts)
    return pending, marker in receipts, marker


def _summary_delivered(report: str, marker: str) -> str:
    """Advance the baseline only with the delivery receipt, after transport succeeds."""
    import re

    current = re.findall(r"<!-- Company summary snapshot: ([A-Za-z0-9+/=]+) -->", report)
    baseline = list(re.finditer(r"<!-- Company delivered snapshot: [A-Za-z0-9+/=]+ -->", report))
    if not current or not baseline:
        raise ValueError("Summary snapshot is missing")
    last = baseline[-1]
    return (
        report[: last.start()]
        + "<!-- Company delivered snapshot: "
        + current[-1]
        + " -->"
        + report[last.end() :]
        + marker
    )


async def _adeliver_summary(interfaces: Sequence[Any], interface_type: str, destination: str, message: str) -> None:
    """Deliver to a human-configured destination; credentials remain inside the interface."""
    interface = next((item for item in interfaces if item.type == interface_type), None)
    if interface is None:
        raise ValueError("Summary interface is not configured on AgentOS")
    if interface_type == "slack":
        from slack_sdk.web.async_client import AsyncWebClient

        from agno.os.interfaces.slack.helpers import send_slack_message_async

        client = AsyncWebClient(token=interface.token or os.getenv("SLACK_TOKEN"), ssl=interface.ssl)
        await send_slack_message_async(client, destination, "", message)
    elif interface_type == "telegram":
        from telebot.async_telebot import AsyncTeleBot

        from agno.os.interfaces.telegram.helpers import send_message

        token = interface.token or os.getenv("TELEGRAM_TOKEN")
        if not isinstance(token, str) or not token:
            raise ValueError("Telegram interface token is not configured")
        bot = AsyncTeleBot(token)
        try:
            await send_message(bot, int(destination), message)
        finally:
            await bot.close_session()
    elif interface_type == "whatsapp":
        from agno.os.interfaces.whatsapp.helpers import WhatsAppConfig, send_whatsapp_message_async

        config = WhatsAppConfig.init(access_token=interface.access_token, phone_number_id=interface.phone_number_id)
        await send_whatsapp_message_async(destination, message, config)
    else:
        raise ValueError("Summary requires a Slack, Telegram or WhatsApp interface")


async def adeliver_summary(interfaces: Sequence[Any], interface_type: str, destination: str, message: str) -> None:
    """Bound the send so a live transport cannot outlast its delivery lease."""
    deadline = _delivery_deadline.get()
    if deadline and time.time() + 65 >= deadline:
        raise ValueError("Summary delivery lease expired before transport; retry")
    await asyncio.wait_for(_adeliver_summary(interfaces, interface_type, destination, message), timeout=60)


def deliver_summary(interfaces: Sequence[Any], interface_type: str, destination: str, message: str) -> None:
    """Synchronous counterpart for code-managed reports."""
    asyncio.run(adeliver_summary(interfaces, interface_type, destination, message))
