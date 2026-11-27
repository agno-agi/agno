"""Sign a Codex agent in to a ChatGPT subscription with a device code, from the running AgentOS.

Codex does the sign-in itself. A Codex app-server is started in an empty CODEX_HOME and asked for
a device-code sign-in; it answers with a link and a short code for a person to enter in their own
browser, and it writes ``auth.json`` when they have. That file is stored exactly as a refreshed
sign-in is stored after a run, and the folder is removed. Nothing here talks to OpenAI directly,
and the sign-in is never returned or logged: a caller sees the link, the code and a status.

The app-server has to stay running until the code is entered, so each attempt has a thread of its
own. An attempt lives in the process that started it. Another replica cannot see it waiting, but
every replica sees the stored sign-in once it has finished.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import threading
import time
from concurrent.futures import Future
from concurrent.futures import thread as _worker_threads  # noqa: F401
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from agno.utils.log import log_error

# How long a person has to enter the code before the attempt is given up.
WAIT_SECONDS = 15 * 60
_START_SECONDS = 60
_SLOT_WAIT_SECONDS = 2.0

WAITING, SIGNED_IN, NOT_SIGNED_IN, FAILED, CANCELLED = "waiting", "signed_in", "not_signed_in", "failed", "cancelled"


@dataclass
class _Attempt:
    agent_id: str
    started_at: float = field(default_factory=time.time)
    status: str = WAITING
    error: Optional[str] = None
    user_code: Optional[str] = None
    verification_url: Optional[str] = None
    # Set from any thread to give the attempt up.
    cancelled: threading.Event = field(default_factory=threading.Event)
    started: "Future[None]" = field(default_factory=Future)
    # Set when the attempt's thread has let go of Codex.
    ended: threading.Event = field(default_factory=threading.Event)

    def view(self) -> Dict[str, Any]:
        """What a caller may see. Never the sign-in."""
        shown: Dict[str, Any] = {"agent_id": self.agent_id, "status": self.status}
        if self.status == WAITING:
            shown.update(
                user_code=self.user_code,
                verification_url=self.verification_url,
                expires_in=max(0, int(self.started_at + WAIT_SECONDS - time.time())),
            )
        if self.error:
            shown["error"] = self.error
        return shown


_lock = threading.Lock()
_attempts: Dict[str, _Attempt] = {}


def _refuse(agent: Any) -> None:
    """Raise when this agent cannot be signed in from AgentOS."""
    from agno.agents.codex._subscription import _encryption_key, _stores_logins

    agent_id = agent.get_id()
    if agent.auth_json is not None or agent.access_token is not None:
        setting = "auth_json" if agent.auth_json is not None else "access_token"
        raise ValueError(
            f"{agent_id} has its ChatGPT credential set in code ({setting}). Remove it there to sign in from AgentOS."
        )
    if not _stores_logins(agent.db):
        raise ValueError(f"{agent_id} needs a database to keep its ChatGPT sign-in in.")
    _encryption_key(agent)
    try:
        import cryptography.fernet  # noqa: F401
    except ImportError:
        raise ImportError(
            f"{agent_id} keeps its ChatGPT sign-in encrypted in its database and needs `cryptography`. "
            "Install it with `pip install cryptography`."
        ) from None


async def _astore(agent: Any, login: Dict[str, Any]) -> None:
    """Store a new sign-in while no run of the agent is using the old one."""
    from agno.agents.codex._subscription import _finish, _take, asave

    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        release = await _finish(asyncio.ensure_future(_take(agent)))
        if release is not None:
            break
        if time.monotonic() > deadline:
            raise RuntimeError(f"{agent.get_id()} stayed busy, so its new sign-in was not stored. Sign it in again.")
        await asyncio.sleep(_SLOT_WAIT_SECONDS)
    try:
        await asave(agent, login, replace=True)
    finally:
        await _finish(asyncio.ensure_future(release()))


async def _arun(agent: Any, attempt: _Attempt, caller_loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """One attempt, in its own thread: ask Codex for a code, wait for the person, store what Codex wrote."""
    from agno.agents.codex._subscription import _loads, parse_login
    from agno.agents.codex.agent import _sdk

    codex_home = Path(tempfile.mkdtemp(prefix="agno-codex-sign-in-"))
    try:
        sdk = _sdk()
        config = agent._codex_config(sdk)
        config.env = {
            **(config.env or {}),
            **{name: "" for name in agent._subscription_blocked_env},
            "CODEX_ACCESS_TOKEN": "",
            "CODEX_HOME": str(codex_home),
        }
        config.config_overrides = (*config.config_overrides, 'cli_auth_credentials_store="file"')
        async with sdk.AsyncCodex(config) as codex:
            handle = await codex.login_chatgpt_device_code()
            attempt.user_code, attempt.verification_url = handle.user_code, handle.verification_url
            attempt.started.set_result(None)
            waiting = asyncio.ensure_future(handle.wait())
            deadline = time.monotonic() + WAIT_SECONDS
            while not waiting.done():
                if attempt.cancelled.is_set() or time.monotonic() > deadline:
                    waiting.cancel()
                    try:
                        await handle.cancel()
                    except Exception:
                        pass
                    attempt.status = CANCELLED if attempt.cancelled.is_set() else FAILED
                    attempt.error = None if attempt.cancelled.is_set() else "The code was not entered in time."
                    return
                await asyncio.wait([waiting], timeout=0.5)
            completed = waiting.result()
            if not completed.success:
                attempt.status, attempt.error = FAILED, str(completed.error or "Codex could not finish the sign-in.")
                return
        path = codex_home / "auth.json"
        login = parse_login(_loads(path.read_text() if path.is_file() else None), agent.get_id())
        if caller_loop is not None and caller_loop.is_running():
            # The database handle belongs to the loop the request came in on.
            asyncio.run_coroutine_threadsafe(_astore(agent, login), caller_loop).result()
        else:
            await _astore(agent, login)
        attempt.status = SIGNED_IN
    except Exception as error:
        attempt.status = FAILED
        # These errors name the agent and never repeat the file; anything else is named by its type.
        attempt.error = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        log_error(f"ChatGPT sign-in for {agent.get_id()} failed: {type(error).__name__}")
    finally:
        if not attempt.started.done():
            attempt.started.set_result(None)
        shutil.rmtree(codex_home, ignore_errors=True)
        attempt.ended.set()


def _give_up_all() -> None:
    """Give up every waiting attempt, so a process that is stopping does not wait for a code."""
    with _lock:
        waiting = list(_attempts.values())
    for attempt in waiting:
        attempt.cancelled.set()
    for attempt in waiting:
        attempt.ended.wait(10)


# A waiting attempt holds a worker thread inside the Codex SDK, and the interpreter waits for
# worker threads before it runs ordinary exit handlers. This hook runs before that wait, and
# before the one concurrent.futures registered, because it is registered after it.
_before_threads_are_joined = getattr(threading, "_register_atexit", None)
if _before_threads_are_joined is not None:
    _before_threads_are_joined(_give_up_all)


async def astart(agent: Any) -> Dict[str, Any]:
    """Start a device-code sign-in for the agent and return the link and the code to enter there.

    Starting again while one is waiting gives the earlier one up.
    """
    _refuse(agent)
    agent_id = agent.get_id()
    attempt = _Attempt(agent_id)
    with _lock:
        earlier = _attempts.get(agent_id)
        if earlier is not None:
            earlier.cancelled.set()
        _attempts[agent_id] = attempt
    try:
        caller_loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
    except RuntimeError:
        caller_loop = None
    threading.Thread(
        target=lambda: asyncio.run(_arun(agent, attempt, caller_loop)), name=f"codex-sign-in-{agent_id}", daemon=True
    ).start()
    try:
        await asyncio.wait_for(asyncio.wrap_future(attempt.started), _START_SECONDS)
    except asyncio.TimeoutError:
        attempt.cancelled.set()
        raise RuntimeError(f"Codex did not answer with a sign-in code for {agent_id}.") from None
    if attempt.status == FAILED:
        raise RuntimeError(f"Codex could not start a sign-in for {agent_id}: {attempt.error}")
    return attempt.view()


async def astatus(agent: Any) -> Dict[str, Any]:
    """Where the agent's sign-in stands: waiting for the code, signed in, failed, or not signed in."""
    from agno.agents.codex._subscription import _astored, _refreshed_at

    agent_id = agent.get_id()
    with _lock:
        attempt = _attempts.get(agent_id)
    if attempt is not None and attempt.status in (WAITING, FAILED):
        return attempt.view()
    stored = await _astored(agent) if agent.auth_json is None else None
    if stored is None:
        return {"agent_id": agent_id, "status": NOT_SIGNED_IN}
    return {"agent_id": agent_id, "status": SIGNED_IN, "last_refresh": _refreshed_at(stored).isoformat()}


async def acancel(agent: Any) -> Dict[str, Any]:
    """Give up a sign-in that is waiting for its code. A stored sign-in is left as it is."""
    with _lock:
        attempt = _attempts.pop(agent.get_id(), None)
    if attempt is not None:
        attempt.cancelled.set()
    return await astatus(agent)
