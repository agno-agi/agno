"""Service accounts for AgentOS.

Service accounts are machine identities (coding agents, chat apps, CI) authenticated by
opaque tokens following the GitHub PAT model: the token is random, only its SHA-256 hash
is stored (in the AgentOS database), the plaintext is returned exactly once at creation,
and revocation is native (see the caching note below for its timing).

Tokens look like ``agno_pat_<base62>`` and authenticate through the same middleware as
JWTs. A verified service account attaches to the request with ``user_id`` set to its
principal (``sa:<name>``) and ``scopes`` set to the account's stored scopes. Unlike JWT
claims, service account scopes are first-party ACL data owned by this AgentOS instance,
so they are enforced in every deployment mode - including ``os_security_key`` mode and
``validate=False`` mode, where JWT scopes are not.

Successful verifications are cached in-process for a short TTL (default 30s) so PAT auth
does not hit the database on every request. Revocation takes effect within that TTL
across worker processes, and immediately on the worker that processes the revoke (the
``DELETE`` handler evicts the local cache entry). Set the cache TTL to 0 for strict
instant revocation - every request verifies against the database. Token expiry is always
honored, even on a cache hit.
"""

import re
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from starlette.concurrency import run_in_threadpool

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.service_accounts import SERVICE_ACCOUNT_PRINCIPAL_PREFIX, ServiceAccount
from agno.os.scopes import AgentOSScope, check_route_scopes, parse_scope
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import hash_string_sha256

# Prefix makes tokens greppable for secret scanners.
TOKEN_PREFIX = "agno_pat_"

# How many characters of the plaintext token are stored for display purposes
# (the literal prefix plus 7 random characters).
TOKEN_DISPLAY_PREFIX_LENGTH = 16

# Run and read, nothing else. Anything broader requires an explicit request.
# config:read is included so a default token can discover what it can run
# (GET /config on REST, get_agentos_config over MCP).
DEFAULT_SERVICE_ACCOUNT_SCOPES: List[str] = [
    "agents:run",
    "teams:run",
    "workflows:run",
    "sessions:read",
    "config:read",
]

DEFAULT_EXPIRY_DAYS = 90

# Lowercase slug: no colons (cannot spoof the sa: principal namespace), no leading
# underscore (cannot collide with internal identities like __scheduler__), no @ or dots
# (cannot mimic email-shaped human subs). \Z (not $) so a trailing newline is rejected.
SERVICE_ACCOUNT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}\Z")

_BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Scope actions that make a token privileged (require an explicit override at mint time).
_PRIVILEGED_ACTIONS = {"write", "delete"}

# Resource whose scopes are always privileged: tokens that can manage tokens.
_SERVICE_ACCOUNTS_RESOURCE = "service_accounts"


