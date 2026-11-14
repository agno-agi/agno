"""Nonblocking permission and question transport for the pinned Codex app-server SDK.

The SDK's synchronous approval callback runs on its only reader thread. This
small transport subclass schedules requests on the owning loop instead, retaining
the SDK's thread/turn API, response router and serialized writes. Codex's
questions to the user (``item/tool/requestUserInput``) pause the run as user
feedback, and the selections are sent back as the answers.
"""

import asyncio
from typing import Any, Dict, Optional

from agno.agents._hitl import HITLBridge


def human_client(
    config: Any,
    bridge: Optional[HITLBridge],
    approval_policy: Optional[str] = None,
    reviewer: str = "user",
) -> Any:
    from importlib.metadata import version

    from openai_codex import AsyncCodex
    from openai_codex.async_client import AsyncCodexClient
    from openai_codex.client import CodexClient

    if version("openai-codex") != "0.163.0":
        raise ValueError("Native human-in-the-loop requires the tested openai-codex==0.163.0 transport")
    loop = asyncio.get_running_loop()

    class PermissionClient(CodexClient):
        def __init__(self) -> None:
            super().__init__(config=config)
            self.pending: Dict[Any, Any] = {}
            self.items: Dict[str, Any] = {}

        def _write_message(self, payload: Any) -> None:
            if payload.get("method") in ("thread/start", "thread/resume", "turn/start"):
                params = {**(payload.get("params") or {}), "approvalsReviewer": reviewer}
                # The high-level SDK inserts its auto-review defaults. Omit its
                # policy when unset so native config/profile policy remains authoritative.
                if approval_policy is None:
                    params.pop("approvalPolicy", None)
                else:
                    params["approvalPolicy"] = approval_policy
                payload = {**payload, "params": params}
            super()._write_message(payload)

        async def answer(self, params: Dict[str, Any], native: Dict[str, Any]) -> Dict[str, Any]:
            questions = params.get("questions")
            if (
                not isinstance(questions, list)
                or not questions
                or not all(isinstance(q, dict) and q.get("id") for q in questions)
            ):
                raise ValueError("Codex question request has no questions")
            if any(q.get("isSecret") for q in questions):
                # Answers are stored on the run, so a secret is never collected this way.
                raise ValueError("Secret Codex questions are not supported in the chat")
            asked = [
                {
                    "question": str(q.get("question") or q.get("header") or q["id"]),
                    "header": q.get("header"),
                    "options": [
                        {"label": str(o.get("label", "")), "description": o.get("description")}
                        for o in q.get("options") or []
                        if isinstance(o, dict)
                    ],
                }
                for q in questions
            ]
            arguments = {"questions": questions}
            if bridge is None:
                raise ValueError("A native question requires an Agno run with a database")
            selections = await bridge.ask("requestUserInput", arguments, native, asked)
            return {"answers": {q["id"]: {"answers": selected} for q, selected in zip(questions, selections)}}

        async def decide(self, message: Any) -> None:
            request_id = message["id"]
            try:
                method = message["method"]
                params = message.get("params") or {}
                if method == "item/tool/requestUserInput":
                    native = {
                        "sdk": "codex",
                        "request_id": request_id,
                        "method": method,
                        "thread_id": params.get("threadId"),
                        "turn_id": params.get("turnId"),
                        "tool_call_id": params.get("itemId"),
                        "request": params,
                    }
                    self._write_message({"id": request_id, "result": await self.answer(params, native)})
                    return
                if method not in (
                    "item/commandExecution/requestApproval",
                    "item/fileChange/requestApproval",
                    "item/permissions/requestApproval",
                ):
                    raise ValueError("Unsupported native approval request")
                item = self.items.get(str(params.get("itemId", "")), {})
                # The review surface shows the action, not protocol routing or
                # policy-amendment options this bridge never grants.
                arguments = {
                    key: value
                    for key, value in params.items()
                    if key
                    not in (
                        "threadId",
                        "turnId",
                        "itemId",
                        "startedAtMs",
                        "kind",
                        "commandActions",
                        "availableDecisions",
                        "proposedExecpolicyAmendment",
                        "proposedNetworkPolicyAmendments",
                    )
                }
                if method == "item/fileChange/requestApproval":
                    if not item.get("changes"):
                        raise ValueError("File approval has no reviewable changes")
                    arguments["changes"] = item["changes"]
                if method == "item/commandExecution/requestApproval":
                    arguments["command"] = params.get("command") or item.get("command")
                    if not arguments["command"] and not params.get("networkApprovalContext"):
                        raise ValueError("Command approval has no reviewable action")
                native = {
                    "sdk": "codex",
                    "request_id": request_id,
                    "method": method,
                    "thread_id": params.get("threadId"),
                    "turn_id": params.get("turnId"),
                    "tool_call_id": params.get("itemId"),
                    "request": params,
                }
                if bridge is None:
                    raise ValueError("A native permission request requires an Agno run with a database")
                allowed = await bridge.request(method.split("/")[1], arguments, native)
                if method == "item/permissions/requestApproval":
                    result = {"permissions": params.get("permissions", {}) if allowed else {}, "scope": "turn"}
                else:
                    result = {"decision": "accept" if allowed else "decline"}
                self._write_message({"id": request_id, "result": result})
            except Exception as error:
                try:
                    self._write_message({"id": request_id, "error": {"code": -32603, "message": str(error)}})
                except Exception as transport_error:
                    # The process may close while its permission callback is finishing.
                    self._router.fail_all(transport_error)

        def _reader_loop(self) -> None:
            try:
                while True:
                    message: Any = self._read_message()
                    if "method" in message and "id" in message:
                        self.pending = {key: task for key, task in self.pending.items() if not task.done()}
                        if len(self.pending) >= 32 or message["id"] in self.pending:
                            self._write_message(
                                {
                                    "id": message["id"],
                                    "error": {"code": -32603, "message": "Too many pending permission requests"},
                                }
                            )
                            continue
                        self.pending[message["id"]] = asyncio.run_coroutine_threadsafe(self.decide(message), loop)
                    elif "method" in message:
                        params = message.get("params") or {}
                        if message["method"] == "item/started" and isinstance(params.get("item"), dict):
                            item = params["item"]
                            if len(self.items) >= 1024:
                                self.items.clear()
                            self.items[item.get("id", "")] = item
                        self._router.route_notification(self._coerce_notification(message["method"], params))
                    else:
                        self._router.route_response(message)
            except BaseException as error:
                for task in self.pending.values():
                    task.cancel()
                self._router.fail_all(error)

        def close(self) -> None:
            for task in list(self.pending.values()):
                task.cancel()
            super().close()

    class PermissionAsyncClient(AsyncCodexClient):
        def __init__(self) -> None:
            self._sync = PermissionClient()

    class HumanCodex(AsyncCodex):
        def __init__(self) -> None:
            self._client = PermissionAsyncClient()
            self._init = None
            self._initialized = False
            self._init_lock = asyncio.Lock()

    return HumanCodex()
