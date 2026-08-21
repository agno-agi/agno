"""SuperGrok OAuth for the xAI model: device-code sign-in, token storage, and refresh."""

import asyncio
import itertools
import json
import os
import threading
import time
import weakref
from dataclasses import dataclass, field
from enum import Enum
from inspect import isawaitable, iscoroutinefunction
from os import getenv
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

from agno.exceptions import ModelAuthenticationError
from agno.utils.log import log_debug, log_warning

XAI_OAUTH_ISSUER = "https://auth.x.ai"
XAI_DEVICE_CODE_URL = "https://auth.x.ai/oauth2/device/code"
XAI_TOKEN_URL = "https://auth.x.ai/oauth2/token"
XAI_OAUTH_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"  # shared public Grok client; auth method "none"
XAI_OAUTH_SCOPE = "openid profile email offline_access grok-cli:access api:access"
REFRESH_MARGIN_SECONDS = 300  # fixed margin against the measured 21600s token lifetime

_EXPIRED_LOGIN_MESSAGE = "The SuperGrok sign-in code expired (30 minutes). Start the login again."
_INVALID_GRANT_MESSAGE = (
    "SuperGrok session expired or was revoked. Sign in again (run the device login), "
    "or set XAI_API_KEY to use pay-per-token access."
)
_UNREADABLE_ROW_MESSAGE = (
    "A stored SuperGrok session for user '{user_id}' could not be read (the encryption key may have "
    "changed). Sign in again, or restore the key it was saved with."
)
_NO_TOKEN_MESSAGE = (
    "No SuperGrok token found. Sign in with the device login, or set XAI_API_KEY to use pay-per-token access."
)
_SYNC_PATH_ASYNC_DB_WARNING = (
    "Async database backends need the async token methods (apoll_for_token / aget_access_token). "
    "Falling back to file storage."
)

# Cache for SuperGrok access tokens: {(store scope, provider, user_id, service):
# (access_token, expires_at)}. Uses double-checked locking: lock-free fast path
# for cache hits, lock only on cache miss to coordinate token refresh.
_token_cache: Dict[Tuple[str, str, str, str], Tuple[str, float]] = {}
_cache_lock = threading.Lock()
# Guards only the per-loop lock registry below - deliberately NOT _cache_lock,
# which get_access_token/force_refresh hold across a blocking HTTP refresh: the
# async path must never wait on a sync refresh just to obtain its own lock.
_async_lock_guard = threading.Lock()
_async_cache_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()

# Monotonic per-store scope tokens for the cache key: a token is never
# reissued, so a new store object reusing a collected store's id() can never
# inherit its cache entries; the finalizer registered at issuance evicts a
# dead store's entries so the cache does not accumulate. The guard is
# dedicated (never _cache_lock): _cache_scope runs on the lock-free fast path.
_db_scope_registry: "weakref.WeakKeyDictionary[Any, str]" = weakref.WeakKeyDictionary()
_db_scope_counter = itertools.count()
_scope_guard = threading.Lock()

# Serializes cache MUTATIONS (put/pop/evict/reset): an unguarded finalizer
# eviction raced concurrent pops/puts, raised mid-iteration, and silently
# stranded the dead scope's entries. Reads stay lock-free; held only around
# dict operations, never during I/O.
_cache_mutation_guard = threading.Lock()


def _evict_scope(scope: str) -> None:
    """Drop a collected store's cache entries (finalizer target - must not raise)."""
    with _cache_mutation_guard:
        for key in list(_token_cache):
            if key[0] == scope:
                _token_cache.pop(key, None)


def _reset_cache_for_tests() -> None:
    """Clear the module-level token cache and lock state so tests stay order-independent."""
    with _cache_mutation_guard:
        _token_cache.clear()
    _async_cache_locks.clear()
    _db_scope_registry.clear()


def _get_async_cache_lock() -> asyncio.Lock:
    """The asyncio lock for the RUNNING event loop.

    An asyncio.Lock binds to the event loop that first sees contention on it,
    and one process can run many loops - sequentially (asyncio.run per call)
    or concurrently in separate threads - so each loop gets its own lock in a
    weak registry. Weak keying releases never-contended entries; a CONTENDED
    lock strongly references its loop (registry -> lock -> loop), so closed
    loops are swept on each fetch. Single-flight stays per loop, which
    matches the lock-free cross-process design.
    """
    loop = asyncio.get_running_loop()
    with _async_lock_guard:
        for dead in [known for known in list(_async_cache_locks) if known.is_closed()]:
            _async_cache_locks.pop(dead, None)
        lock = _async_cache_locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _async_cache_locks[loop] = lock
    return lock


