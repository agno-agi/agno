"""A Codex agent signed in with a ChatGPT subscription instead of an API key.

The login is the contents of an ``auth.json`` written by ``codex login``. Codex replaces the
tokens in that file while it works, and the old ones stop working, so three things hold:

- The copy Codex last wrote is the one the next run starts from. It is kept in the agent's
  database, in the auth tokens table, encrypted with a key made from the login the agent
  was given. Only a process that holds that login can read the row. A different login given
  to the agent later cannot read it, and replaces it.
- A copy is never replaced by an older one, wherever it is written.
- One agent runs one piece of work at a time, so two runs never refresh the same login.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import random
import re
import threading
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Set

from agno.db.base import AsyncBaseDb
from agno.exceptions import AgentBusyError
from agno.utils.log import log_error, log_warning

# provider column of the auth tokens table; the service column is the agent id.
_PROVIDER = "codex"
_EXEC_SECONDS = 30.0
_MAX_LOGIN_BYTES = 256 * 1024

# Run inside the sandbox. The path is the one the sandbox runtime gives Codex as CODEX_HOME.
_PATH = "os.path.join(os.environ.get('AGNO_SANDBOX_RUNTIME_DIR', '/runtime'), 'native', 'codex', 'auth.json')"
_READ = f"import os, sys\np = {_PATH}\nsys.stdout.write(open(p).read() if os.path.isfile(p) else '')\n"
# Written in place: a temporary file beside it would be a second copy a checkpoint could pick up.
_WRITE = (
    f"import os, sys\np = {_PATH}\nos.makedirs(os.path.dirname(p), exist_ok=True)\n"
    "f = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)\n"
    "os.write(f, sys.stdin.buffer.read())\nos.close(f)\nos.chmod(p, 0o600)\n"
)

# How long a run waits for a busy agent's slot before it gives up, and how often it asks again.
WAIT_SECONDS = 30 * 60.0
_ASK_AGAIN_SECONDS = 2.0


def _minutes(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


_busy_lock = threading.Lock()
_busy: Set[str] = set()


def parse_login(value: Any, agent_id: str) -> Dict[str, Any]:
    """The login as a mapping. The error never repeats any part of the value."""
    reason = "is not the contents of an auth.json"
    if isinstance(value, str):
        if not value.strip():
            reason = "is empty"
        value = _loads(value)
    if isinstance(value, dict):
        tokens = value.get("tokens")
        if isinstance(tokens, dict) and isinstance(tokens.get("refresh_token"), str) and tokens["refresh_token"]:
            return value
        reason = "has no ChatGPT sign-in in it (an auth.json made with an API key cannot be used)"
    raise ValueError(
        f"{agent_id} is set to run on a ChatGPT subscription, but its auth_json {reason}. Run `codex login` and pass "
        "the contents of the auth.json it writes. OPENAI_API_KEY was not used."
    )


def check(agent: Any) -> None:
    """Raise when the agent's login cannot be used, or cannot be kept safely after a run."""
    parse_login(agent.auth_json, agent.get_id())
    if _stores_logins(agent.db):
        try:
            import cryptography.fernet  # noqa: F401
        except ImportError:
            raise ImportError(
                f"{agent.get_id()} keeps its ChatGPT sign-in (auth.json) encrypted in its database and needs `cryptography`. "
                "Install it with `pip install cryptography`."
            ) from None


def _refreshed_at(login: Optional[Dict[str, Any]]) -> datetime:
    """When Codex last refreshed this login; the earliest possible time when it does not say."""
    text = (login or {}).get("last_refresh")
    if isinstance(text, str):
        # Codex writes up to nine fractional digits; datetime reads six.
        text = re.sub(r"(\.\d{6})\d+", r"\1", text.strip().replace("Z", "+00:00"))
        with suppress(ValueError):
            parsed = datetime.fromisoformat(text)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _is_chatgpt_sign_in(login: Any) -> bool:
    return isinstance(login, dict) and isinstance(login.get("tokens"), dict) and bool(login["tokens"])


def _newer(login: Any, than: Any) -> bool:
    """Whether ``login`` is a ChatGPT sign-in refreshed after ``than``."""
    return _is_chatgpt_sign_in(login) and (not _is_chatgpt_sign_in(than) or _refreshed_at(login) > _refreshed_at(than))


def _loads(text: Optional[str]) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def _key(seed: Dict[str, Any]) -> str:
    """The key the stored copy is encrypted with, made from the login the agent was given."""
    secret = "agno-codex-plan-login:" + seed["tokens"]["refresh_token"]
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()


def _stores_logins(db: Any) -> bool:
    return db is not None and hasattr(db, "get_auth_token") and hasattr(db, "upsert_auth_token")