def _base62_encode(data: bytes) -> str:
    num = int.from_bytes(data, "big")
    if num == 0:
        return _BASE62_ALPHABET[0]
    chars = []
    while num > 0:
        num, rem = divmod(num, 62)
        chars.append(_BASE62_ALPHABET[rem])
    return "".join(reversed(chars))


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a token. This is the only form ever stored."""
    return hash_string_sha256(token)


def generate_token() -> Tuple[str, str, str]:
    """Generate a new service account token.

    Returns:
        Tuple of (plaintext, token_hash, token_prefix). The plaintext must be returned
        to the caller exactly once and never persisted.
    """
    plaintext = TOKEN_PREFIX + _base62_encode(secrets.token_bytes(32))
    return plaintext, hash_token(plaintext), plaintext[:TOKEN_DISPLAY_PREFIX_LENGTH]


def is_valid_service_account_name(name: str) -> bool:
    """Check a service account name against the allowed slug format."""
    return bool(SERVICE_ACCOUNT_NAME_PATTERN.match(name))


def get_invalid_scopes(scopes: List[str], admin_scope: Optional[str] = None) -> List[str]:
    """Return the scope strings that do not parse as admin, global, or per-resource scopes."""
    return [s for s in scopes if parse_scope(s, admin_scope=admin_scope).scope_type == "unknown"]


def get_privileged_scopes(scopes: List[str], admin_scope: Optional[str] = None) -> List[str]:
    """Return the subset of scopes that make a token privileged.

    Privileged means: any write/delete action (2- or 3-part form), the admin scope
    (default or custom), or any scope over the service_accounts resource (tokens that
    can mint or revoke tokens).
    """
    privileged = []
    for scope in scopes:
        parsed = parse_scope(scope, admin_scope=admin_scope)
        if (
            parsed.scope_type == "admin"
            or scope == AgentOSScope.ADMIN.value
            or (parsed.action in _PRIVILEGED_ACTIONS)
            or (parsed.resource == _SERVICE_ACCOUNTS_RESOURCE)
        ):
            privileged.append(scope)
    return privileged


class VerificationStatus(str, Enum):
    """Outcome of a service account token verification."""

    OK = "ok"
    INVALID = "invalid"  # unknown, revoked, or expired token
    THROTTLED = "throttled"  # too many recent failed lookups from this client
    UNAVAILABLE = "unavailable"  # the database could not be reached or lacks support


@dataclass
class ServiceAccountVerification:
    status: VerificationStatus
    account: Optional[ServiceAccount] = None

    @property
    def ok(self) -> bool:
        return self.status == VerificationStatus.OK


class _FailedLookupLimiter:
    """Sliding-window limiter for failed token lookups.

    Only throttles the failure RESPONSE - a valid token is never blocked, so a flood
    of bad tokens cannot lock out legitimate clients even when they share a bucket.
    In-process and per-worker: with N workers the effective budget is N times larger.
    Keyed by client address, which is only meaningful behind a proxy when the server
    runs with proxy headers enabled (e.g. uvicorn --proxy-headers). Only true
    verification failures count - database errors do not.
    """

    def __init__(self, max_failures: int = 20, window_seconds: int = 60, max_entries: int = 1024):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._failures: "OrderedDict[str, List[float]]" = OrderedDict()

    def is_limited(self, key: str) -> bool:
        timestamps = self._failures.get(key)
        if not timestamps:
            return False
        cutoff = time.monotonic() - self.window_seconds
        fresh = [t for t in timestamps if t > cutoff]
        if fresh:
            self._failures[key] = fresh
        else:
            self._failures.pop(key, None)
        return len(fresh) >= self.max_failures

    def record_failure(self, key: str) -> None:
        timestamps = self._failures.setdefault(key, [])
        timestamps.append(time.monotonic())
        self._failures.move_to_end(key)
        while len(self._failures) > self.max_entries:
            self._failures.popitem(last=False)


class _VerificationCache:
    """Bounded, TTL'd LRU of successful verifications, keyed by token hash.

    Caches only valid accounts. Token expiry is still honored on every hit (the cached
    account's expires_at is immutable, so it can be re-checked against the wall clock).
    Revocation is handled out of band: the worker that processes a revoke evicts its
    entry immediately via invalidate(); other workers converge as their entry ages out
    within the TTL. TTL <= 0 disables the cache entirely (strict instant revocation).
    """

    def __init__(self, ttl_seconds: int, max_entries: int = 2048):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: "OrderedDict[str, Tuple[ServiceAccount, float]]" = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def get(self, token_hash: str) -> Optional[ServiceAccount]:
        if not self.enabled:
            return None
        entry = self._entries.get(token_hash)
        if entry is None:
            return None
        account, cached_at = entry
        if time.monotonic() - cached_at > self.ttl_seconds:
            self._entries.pop(token_hash, None)
            return None
        # Honor expiry even within the TTL window - never serve an expired account.
        if account.is_expired():
            self._entries.pop(token_hash, None)
            return None
        self._entries.move_to_end(token_hash)
        return account

    def put(self, token_hash: str, account: ServiceAccount) -> None:
        if not self.enabled:
            return
        self._entries[token_hash] = (account, time.monotonic())
        self._entries.move_to_end(token_hash)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def invalidate(self, token_hash: str) -> None:
        self._entries.pop(token_hash, None)


class ServiceAccountVerifier:
    """Verifies service account tokens against the AgentOS database.

    Supports both sync (BaseDb) and async (AsyncBaseDb) databases; sync lookups run in
    the threadpool so verification never blocks the event loop. Successful verifications
    are cached in-process for ``cache_ttl_seconds`` (0 disables the cache), so a valid
    token does not hit the database on every request; token expiry is still enforced on
    cache hits, and revoke() callers should invalidate() the entry to evict it locally.
    Successful lookups also refresh the account's last_used_at, throttled to at most one
    write per minute per token (per worker process).
    """

    def __init__(
        self,
        db: Union[BaseDb, AsyncBaseDb],
        last_used_write_interval: int = 60,
        cache_ttl_seconds: int = 30,
        cache_max_entries: int = 2048,
        last_used_max_entries: int = 2048,
    ):
        self.db = db
        self.last_used_write_interval = last_used_write_interval
        self.last_used_max_entries = last_used_max_entries
        self._limiter = _FailedLookupLimiter()
        self._cache = _VerificationCache(ttl_seconds=cache_ttl_seconds, max_entries=cache_max_entries)
        # Bounded LRU of the last last_used_at write time per account (monotonic seconds),
        # so a worker that verifies many distinct accounts cannot leak memory. Bounded like
        # its siblings _cache and _limiter; eviction only drops the throttle memory, so an
        # evicted account just gets one extra last_used_at write next time it authenticates.
        self._last_used_writes: "OrderedDict[str, float]" = OrderedDict()

    def invalidate(self, token_hash: str) -> None:
        """Evict a cached verification. Call on revoke so it takes effect immediately on
        this worker; other workers converge within the cache TTL. Idempotent."""
        self._cache.invalidate(token_hash)

    async def verify(self, token: str, client_key: Optional[str] = None) -> ServiceAccountVerification:
        """Verify a plaintext token. Returns a verification result, never raises."""
        key = client_key or "unknown"
        token_hash = hash_token(token)

        # Serve a recently-verified token from the cache (expiry re-checked in get()).
        cached = self._cache.get(token_hash)
        if cached is not None:
            await self._maybe_touch_last_used(cached)
            return ServiceAccountVerification(status=VerificationStatus.OK, account=cached)

        # The token is always looked up first: a valid token is never blocked by the
        # limiter. The limiter only shapes the FAILURE response (INVALID vs 429) so a
        # flood of bad tokens can't deny service to legitimate holders.
        try:
            if isinstance(self.db, AsyncBaseDb):
                row = await self.db.get_service_account_by_token_hash(token_hash)
            else:
                row = await run_in_threadpool(self.db.get_service_account_by_token_hash, token_hash)
        except NotImplementedError:
            log_warning("The configured database does not support service accounts")
            return ServiceAccountVerification(status=VerificationStatus.UNAVAILABLE)
        except Exception as e:
            # Fail closed on database errors: never counts toward the limiter, so a
            # DB blip cannot lock out legitimate clients.
            log_error(f"Service account lookup failed: {e}")
            return ServiceAccountVerification(status=VerificationStatus.UNAVAILABLE)

        if row is not None:
            account = ServiceAccount.from_dict(row)
            if not (account.is_revoked() or account.is_expired()):
                self._cache.put(token_hash, account)
                await self._maybe_touch_last_used(account)
                return ServiceAccountVerification(status=VerificationStatus.OK, account=account)
            # Defensive: ensure a now-revoked/expired token is not lingering in cache.
            self._cache.invalidate(token_hash)
            log_debug("Service account verification failed: token is revoked or expired")
        else:
            log_debug("Service account verification failed: unknown token")

        # Verification failed for a reason we count (unknown / revoked / expired).
        if self._limiter.is_limited(key):
            log_warning("Service account verification throttled: too many failed lookups")
            return ServiceAccountVerification(status=VerificationStatus.THROTTLED)
        self._limiter.record_failure(key)
        return ServiceAccountVerification(status=VerificationStatus.INVALID)

    async def _maybe_touch_last_used(self, account: ServiceAccount) -> None:
        # Throttle on the monotonic clock (immune to wall-clock steps that could otherwise
        # suppress writes indefinitely); persist the wall-clock time as the actual value.
        now_monotonic = time.monotonic()
        last_write = self._last_used_writes.get(account.id)
        if last_write is not None and now_monotonic - last_write < self.last_used_write_interval:
            self._last_used_writes.move_to_end(account.id)
            return
        self._last_used_writes[account.id] = now_monotonic
        self._last_used_writes.move_to_end(account.id)
        while len(self._last_used_writes) > self.last_used_max_entries:
            self._last_used_writes.popitem(last=False)
        wall_now = int(time.time())
        try:
            if isinstance(self.db, AsyncBaseDb):
                await self.db.update_service_account(account.id, return_record=False, last_used_at=wall_now)
            else:
                await run_in_threadpool(
                    self.db.update_service_account, account.id, return_record=False, last_used_at=wall_now
                )
        except Exception as e:
            log_warning(f"Could not update last_used_at for service account '{account.name}': {e}")


async def authenticate_service_account_request(
    request: Any,
    token: str,
    *,
    verifier: "ServiceAccountVerifier",
    scope_mappings: Dict[str, List[str]],
    admin_scope: Optional[str],
    user_isolation: Optional[bool] = None,
) -> Optional[Tuple[int, str, Optional[List[str]]]]:
    """Verify a PAT and attach the account identity to request.state.

    The single verify + attach + scope-enforcement path for service accounts, shared
    by the auth middleware and the REST dependency so the surfaces cannot drift.
    Scope enforcement always runs: service account scopes are first-party ACL data
    owned by this AgentOS instance, unlike JWT claims.

    Returns None on success, else (status_code, detail, required_scopes) for the
    transport to render (HTTPException on REST, JSONResponse in the middleware).
    """
    client_key = request.client.host if request.client else None
    result = await verifier.verify(token, client_key=client_key)

    if result.status == VerificationStatus.THROTTLED:
        return 429, "Too many failed authentication attempts", None
    if result.status == VerificationStatus.UNAVAILABLE:
        return 503, "Authentication is temporarily unavailable", None
    account = result.account
    if not result.ok or account is None:
        return 401, "Invalid or expired service account token", None

    request.state.authenticated = True
    request.state.user_id = account.principal
    request.state.session_id = None
    request.state.scopes = list(account.scopes)
    # Scope enforcement is always active for service accounts, so route-level
    # authorization gates (require_resource_access etc.) must be active too.
    request.state.authorization_enabled = True
    request.state.service_account_name = account.name
    if admin_scope:
        request.state.admin_scope = admin_scope
    if user_isolation is not None:
        request.state.user_isolation_enabled = user_isolation

    scope_check = check_route_scopes(
        list(account.scopes),
        scope_mappings,
        request.method,
        request.url.path,
        admin_scope=admin_scope,
    )
    request.state.required_scopes = scope_check.required_scopes
    if scope_check.accessible_resource_ids is not None:
        request.state.accessible_resource_ids = scope_check.accessible_resource_ids
    if not scope_check.allowed:
        return 403, "Insufficient permissions", scope_check.required_scopes

    log_debug(f"Service account authenticated: {account.principal}")
    return None


def get_principal(name: str) -> str:
    """Build the principal identifier attached to requests as user_id."""
    return f"{SERVICE_ACCOUNT_PRINCIPAL_PREFIX}{name}"