async def _maybe_await(result: Any) -> Any:
    """DB adapters ship in sync and async flavors; await only the async ones."""
    return await result if isawaitable(result) else result


@dataclass
class DeviceLoginInfo:
    """The values a user needs to complete a SuperGrok device sign-in."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DevicePollStatus(str, Enum):
    """Outcome of one device-flow poll iteration (RFC 8628 section 3.5)."""

    pending = "PENDING"
    success = "SUCCESS"
    denied = "DENIED"
    expired = "EXPIRED"


@dataclass
class DevicePollResult:
    """One poll_once outcome: what happened and how long to wait before the next poll."""

    status: DevicePollStatus
    interval: int  # wait this long before the next poll (bumped +5 after a slow_down)
    token_data: Optional[Dict[str, Any]] = None  # SUCCESS only: the stored envelope
    message: Optional[str] = None  # DENIED/EXPIRED: the drafted terminal string


@dataclass
class XAITokenManager:
    """Manages SuperGrok OAuth tokens: device sign-in, encrypted storage, and refresh.

    Tokens live on the ``agno_auth_tokens`` table when a db is given, in a 0600
    file otherwise, and in memory as a last resort. Refresh is lock-free across
    processes (the token endpoint keeps a rotation grace window) with in-process
    single-flight coordination.
    """

    db: Optional[Any] = None
    token_path: Optional[str] = None
    # Dedicated per-provider key, no AGNO_ENCRYPTION_KEY fallback: compromise
    # or rotation of one provider's key never touches another's tokens
    # (NIST SP 800-57 Pt 1 §5.2).
    encryption_key: Optional[str] = field(default_factory=lambda: getenv("XAI_TOKEN_ENCRYPTION_KEY"))
    encrypt_tokens: bool = True  # Require encryption by default; set False for local dev only
    http_client: Optional[httpx.Client] = None
    async_http_client: Optional[httpx.AsyncClient] = None
    # httpx defaults to 5s, which is too short for a device-code poll against a
    # live IdP: a sign-in that had already been approved timed out on it.
    timeout: float = 30.0
    now_fn: Callable[[], float] = time.time

    # Keyed by user_id like the row and the cache: a shared manager serves every
    # user through this last-resort store, so one slot would hand whoever saved
    # last to everyone without a row.
    _memory_rows: Dict[str, Dict[str, Any]] = field(default_factory=dict, repr=False)

    # The empty string is the deployment slot - the single-user default and the
    # fallback for a user who has not signed in personally.
    @staticmethod
    def _store_key(user_id: str = "") -> Tuple[str, str, str]:
        return ("xai", user_id, "supergrok")

    def _cache_scope(self) -> str:
        """Cache identity of THIS manager's store.

        Managers on the same store share the fast path; managers on different
        stores must never serve each other's tokens (they can hold different
        accounts). DB stores get a monotonic token that is never reissued, so
        a new store object reusing a collected store's memory address cannot
        inherit its entries; a finalizer evicts the dead store's entries.
        """
        if self.db is None:
            return f"file-{self._token_file()}"
        scope = _db_scope_registry.get(self.db)
        if scope is None:
            with _scope_guard:
                scope = _db_scope_registry.get(self.db)
                if scope is None:
                    scope = f"db-{next(_db_scope_counter)}"
                    _db_scope_registry[self.db] = scope
                    weakref.finalize(self.db, _evict_scope, scope)
        return scope

    def _cache_key(self, user_id: str = "") -> Tuple[str, str, str, str]:
        return (self._cache_scope(), *self._store_key(user_id))

    # ------------------------------------------------------------------
    # Device flow (RFC 8628)
    # ------------------------------------------------------------------

    def start_device_login(self) -> DeviceLoginInfo:
        """Start a SuperGrok device sign-in and return the codes to show the user."""
        response = self._post_form(XAI_DEVICE_CODE_URL, {"client_id": XAI_OAUTH_CLIENT_ID, "scope": XAI_OAUTH_SCOPE})
        return self._parse_device_response(response)

    async def astart_device_login(self) -> DeviceLoginInfo:
        """Start a SuperGrok device sign-in and return the codes to show the user."""
        response = await self._apost_form(
            XAI_DEVICE_CODE_URL, {"client_id": XAI_OAUTH_CLIENT_ID, "scope": XAI_OAUTH_SCOPE}
        )
        return self._parse_device_response(response)

    def poll_once(self, device_code: str, interval: int = 5, user_id: str = "") -> DevicePollResult:
        """One poll of the token endpoint (RFC 8628 section 3.5): no sleeping, no loop.

        The caller owns pacing and deadlines; result.interval is the wait
        before the next poll. SUCCESS persists through the normal save path.
        """
        response = self._post_form(XAI_TOKEN_URL, self._poll_form(device_code))
        if response.status_code == 200:
            token_data = self._build_envelope(response.json(), previous=None)
            self._save(token_data, user_id)
            return DevicePollResult(status=DevicePollStatus.success, interval=interval, token_data=token_data)
        return self._classify_poll_error(response, interval)

    async def apoll_once(self, device_code: str, interval: int = 5, user_id: str = "") -> DevicePollResult:
        """One poll of the token endpoint (RFC 8628 section 3.5): no sleeping, no loop.

        The caller owns pacing and deadlines; result.interval is the wait
        before the next poll. SUCCESS persists through the normal save path.
        """
        response = await self._apost_form(XAI_TOKEN_URL, self._poll_form(device_code))
        if response.status_code == 200:
            token_data = self._build_envelope(response.json(), previous=None)
            await self._asave(token_data, user_id)
            return DevicePollResult(status=DevicePollStatus.success, interval=interval, token_data=token_data)
        return self._classify_poll_error(response, interval)

    def poll_for_token(self, device_code: str, interval: int, deadline: float) -> Dict[str, Any]:
        """Poll the token endpoint until the user approves, per RFC 8628 section 3.5."""
        current_interval = interval
        while True:
            if self.now_fn() > deadline:
                raise ModelAuthenticationError(_EXPIRED_LOGIN_MESSAGE)
            result = self.poll_once(device_code, current_interval)
            if result.status == DevicePollStatus.success and result.token_data is not None:
                return result.token_data
            if result.status in (DevicePollStatus.denied, DevicePollStatus.expired) and result.message is not None:
                raise ModelAuthenticationError(result.message)
            current_interval = result.interval
            time.sleep(current_interval)

    async def apoll_for_token(self, device_code: str, interval: int, deadline: float) -> Dict[str, Any]:
        """Poll the token endpoint until the user approves, per RFC 8628 section 3.5."""
        current_interval = interval
        while True:
            if self.now_fn() > deadline:
                raise ModelAuthenticationError(_EXPIRED_LOGIN_MESSAGE)
            result = await self.apoll_once(device_code, current_interval)
            if result.status == DevicePollStatus.success and result.token_data is not None:
                return result.token_data
            if result.status in (DevicePollStatus.denied, DevicePollStatus.expired) and result.message is not None:
                raise ModelAuthenticationError(result.message)
            current_interval = result.interval
            await asyncio.sleep(current_interval)

    @staticmethod
    def _poll_form(device_code: str) -> Dict[str, str]:
        return {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": XAI_OAUTH_CLIENT_ID,
        }

    @staticmethod
    def _parse_device_response(response: httpx.Response) -> DeviceLoginInfo:
        if response.status_code != 200:
            raise ModelAuthenticationError(f"SuperGrok device login could not be started: {response.text}")
        data = response.json()
        return DeviceLoginInfo(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data["verification_uri"],
            # RFC 8628 section 3.3.1 makes verification_uri_complete OPTIONAL;
            # fall back to the plain URI (the user then enters the code manually)
            verification_uri_complete=data.get("verification_uri_complete") or data["verification_uri"],
            expires_in=data.get("expires_in", 1800),
            interval=data.get("interval", 5),
        )

    @staticmethod
    def _classify_poll_error(response: httpx.Response, interval: int) -> DevicePollResult:
        """Classify a non-200 poll response per RFC 8628 section 3.5; unknown errors raise."""
        error = XAITokenManager._error_code(response)
        if error == "authorization_pending":
            return DevicePollResult(status=DevicePollStatus.pending, interval=interval)
        if error == "slow_down":
            # RFC 8628 section 3.5 mandates +5 seconds; same caller action as
            # pending (wait, poll again), so not a separate status
            return DevicePollResult(status=DevicePollStatus.pending, interval=interval + 5)
        if error == "access_denied":
            return DevicePollResult(
                status=DevicePollStatus.denied,
                interval=interval,
                message="SuperGrok sign-in was denied in the browser.",
            )
        if error == "expired_token":
            return DevicePollResult(status=DevicePollStatus.expired, interval=interval, message=_EXPIRED_LOGIN_MESSAGE)
        raise ModelAuthenticationError(f"SuperGrok sign-in failed: {response.text}")

    @staticmethod
    def _error_code(response: httpx.Response) -> Optional[str]:
        try:
            body = response.json()
        except ValueError:
            return None
        return body.get("error") if isinstance(body, dict) else None

    # ------------------------------------------------------------------
    # Access tokens and refresh
    # ------------------------------------------------------------------

    def get_access_token(self, user_id: str = "") -> str:
        """The current access token, proactively refreshed inside the 300s margin.

        ``user_id`` selects the row and the cache entry; the empty string is the
        deployment slot, which is what PR 1 and PR 2 callers get unchanged.
        """
        cached = self._cached_token(user_id)
        if cached is not None:
            return cached
        with _cache_lock:
            cached = self._cached_token(user_id)
            if cached is not None:
                return cached
            token_data = self._load(user_id)
            if token_data is not None and self._is_fresh(token_data.get("expires_at")):
                # Another process refreshed already: adopt the stored token
                self._memory_rows[user_id] = token_data
                self._cache_put(token_data, user_id)
                return token_data["access_token"]
            return self._refresh_locked(token_data, user_id)

    async def aget_access_token(self, user_id: str = "") -> str:
        """The current access token, proactively refreshed inside the 300s margin.

        ``user_id`` selects the row and the cache entry; the empty string is the
        deployment slot, which is what PR 1 and PR 2 callers get unchanged.
        """
        cached = self._cached_token(user_id)
        if cached is not None:
            return cached
        async with _get_async_cache_lock():
            cached = self._cached_token(user_id)
            if cached is not None:
                return cached
            token_data = await self._aload(user_id)
            if token_data is not None and self._is_fresh(token_data.get("expires_at")):
                # Another process refreshed already: adopt the stored token
                self._memory_rows[user_id] = token_data
                self._cache_put(token_data, user_id)
                return token_data["access_token"]
            return await self._arefresh_locked(token_data, user_id)

    def force_refresh(self, user_id: str = "") -> str:
        """Refresh immediately, skipping the freshness margin (the 401 one-shot leg)."""
        with _cache_lock:
            return self._refresh_locked(self._load(user_id), user_id)

    async def aforce_refresh(self, user_id: str = "") -> str:
        """Refresh immediately, skipping the freshness margin (the 401 one-shot leg)."""
        async with _get_async_cache_lock():
            return await self._arefresh_locked(await self._aload(user_id), user_id)

    def _refresh_locked(self, previous: Optional[Dict[str, Any]], user_id: str = "") -> str:
        refresh_token = (previous or {}).get("refresh_token")
        if not refresh_token:
            raise ModelAuthenticationError(_NO_TOKEN_MESSAGE)
        # No blind retry: transport errors surface to the caller
        response = self._post_form(XAI_TOKEN_URL, self._refresh_form(refresh_token))
        if response.status_code == 200:
            token_data = self._build_envelope(response.json(), previous=previous)
            # Always persist the newest rotated refresh token immediately
            self._save(token_data, user_id)
            return token_data["access_token"]
        if self._error_code(response) == "invalid_grant":
            self._delete_stored_token(user_id)
            raise ModelAuthenticationError(_INVALID_GRANT_MESSAGE)
        raise ModelAuthenticationError(f"SuperGrok token refresh failed: {response.text}")

    async def _arefresh_locked(self, previous: Optional[Dict[str, Any]], user_id: str = "") -> str:
        refresh_token = (previous or {}).get("refresh_token")
        if not refresh_token:
            raise ModelAuthenticationError(_NO_TOKEN_MESSAGE)
        # No blind retry: transport errors surface to the caller
        response = await self._apost_form(XAI_TOKEN_URL, self._refresh_form(refresh_token))
        if response.status_code == 200:
            token_data = self._build_envelope(response.json(), previous=previous)
            # Always persist the newest rotated refresh token immediately
            await self._asave(token_data, user_id)
            return token_data["access_token"]
        if self._error_code(response) == "invalid_grant":
            await self._adelete_stored_token(user_id)
            raise ModelAuthenticationError(_INVALID_GRANT_MESSAGE)
        raise ModelAuthenticationError(f"SuperGrok token refresh failed: {response.text}")

    @staticmethod
    def _refresh_form(refresh_token: str) -> Dict[str, str]:
        return {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": XAI_OAUTH_CLIENT_ID}

    def _build_envelope(self, response_json: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        # An HTTP 200 does not guarantee a token body (proxies and error-in-200
        # responses exist): reject cleanly instead of KeyError-ing
        if "access_token" not in response_json:
            raise ModelAuthenticationError(f"SuperGrok token response is missing access_token: {response_json}")
        previous = previous or {}
        return {
            "access_token": response_json["access_token"],
            # Rotation-tolerant: keep the old refresh token when none is returned
            "refresh_token": response_json.get("refresh_token") or previous.get("refresh_token"),
            # id_token arrives on the initial grant only, never on refresh: keep the last seen one
            "id_token": response_json.get("id_token") or previous.get("id_token"),
            "token_type": response_json.get("token_type", "Bearer"),
            "scope": response_json.get("scope", XAI_OAUTH_SCOPE),
            "expires_at": int(self.now_fn()) + response_json.get("expires_in", 21600),
            "token_endpoint": XAI_TOKEN_URL,
        }

    def _is_fresh(self, expires_at: Any) -> bool:
        return float(expires_at or 0) - self.now_fn() > REFRESH_MARGIN_SECONDS

    def _cached_token(self, user_id: str = "") -> Optional[str]:
        cached = _token_cache.get(self._cache_key(user_id))
        if cached is not None:
            access_token, expires_at = cached
            if self._is_fresh(expires_at):
                return access_token
        return None

    def _cache_put(self, token_data: Dict[str, Any], user_id: str = "") -> None:
        with _cache_mutation_guard:
            _token_cache[self._cache_key(user_id)] = (
                token_data["access_token"],
                float(token_data.get("expires_at") or 0),
            )

    # ------------------------------------------------------------------
    # Storage: db row (Google auth-token shape), 0600 file, or memory
    # ------------------------------------------------------------------

    def _save(self, token_data: Dict[str, Any], user_id: str = "") -> None:
        self._memory_rows[user_id] = token_data
        self._cache_put(token_data, user_id)
        payload = self._encrypt_for_save(token_data)
        if payload is None:
            return
        if self.db is not None:
            if iscoroutinefunction(self.db.upsert_auth_token):
                # Falls through to the file store, like an unsupported backend
                log_warning(_SYNC_PATH_ASYNC_DB_WARNING)
            else:
                try:
                    # Adapters swallow their own errors and signal failure by returning None
                    if self.db.upsert_auth_token(self._db_row(token_data, payload, user_id)) is None:
                        log_warning("Could not persist SuperGrok token to the database; token kept in memory only")
                    return
                except NotImplementedError:
                    # An unsupported backend falls through to the file store;
                    # a real DB error does not (the row may still exist).
                    log_warning("Database does not support auth token storage")
                except Exception as e:
                    log_debug(f"Could not save token to DB: {e}")
                    return
        self._write_file_for(payload, user_id)

    async def _asave(self, token_data: Dict[str, Any], user_id: str = "") -> None:
        self._memory_rows[user_id] = token_data
        self._cache_put(token_data, user_id)
        payload = self._encrypt_for_save(token_data)
        if payload is None:
            return
        if self.db is not None:
            try:
                # Adapters swallow their own errors and signal failure by returning None
                if await _maybe_await(self.db.upsert_auth_token(self._db_row(token_data, payload, user_id))) is None:
                    log_warning("Could not persist SuperGrok token to the database; token kept in memory only")
                return
            except NotImplementedError:
                log_warning("Database does not support auth token storage")
            except Exception as e:
                log_debug(f"Could not save token to DB: {e}")
                return
        self._write_file_for(payload, user_id)

    def _load(self, user_id: str = "") -> Optional[Dict[str, Any]]:
        payload = self._read_store(user_id)
        if payload is None:
            return self._memory_rows.get(user_id)
        return self._decrypted_or_raise(payload, user_id)

    async def _aload(self, user_id: str = "") -> Optional[Dict[str, Any]]:
        payload = await self._aread_store(user_id)
        if payload is None:
            return self._memory_rows.get(user_id)
        return self._decrypted_or_raise(payload, user_id)

    def _decrypted_or_raise(self, payload: Dict[str, Any], user_id: str) -> Optional[Dict[str, Any]]:
        """Decrypt a stored row; an identified user's unreadable row must not read as absent.

        The deployment slot keeps PR 1's behaviour and degrades to signed-out. For
        an identified user that same degrade would fall through to the shared
        subscription and bill it for someone who is signed in, so it surfaces.
        """
        token_data = self._decrypt_payload(payload)
        if token_data is None and user_id:
            raise ModelAuthenticationError(_UNREADABLE_ROW_MESSAGE.format(user_id=user_id))
        return token_data

    def _read_store(self, user_id: str = "") -> Optional[Dict[str, Any]]:
        if self.db is not None:
            if iscoroutinefunction(self.db.get_auth_token):
                log_warning(_SYNC_PATH_ASYNC_DB_WARNING)
            else:
                try:
                    row = self.db.get_auth_token(*self._store_key(user_id))
                    return row.get("token_data") if row else None
                except NotImplementedError:
                    log_warning("Database does not support auth token storage")
                except Exception as e:
                    log_debug(f"Could not load token from DB: {e}")
                    return None
        return self._read_file_for(user_id)

    async def _aread_store(self, user_id: str = "") -> Optional[Dict[str, Any]]:
        if self.db is not None:
            try:
                row = await _maybe_await(self.db.get_auth_token(*self._store_key(user_id)))
                return row.get("token_data") if row else None
            except NotImplementedError:
                log_warning("Database does not support auth token storage")
            except Exception as e:
                log_debug(f"Could not load token from DB: {e}")
                return None
        return self._read_file_for(user_id)

    def _decrypt_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        from agno.utils.encryption import decrypt_dict, is_encrypted

        if not is_encrypted(payload):
            return payload
        if not self.encryption_key:
            # No AGNO_ENCRYPTION_KEY fallback on read either: decrypt_dict would fall
            # back to it when handed key=None (see the encryption_key field comment).
            log_warning("Could not decrypt stored SuperGrok token: XAI_TOKEN_ENCRYPTION_KEY is not set")
            return None
        try:
            return decrypt_dict(payload, key=self.encryption_key)
        except ValueError as e:
            # Warning, not debug: a headless deployment cannot re-auth interactively,
            # so silently losing the stored session is the worse failure.
            log_warning(f"Could not decrypt stored SuperGrok token: {e}")
            return None

    def _encrypt_for_save(self, token_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.encrypt_tokens:
            log_warning("Saving SuperGrok token WITHOUT encryption (encrypt_tokens=False).")
            return dict(token_data)
        if not self.encryption_key:
            log_warning(
                "Token encryption required but no key configured. Token NOT saved. "
                "Set XAI_TOKEN_ENCRYPTION_KEY env var, or pass encrypt_tokens=False for local dev."
            )
            return None
        from agno.utils.encryption import encrypt_dict

        return encrypt_dict(token_data, key=self.encryption_key)

    def _db_row(self, token_data: Dict[str, Any], payload: Dict[str, Any], user_id: str = "") -> Dict[str, Any]:
        provider, user_id, service = self._store_key(user_id)
        return {
            "provider": provider,
            "user_id": user_id,
            "service": service,
            "token_data": payload,
            "granted_scopes": (token_data.get("scope") or "").split(),
        }

    def _token_file(self) -> Path:
        return Path(self.token_path or "xai_token.json")

    def _read_file_for(self, user_id: str) -> Optional[Dict[str, Any]]:
        """The file store, but only for the deployment slot.

        One file holds one session, so serving it to an identified user would
        hand them whoever signed in on this machine. An absent per-user token
        is not an error - resolution falls through to the deployment slot.
        """
        if user_id:
            log_debug("Per-user SuperGrok tokens need a database; the file store is single-user")
            return None
        return self._read_file()

    def _write_file_for(self, payload: Dict[str, Any], user_id: str) -> None:
        """Persist to the file store, or refuse when the token belongs to a user."""
        if user_id:
            log_warning(
                "Per-user SuperGrok tokens need a database; this token is kept in memory "
                "for this process only. Pass db= to persist it."
            )
            return
        self._write_file(payload)

    def _read_file(self) -> Optional[Dict[str, Any]]:
        path = self._token_file()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            log_warning(f"Could not read SuperGrok token file {path}: {e}")
            return None

    def _write_file(self, payload: Dict[str, Any]) -> None:
        path = self._token_file()
        try:
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as handle:
                json.dump(payload, handle)
            # O_CREAT's mode only applies to newly created files; enforce 0600 on overwrite too
            os.chmod(path, 0o600)
        except OSError as e:
            log_warning(f"Could not persist SuperGrok token to {path}: {e}. Token kept in memory only.")

    def sign_out(self, user_id: str = "") -> None:
        """Forget the stored SuperGrok session on this machine.

        Wipes the stored row (db or file), the process cache entry, and the
        in-memory copy - durable copy first. Idempotent when nothing is
        stored. Never calls the revocation endpoint: the grant lives on
        server-side until it expires or is revoked from the account page.
        """
        self._delete_stored_token(user_id)

    async def asign_out(self, user_id: str = "") -> None:
        """Forget the stored SuperGrok session on this machine.

        Wipes the stored row (db or file), the process cache entry, and the
        in-memory copy - durable copy first. Idempotent when nothing is
        stored. Never calls the revocation endpoint: the grant lives on
        server-side until it expires or is revoked from the account page.
        """
        await self._adelete_stored_token(user_id)

    def _delete_stored_token(self, user_id: str = "") -> None:
        # Durable copy first: the persisted row dies before the in-process
        # copies, so no later process can resurrect a session whose live
        # state is already gone
        self._delete_stored_row(user_id)
        with _cache_mutation_guard:
            _token_cache.pop(self._cache_key(user_id), None)
        self._memory_rows.pop(user_id, None)

    async def _adelete_stored_token(self, user_id: str = "") -> None:
        # Durable copy first: the persisted row dies before the in-process
        # copies, so no later process can resurrect a session whose live
        # state is already gone
        await self._adelete_stored_row(user_id)
        with _cache_mutation_guard:
            _token_cache.pop(self._cache_key(user_id), None)
        self._memory_rows.pop(user_id, None)

    def _delete_stored_row(self, user_id: str = "") -> None:
        if self.db is not None:
            if iscoroutinefunction(self.db.delete_auth_token):
                log_warning(_SYNC_PATH_ASYNC_DB_WARNING)
            else:
                try:
                    if not self.db.delete_auth_token(*self._store_key(user_id)):
                        log_debug("No SuperGrok token row deleted")
                    return
                except NotImplementedError:
                    log_warning("Database does not support auth token deletion")
                except Exception as e:
                    log_debug(f"Could not delete token from DB: {e}")
                    return
        if user_id:
            # The file store holds ONE session, the deployment's - reads and writes
            # already refuse an identified user, so deleting must too.
            return
        try:
            self._token_file().unlink(missing_ok=True)
        except OSError as e:
            log_debug(f"Could not delete SuperGrok token file: {e}")

    async def _adelete_stored_row(self, user_id: str = "") -> None:
        if self.db is not None:
            try:
                if not await _maybe_await(self.db.delete_auth_token(*self._store_key(user_id))):
                    log_debug("No SuperGrok token row deleted")
                return
            except NotImplementedError:
                log_warning("Database does not support auth token deletion")
            except Exception as e:
                log_debug(f"Could not delete token from DB: {e}")
                return
        if user_id:
            # The file store holds ONE session, the deployment's - reads and writes
            # already refuse an identified user, so deleting must too.
            return
        try:
            self._token_file().unlink(missing_ok=True)
        except OSError as e:
            log_debug(f"Could not delete SuperGrok token file: {e}")

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _post_form(self, url: str, data: Dict[str, str]) -> httpx.Response:
        if self.http_client is not None:
            return self.http_client.post(url, data=data)
        with httpx.Client(timeout=self.timeout) as client:
            return client.post(url, data=data)

    async def _apost_form(self, url: str, data: Dict[str, str]) -> httpx.Response:
        if self.async_http_client is not None:
            return await self.async_http_client.post(url, data=data)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await client.post(url, data=data)