async def aload(agent: Any) -> Dict[str, Any]:
    """The login the next run starts from: the stored copy when this agent's login can read it, else that login."""
    from agno.agents._hitl import db_call
    from agno.utils.encryption import decrypt_dict, is_encrypted

    seed = parse_login(agent.auth_json, agent.get_id())
    if not _stores_logins(agent.db):
        return seed
    try:
        row = await db_call(agent.db, "get_auth_token", _PROVIDER, None, agent.get_id())
    except NotImplementedError:
        return seed
    data = (row or {}).get("token_data")
    if not isinstance(data, dict) or not is_encrypted(data):
        return seed
    try:
        stored = decrypt_dict(data, key=_key(seed))
    except ValueError:
        # Saved from another login: the one this agent has now replaces it.
        return seed
    return stored if _newer(stored, seed) else seed


async def asave(agent: Any, login: Any) -> None:
    """Keep ``login`` as the copy the next run starts from, unless the kept one is as new."""
    from agno.agents._hitl import db_call
    from agno.utils.encryption import encrypt_dict

    if not _stores_logins(agent.db) or not _newer(login, await aload(agent)):
        return
    seed = parse_login(agent.auth_json, agent.get_id())
    row = {
        "provider": _PROVIDER,
        "user_id": None,
        "service": agent.get_id(),
        "token_data": encrypt_dict(login, key=_key(seed)),
        "granted_scopes": [],
    }
    saved = None
    with suppress(NotImplementedError):
        saved = await db_call(agent.db, "upsert_auth_token", row)
    if saved is None:
        log_error(
            f"Could not save the ChatGPT sign-in (auth.json) {agent.get_id()} refreshed during its run. Its next run starts "
            "from the previous copy, which may no longer work; if it fails to sign in, give it a new login."
        )


async def _settle(agent: Any, login: Any) -> None:
    """Save after a run, without letting a failed save replace the run's own outcome."""
    try:
        await asave(agent, login)
    except Exception as error:
        log_error(
            f"Could not save the ChatGPT sign-in (auth.json) of {agent.get_id()} after its run: {type(error).__name__}"
        )


class SandboxLogin:
    """Writes one agent's login into its sandbox before a turn and saves the refreshed copy after."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    async def _read(self, provider: Any, handle: Any) -> Any:
        from agno.sandbox.base import SandboxError

        result = await provider.aexec(
            handle, ["python", "-I", "-c", _READ], timeout=_EXEC_SECONDS, max_output_bytes=_MAX_LOGIN_BYTES
        )
        if result.exit_code or result.timed_out or result.output_limited:
            raise SandboxError(
                f"Could not read the ChatGPT sign-in (auth.json) of {self.agent.get_id()} from its sandbox"
            )
        return _loads(result.stdout)

    async def ainstall(self, provider: Any, handle: Any) -> None:
        from agno.sandbox.base import SandboxError

        login = await aload(self.agent)
        # A sandbox kept from this session's last turn, or one this run is reattaching to, may
        # hold a copy Codex refreshed after the stored one.
        if _newer(await self._read(provider, handle), login):
            return
        result = await provider.aexec(
            handle, ["python", "-I", "-c", _WRITE], stdin=json.dumps(login).encode(), timeout=_EXEC_SECONDS
        )
        if result.exit_code or result.timed_out:
            raise SandboxError(
                f"Could not write the ChatGPT sign-in (auth.json) of {self.agent.get_id()} into its sandbox"
            )

    async def acollect(self, provider: Any, handle: Any) -> None:
        """Best effort: the sandbox may already be gone, and the turn's outcome must stand either way."""
        try:
            login = await self._read(provider, handle)
        except Exception as error:
            log_warning(
                f"Could not read the ChatGPT sign-in (auth.json) of {self.agent.get_id()} back from its sandbox: "
                f"{type(error).__name__}"
            )
            return
        await _settle(self.agent, login)


def home(agent: Any, env: Optional[Dict[str, str]]) -> Path:
    """The CODEX_HOME of an agent that runs on this host: the one its env names, else one of its own."""
    configured = (env or {}).get("CODEX_HOME")
    return Path(configured) if configured else Path.home() / ".agno" / "codex" / agent.get_id()


def _write_home(path: Path, login: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".agno")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(login))
    os.replace(temporary, path)


@asynccontextmanager
async def host_login(agent: Any, codex_home: Path) -> AsyncIterator[None]:
    """Put the agent's login in its CODEX_HOME on this host for one run, and save the refreshed copy after."""
    path = codex_home / "auth.json"
    login = await aload(agent)
    if not _newer(_loads(path.read_text() if path.is_file() else None), login):
        _write_home(path, login)
    try:
        yield
    finally:
        await _settle(agent, _loads(path.read_text() if path.is_file() else None))


def _lock_key(agent_id: str) -> int:
    digest = hashlib.sha256(("agno-codex-plan-login:" + agent_id).encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _database_lock(db: Any, agent_id: str) -> Optional[Callable[[], Awaitable[None]]]:
    """Take the agent's lock across every process on a PostgreSQL database.

    Returns how to release it, or None when another process holds it. The lock belongs to one
    connection, held until release, so a process that dies gives it up.
    """
    from sqlalchemy import text

    engine = db.db_engine
    key = {"key": _lock_key(agent_id)}
    take, give = text("SELECT pg_try_advisory_lock(:key)"), text("SELECT pg_advisory_unlock(:key)")
    if isinstance(db, AsyncBaseDb):
        connection = await engine.connect()
        try:
            held = (await connection.execute(take, key)).scalar()
            # The lock outlives the transaction; do not leave one open for the length of a run.
            await connection.commit()
        except BaseException:
            await connection.close()
            raise
        if not held:
            await connection.close()
            return None

        async def release_async() -> None:
            try:
                await connection.execute(give, key)
            except Exception:
                await connection.invalidate()
            finally:
                await connection.close()

        return release_async

    def acquire() -> Any:
        connection = engine.connect()
        try:
            held = connection.execute(take, key).scalar()
            connection.commit()
            if held:
                return connection
        except BaseException:
            connection.close()
            raise
        connection.close()
        return None

    connection = await asyncio.to_thread(acquire)
    if connection is None:
        return None

    def release_sync() -> None:
        try:
            connection.execute(give, key)
        except Exception:
            connection.invalidate()
        finally:
            connection.close()

    async def release() -> None:
        await asyncio.to_thread(release_sync)

    return release


def _is_postgres(db: Any) -> bool:
    return getattr(getattr(getattr(db, "db_engine", None), "dialect", None), "name", None) == "postgresql"


async def _take(agent: Any) -> Optional[Callable[[], Awaitable[None]]]:
    """Take the agent's one slot, in this process and across processes; None when it is taken."""
    agent_id = agent.get_id()
    with _busy_lock:
        if agent_id in _busy:
            return None
        _busy.add(agent_id)
    release_database: Optional[Callable[[], Awaitable[None]]] = None
    try:
        if _is_postgres(agent.db):
            release_database = await _database_lock(agent.db, agent_id)
            if release_database is None:
                _busy.discard(agent_id)
                return None
    except BaseException:
        _busy.discard(agent_id)
        raise

    async def release() -> None:
        try:
            if release_database is not None:
                await release_database()
        finally:
            _busy.discard(agent_id)

    return release


async def _finish(task: "asyncio.Future[Any]") -> Any:
    """Wait for work that must not be abandoned half way, through any cancellation of the caller."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.wait([task])
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        if not task.cancelled() and task.exception() is None and task.result() is not None:
            await _finish(asyncio.ensure_future(task.result()()))
        raise asyncio.CancelledError()
    return task.result()


@asynccontextmanager
async def one_at_a_time(agent: Any, wait: bool = False, run_id: Optional[str] = None) -> AsyncIterator[None]:
    """Hold the agent's one slot for a run.

    Without ``wait``, AgentBusyError is raised at once when another run has the slot. That is the
    answer for a caller who should not be kept waiting, and for a run the durable queue owns: the
    queue takes that run back and starts it again when the agent is free.

    With ``wait``, the run waits its turn: it asks again every few seconds until the slot is free,
    for up to WAIT_SECONDS, and then raises AgentBusyError saying it waited that long. Turns are
    not taken in order: whichever waiting run asks first after a release gets the slot. A run
    cancelled while it waits (``run_id``) raises RunCancelledException and never runs on the slot:
    it stops waiting, or gives the slot straight back when it came free after the cancel.
    """
    from agno.exceptions import RunCancelledException
    from agno.run.cancel import ais_cancelled

    agent_id = agent.get_id()
    deadline = time.monotonic() + WAIT_SECONDS
    waited = False
    while True:
        release = await _finish(asyncio.ensure_future(_take(agent)))
        if release is not None:
            break
        waited = True
        if not wait:
            raise AgentBusyError(
                f"{agent_id} is busy. It runs on a ChatGPT subscription, one piece of work at a time. "
                "Try again when its current run finishes.",
                agent_id=agent_id,
            )
        if time.monotonic() >= deadline:
            raise AgentBusyError(
                f"{agent_id} was still busy after this work waited {_minutes(WAIT_SECONDS)} for its turn, so it "
                "was not started. It runs on a ChatGPT subscription, one piece of work at a time. Run it again "
                "when its current work finishes.",
                agent_id=agent_id,
            )
        if run_id is not None and await ais_cancelled(run_id):
            raise RunCancelledException(run_id)
        # A little apart, so runs waiting on one agent do not all ask at the same moment.
        await asyncio.sleep(_ASK_AGAIN_SECONDS + random.uniform(0, _ASK_AGAIN_SECONDS / 4))
    try:
        # The slot may have come free after the waiting run was cancelled: that run gives it back.
        if waited and run_id is not None and await ais_cancelled(run_id):
            raise RunCancelledException(run_id)
        yield
    finally:
        await _finish(asyncio.ensure_future(release()))
