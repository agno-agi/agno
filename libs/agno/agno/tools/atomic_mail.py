import asyncio
import base64
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from os import cpu_count, getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info

DEFAULT_AUTH_URL = "https://auth.atomicmail.ai"
DEFAULT_API_URL = "https://api.atomicmail.ai"

# Scrypt parameters and salt required by AtomicMail's proof-of-work signup endpoint.
# See https://atomicmail.ai/llms.txt for the documented protocol.
POW_SCRYPT_SALT = "0b980734412c292d6549110276b604ab1dea4883bd460d77d1b984adf8bca083"
POW_SCRYPT_N = 16_384
POW_SCRYPT_R = 8
POW_SCRYPT_P = 1
POW_HASH_BYTES = 64

JMAP_MAIL_URN = "urn:ietf:params:jmap:mail"


class AtomicMailTools(Toolkit):
    """Tools for registering and operating an AtomicMail inbox for AI agents.

    AtomicMail (https://atomicmail.ai) issues email inboxes through an autonomous,
    proof-of-work signup flow with no domain setup or human verification step, then
    exposes the inbox over JMAP. Once `register_inbox` has been called, the API key
    is cached to disk (default `~/.atomicmail/credentials.json`) so `send_email` and
    `list_inbox` can reuse the same inbox across agent runs. Override the location
    with `credentials_dir` or the `ATOMIC_MAIL_CREDENTIALS_DIR` environment variable.
    """

    def __init__(
        self,
        credentials_dir: Optional[str] = None,
        auth_url: str = DEFAULT_AUTH_URL,
        api_url: str = DEFAULT_API_URL,
        enable_register_inbox: bool = True,
        enable_send_email: bool = True,
        enable_list_inbox: bool = True,
        all: bool = False,
        timeout: int = 30,
        pow_timeout: Optional[float] = 300.0,
        pow_workers: Optional[int] = None,
        **kwargs,
    ):
        """Initialize AtomicMail tools.

        Args:
            credentials_dir: Directory to store/read `credentials.json` in. Defaults to
                `ATOMIC_MAIL_CREDENTIALS_DIR` or `~/.atomicmail`.
            auth_url: AtomicMail auth service base URL.
            api_url: AtomicMail JMAP API base URL.
            enable_register_inbox: Register the register_inbox tool (sync and async).
            enable_send_email: Register the send_email tool (sync and async).
            enable_list_inbox: Register the list_inbox tool (sync and async).
            all: Register all tools regardless of individual flags.
            timeout: Per-request timeout in seconds.
            pow_timeout: Wall-clock cap (seconds) for the proof-of-work solve, which is
                otherwise unbounded and driven by a server-set difficulty. A solve that
                exceeds it fails with an `error` result instead of hanging. Set to `None`
                to wait indefinitely.
            pow_workers: Threads searching the proof-of-work nonce space in parallel.
                Defaults to `min(4, cpu_count())`; `1` searches sequentially.
        """
        self.auth_url = auth_url.rstrip("/")
        self.api_url = api_url.rstrip("/")
        self.pow_timeout = pow_timeout
        self.pow_workers = pow_workers or min(4, cpu_count() or 1)
        # The resolved JMAP context (capability token, account and inbox mailbox ids) is
        # reused across tool calls until the token nears expiry or the stored api_key
        # changes: every call otherwise repeats the whole proof-of-work handshake for
        # one JMAP request.
        self.__jmap_context: Optional[Dict[str, Any]] = None
        self.__jmap_context_expiry = 0.0
        self.credentials_path = self._resolve_credentials_path(credentials_dir)

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []
        if all or enable_register_inbox:
            tools.append(self.register_inbox)
            async_tools.append((self.aregister_inbox, "register_inbox"))
        if all or enable_send_email:
            tools.append(self.send_email)
            async_tools.append((self.asend_email, "send_email"))
        if all or enable_list_inbox:
            tools.append(self.list_inbox)
            async_tools.append((self.alist_inbox, "list_inbox"))

        super().__init__(name="atomic_mail_tools", tools=tools, async_tools=async_tools, timeout=timeout, **kwargs)

    # -- credential storage ---------------------------------------------------------

    @staticmethod
    def _resolve_credentials_path(credentials_dir: Optional[str]) -> Path:
        directory = credentials_dir or getenv("ATOMIC_MAIL_CREDENTIALS_DIR") or "~/.atomicmail"
        return Path(directory).expanduser() / "credentials.json"

    def _load_credentials(self) -> Optional[Dict[str, Any]]:
        """Return the stored credentials, or `None` if none have been written yet.

        A present-but-unreadable file (truncated, non-JSON, permission error) raises
        instead of returning `None`: treating corruption as "nothing registered" would
        let `register_inbox` sail past its already-registered guard and overwrite a live
        inbox's api_key with a freshly signed-up one.
        """
        if not self.credentials_path.exists():
            return None
        try:
            return json.loads(self.credentials_path.read_text())
        except (OSError, ValueError) as e:
            raise ValueError(
                f"AtomicMail credentials at {self.credentials_path} exist but could not be read ({e}). "
                "Fix or remove the file; refusing to overwrite it with a new registration."
            ) from e

    def _save_credentials(self, credentials: Dict[str, Any]) -> None:
        self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
        self.credentials_path.write_text(json.dumps(credentials, indent=2))
        try:
            self.credentials_path.chmod(0o600)
        except OSError:
            pass

    def _require_credentials(self) -> Dict[str, Any]:
        credentials = self._load_credentials()
        if not credentials or not credentials.get("api_key"):
            raise ValueError("No AtomicMail inbox registered yet. Call register_inbox first.")
        return credentials

    # -- pure helpers shared by the sync and async paths -----------------------------
    # These never touch the network; only the HTTP client calls below differ between
    # the sync (httpx.Client) and async (httpx.AsyncClient) tool variants.

    @staticmethod
    def _decode_jwt_payload(token: str) -> Dict[str, Any]:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        return json.loads(decoded)

    @staticmethod
    def _has_leading_zero_bits(data: bytes, bits: int) -> bool:
        full_bytes, remaining_bits = divmod(bits, 8)
        if any(byte != 0 for byte in data[:full_bytes]):
            return False
        if remaining_bits:
            mask = (0xFF << (8 - remaining_bits)) & 0xFF
            if data[full_bytes] & mask != 0:
                return False
        return True

    @classmethod
    def _solve_pow(
        cls, challenge: str, difficulty: int, max_seconds: Optional[float] = None, workers: int = 1
    ) -> Dict[str, str]:
        """Grind nonces until the scrypt digest has `difficulty` leading zero bits.

        `difficulty` comes from the (unverified) challenge JWT, so the loop is bounded
        by `max_seconds` of wall-clock time to keep a misconfigured or implausibly high
        difficulty from hanging the caller forever. `None` waits indefinitely.

        `hashlib.scrypt` releases the GIL, so `workers` threads each search an
        interleaved slice of the nonce space (`start, start + workers, ...`); the first
        valid digest wins and the others stop. `workers=1` is the plain sequential search
        (nonces 0, 1, 2, ...).
        """
        deadline = None if max_seconds is None else time.monotonic() + max_seconds
        stop = threading.Event()
        solved: Dict[str, str] = {}

        def search(start: int) -> None:
            nonce = start
            while not stop.is_set():
                digest = hashlib.scrypt(
                    f"{challenge}:{nonce}".encode(),
                    salt=POW_SCRYPT_SALT.encode(),
                    n=POW_SCRYPT_N,
                    r=POW_SCRYPT_R,
                    p=POW_SCRYPT_P,
                    dklen=POW_HASH_BYTES,
                )
                if cls._has_leading_zero_bits(digest, difficulty):
                    # Two workers finishing valid hashes at once both write here; either
                    # pair is a genuine proof, and `stop` bounds it to hashes already in flight.
                    solved.update(powHex=digest.hex(), nonce=str(nonce))
                    stop.set()
                    return
                nonce += workers
                if deadline is not None and time.monotonic() > deadline:
                    stop.set()
                    raise ValueError(
                        f"AtomicMail proof-of-work did not converge within {max_seconds:g}s "
                        f"(difficulty={difficulty}, tried {nonce} nonces). The challenge may be "
                        "misconfigured or its difficulty implausibly high."
                    )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(search, start) for start in range(workers)]
        # Every worker has finished. A worker can cross the deadline while another is
        # mid-way through the winning hash, so a solution wins over a timeout.
        if not solved:
            for future in futures:
                future.result()  # re-raises the worker's timeout
        return solved

    @staticmethod
    def _bearer_token(response: httpx.Response) -> str:
        header = response.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            raise ValueError(f"{response.request.url} did not return a Bearer Authorization header.")
        return header[len("Bearer ") :].strip()

    @staticmethod
    def _build_session_payload(
        solved: Dict[str, str], username: Optional[str], api_key: Optional[str]
    ) -> Dict[str, str]:
        payload = dict(solved)
        if username:
            payload["username"] = username
        if api_key:
            payload["apiKey"] = api_key
        return payload

    @staticmethod
    def _parse_auth_result(capability_jwt: str, session_data: Dict[str, Any], api_key: Optional[str]) -> Dict[str, Any]:
        capability_claims = AtomicMailTools._decode_jwt_payload(capability_jwt)
        # `inboxId` is the inbox local-part (e.g. "research-agent"), not a full address.
        # The sending address is `<inboxId>@<allowedFromDomain>`; JMAP rejects a bare
        # local-part with `forbiddenFrom`. Both values are carried in the capability JWT.
        inbox_id = capability_claims.get("inboxId")
        domain = capability_claims.get("allowedFromDomain") or "atomicmail.ai"
        inbox = f"{inbox_id}@{domain}" if inbox_id and "@" not in inbox_id else inbox_id
        return {
            "api_key": session_data.get("apiKey") or api_key,
            "inbox": inbox,
            "capability_jwt": capability_jwt,
        }

    @staticmethod
    def _jmap_body(using: List[str], method_calls: List[Any]) -> Dict[str, Any]:
        return {"using": using, "methodCalls": method_calls}

    @staticmethod
    def _extract_account_id(session: Dict[str, Any]) -> str:
        return session["primaryAccounts"][JMAP_MAIL_URN]

    @staticmethod
    def _mailbox_query_call(account_id: str) -> Tuple[List[str], List[Any]]:
        using = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]
        method_calls = [["Mailbox/query", {"accountId": account_id, "filter": {"role": "inbox"}}, "m0"]]
        return using, method_calls

    @staticmethod
    def _build_jmap_context(
        auth: Dict[str, Any],
        session: Dict[str, Any],
        account_id: str,
        mailbox_result: Dict[str, Any],
        credentials: Dict[str, Any],
    ) -> Dict[str, Any]:
        mailbox_ids = mailbox_result["methodResponses"][0][1]["ids"]
        if not mailbox_ids:
            raise ValueError("AtomicMail account has no inbox mailbox.")
        return {
            "api_key": credentials["api_key"],
            "capability_jwt": auth["capability_jwt"],
            "api_url": session["apiUrl"],
            "account_id": account_id,
            # Prefer the address derived from this auth: it is always the full
            # `<local-part>@<domain>`. A credential saved before that format was
            # fixed may still hold a bare local-part, which JMAP rejects as From.
            "inbox": auth.get("inbox") or credentials.get("inbox"),
            "inbox_mailbox_id": mailbox_ids[0],
        }

    @staticmethod
    def _send_email_call(context: Dict[str, Any], to: str, subject: str, body: str) -> Tuple[List[str], List[Any]]:
        using = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail", "urn:ietf:params:jmap:submission"]
        method_calls = [
            [
                "Email/set",
                {
                    "accountId": context["account_id"],
                    "create": {
                        "draft": {
                            "mailboxIds": {context["inbox_mailbox_id"]: True},
                            "from": [{"email": context["inbox"]}],
                            "to": [{"email": to}],
                            "subject": subject,
                            "textBody": [{"partId": "body", "type": "text/plain"}],
                            "bodyValues": {"body": {"value": body}},
                            "keywords": {"$draft": True},
                        }
                    },
                },
                "c0",
            ],
            [
                "EmailSubmission/set",
                {
                    "accountId": context["account_id"],
                    "create": {
                        "submission": {
                            "emailId": "#draft",
                            # Required by JMAP submission (RFC 8621). AtomicMail's identity id
                            # matches the JMAP account id (both equal the inbox local-part).
                            "identityId": context["account_id"],
                            "envelope": {
                                "mailFrom": {"email": context["inbox"]},
                                "rcptTo": [{"email": to}],
                            },
                        }
                    },
                },
                "c1",
            ],
        ]
        return using, method_calls

    @staticmethod
    def _parse_send_email_result(result: Dict[str, Any], to: str, subject: str) -> Dict[str, Any]:
        responses = {name: payload for name, payload, _ in result["methodResponses"]}
        email_result = responses.get("Email/set", {})
        submission_result = responses.get("EmailSubmission/set", {})
        created_draft = (email_result.get("created") or {}).get("draft")
        created_submission = (submission_result.get("created") or {}).get("submission")
        # Require that the draft was created AND actually submitted. A notCreated
        # entry or a method-level error (e.g. an ["error", ...] response that never
        # populates `created`) leaves these falsy; without this check the draft
        # would be created but unsent yet reported as success with a null id.
        if email_result.get("notCreated") or submission_result.get("notCreated") or not created_submission:
            return {"error": "AtomicMail rejected the email", "details": result["methodResponses"]}

        log_info(f"Sent AtomicMail email to {to}")
        return {
            "email_id": (created_draft or {}).get("id"),
            "submission_id": created_submission.get("id"),
            "to": to,
            "subject": subject,
        }

    @staticmethod
    def _list_inbox_call(context: Dict[str, Any], capped_limit: int) -> Tuple[List[str], List[Any]]:
        using = ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"]
        method_calls = [
            [
                "Email/query",
                {
                    "accountId": context["account_id"],
                    # send_email files outgoing mail in this same mailbox with `$draft` set,
                    # so without this exclusion sent mail reads back as received.
                    "filter": {"inMailbox": context["inbox_mailbox_id"], "notKeyword": "$draft"},
                    "sort": [{"property": "receivedAt", "isAscending": False}],
                    "limit": capped_limit,
                },
                "q0",
            ],
            [
                "Email/get",
                {
                    "accountId": context["account_id"],
                    "#ids": {"resultOf": "q0", "name": "Email/query", "path": "/ids"},
                    "properties": ["id", "threadId", "receivedAt", "from", "to", "subject", "preview", "keywords"],
                },
                "g0",
            ],
        ]
        return using, method_calls

    @staticmethod
    def _parse_list_inbox_result(result: Dict[str, Any], inbox: str) -> Dict[str, Any]:
        responses = {name: payload for name, payload, _ in result["methodResponses"]}
        # A rejected query (e.g. `unsupportedFilter`) comes back as ["error", ...] entries
        # with no Email/get list; that is an error, not an empty inbox.
        if "Email/get" not in responses:
            return {"error": "AtomicMail rejected the inbox query", "details": result["methodResponses"]}
        emails: List[Dict[str, Any]] = responses["Email/get"]["list"]
        # Belt-and-braces on the query's `notKeyword` filter: a `$draft` message in the
        # inbox is our own outgoing mail from send_email, never something received.
        emails = [email for email in emails if "$draft" not in (email.get("keywords") or {})]
        return {
            "inbox": inbox,
            "count": len(emails),
            "emails": [
                {
                    "id": email.get("id"),
                    "from": email.get("from"),
                    "to": email.get("to"),
                    "subject": email.get("subject"),
                    "received_at": email.get("receivedAt"),
                    "preview": email.get("preview"),
                }
                for email in emails
            ],
        }

    @staticmethod
    def _start_registration(
        credentials_path: Path, existing: Optional[Dict[str, Any]], normalized: str, forced: bool
    ) -> Optional[Dict[str, Any]]:
        """Validate `normalized` and check for an already-registered inbox.

        Returns a result dict to short-circuit on (idempotent success or error), or
        None to signal that the caller should proceed with the network handshake.
        """
        if not (5 <= len(normalized) <= 21):
            return {"error": "username must be 5-21 characters"}

        if existing and existing.get("api_key"):
            existing_local_part = (existing.get("inbox") or "").split("@")[0]
            if existing_local_part == normalized:
                return {"inbox": existing["inbox"], "account_id": existing.get("account_id"), "idempotent": True}
            if not forced:
                return {
                    "error": (
                        f"Credentials for a different inbox ({existing.get('inbox')}) already exist at "
                        f"{credentials_path}. Call register_inbox with forced=True to replace them, "
                        "or use a different credentials_dir to register a second inbox."
                    )
                }
        return None

    def _finalize_registration(self, auth: Dict[str, Any], account_id: Optional[str]) -> Dict[str, Any]:
        self._save_credentials({"api_key": auth["api_key"], "inbox": auth["inbox"], "account_id": account_id})
        log_info(f"Registered AtomicMail inbox: {auth['inbox']}")
        return {"inbox": auth["inbox"], "account_id": account_id, "idempotent": False}

    @staticmethod
    def _registration_error(e: Exception) -> Dict[str, Any]:
        if isinstance(e, httpx.HTTPStatusError):
            return {"error": f"AtomicMail registration failed: {e.response.status_code} {e.response.text}"}
        return {"error": f"AtomicMail registration failed: {e}"}

    @staticmethod
    def _request_error(e: Exception) -> Dict[str, Any]:
        if isinstance(e, httpx.HTTPStatusError):
            return {"error": f"AtomicMail request failed: {e.response.status_code} {e.response.text}"}
        return {"error": f"AtomicMail request failed: {e}"}

    # -- JMAP context cache, shared by the sync and async paths ----------------------

    def _cached_jmap_context(self, credentials: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Keyed to the api_key it was minted from: credentials.json can be replaced by a
        # forced re-registration, from this instance or another process sharing the dir.
        if (
            self.__jmap_context is not None
            and self.__jmap_context["api_key"] == credentials["api_key"]
            and time.monotonic() < self.__jmap_context_expiry
        ):
            return self.__jmap_context
        return None

    def _cache_jmap_context(self, context: Dict[str, Any]) -> None:
        claims = self._decode_jwt_payload(context["capability_jwt"])
        exp, iat = claims.get("exp"), claims.get("iat", time.time())
        # Expire with the token: its `exp - iat` span, or `exp` against the local clock
        # when it carries no `iat`. The 30s margin keeps a request that starts inside the
        # window from outliving the token; without a numeric `exp` nothing is reused.
        lifetime = exp - iat if isinstance(exp, (int, float)) and isinstance(iat, (int, float)) else 0
        self.__jmap_context = context
        self.__jmap_context_expiry = time.monotonic() + lifetime - 30

    # -- sync HTTP calls ---------------------------------------------------------

    def _authenticate(
        self, client: httpx.Client, *, username: Optional[str] = None, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run the challenge -> proof-of-work -> session -> capability handshake.

        Provide `username` to register a new inbox, or `api_key` to re-authenticate an
        existing one. Returns the resolved api_key, inbox address, and capability JWT
        (a short-lived bearer token used to authorize JMAP requests).
        """
        challenge_response = client.post(f"{self.auth_url}/api/v1/challenge")
        challenge_response.raise_for_status()
        challenge_jwt = self._bearer_token(challenge_response)
        challenge_claims = self._decode_jwt_payload(challenge_jwt)
        solved = self._solve_pow(
            challenge_claims["jti"], int(challenge_claims["difficulty"]), self.pow_timeout, self.pow_workers
        )

        session_response = client.post(
            f"{self.auth_url}/api/v1/session",
            headers={"Authorization": f"Bearer {challenge_jwt}"},
            json=self._build_session_payload(solved, username, api_key),
        )
        session_response.raise_for_status()
        session_jwt = self._bearer_token(session_response)
        session_data = session_response.json() if session_response.text.strip() else {}

        capability_response = client.post(
            f"{self.auth_url}/api/v1/capability",
            headers={"Authorization": f"Bearer {session_jwt}"},
        )
        capability_response.raise_for_status()
        capability_jwt = self._bearer_token(capability_response)

        return self._parse_auth_result(capability_jwt, session_data, api_key)

    def _jmap_session(self, client: httpx.Client, capability_jwt: str) -> Dict[str, Any]:
        response = client.get(
            f"{self.api_url}/.well-known/jmap",
            headers={"Authorization": f"Bearer {capability_jwt}"},
        )
        response.raise_for_status()
        return response.json()

    def _jmap_call(
        self, client: httpx.Client, capability_jwt: str, jmap_api_url: str, using: List[str], method_calls: List[Any]
    ) -> Dict[str, Any]:
        response = client.post(
            jmap_api_url,
            headers={"Authorization": f"Bearer {capability_jwt}"},
            json=self._jmap_body(using, method_calls),
        )
        response.raise_for_status()
        return response.json()

    def _prepare_jmap_context(self, client: httpx.Client) -> Dict[str, Any]:
        """Authenticate with the stored API key and resolve the inbox's JMAP account/mailbox ids.

        The result is cached until the capability token nears expiry or the stored api_key
        changes, so only the first call in that window pays for the proof-of-work handshake.
        """
        credentials = self._require_credentials()
        cached = self._cached_jmap_context(credentials)
        if cached is not None:
            return cached
        auth = self._authenticate(client, api_key=credentials["api_key"])
        session = self._jmap_session(client, auth["capability_jwt"])
        account_id = self._extract_account_id(session)
        mailbox_result = self._jmap_call(
            client, auth["capability_jwt"], session["apiUrl"], *self._mailbox_query_call(account_id)
        )
        context = self._build_jmap_context(auth, session, account_id, mailbox_result, credentials)
        self._cache_jmap_context(context)
        return context

    def _resolve_account_id(self, client: httpx.Client, capability_jwt: str) -> Optional[str]:
        """Best-effort JMAP account-id lookup for the registration result.

        The inbox already exists once signup authenticates, so a failure resolving its
        account id must not strand it: log and return `None` (it is re-derived on the
        next send/list) rather than raising and discarding the just-created api_key.
        """
        try:
            session = self._jmap_session(client, capability_jwt)
            return self._extract_account_id(session)
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError, ValueError) as e:
            log_error(f"AtomicMail inbox registered, but its account id could not be resolved yet: {e}")
            return None

    # -- async HTTP calls ---------------------------------------------------------

    async def _aauthenticate(
        self, client: httpx.AsyncClient, *, username: Optional[str] = None, api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Async counterpart of `_authenticate`; see there for the handshake description."""
        challenge_response = await client.post(f"{self.auth_url}/api/v1/challenge")
        challenge_response.raise_for_status()
        challenge_jwt = self._bearer_token(challenge_response)
        challenge_claims = self._decode_jwt_payload(challenge_jwt)
        # Offload the CPU-bound scrypt grind to a worker thread so a multi-second
        # (server-difficulty-driven) solve does not block the event loop under agentos.
        solved = await asyncio.to_thread(
            self._solve_pow,
            challenge_claims["jti"],
            int(challenge_claims["difficulty"]),
            self.pow_timeout,
            self.pow_workers,
        )

        session_response = await client.post(
            f"{self.auth_url}/api/v1/session",
            headers={"Authorization": f"Bearer {challenge_jwt}"},
            json=self._build_session_payload(solved, username, api_key),
        )
        session_response.raise_for_status()
        session_jwt = self._bearer_token(session_response)
        session_data = session_response.json() if session_response.text.strip() else {}

        capability_response = await client.post(
            f"{self.auth_url}/api/v1/capability",
            headers={"Authorization": f"Bearer {session_jwt}"},
        )
        capability_response.raise_for_status()
        capability_jwt = self._bearer_token(capability_response)

        return self._parse_auth_result(capability_jwt, session_data, api_key)

    async def _ajmap_session(self, client: httpx.AsyncClient, capability_jwt: str) -> Dict[str, Any]:
        response = await client.get(
            f"{self.api_url}/.well-known/jmap",
            headers={"Authorization": f"Bearer {capability_jwt}"},
        )
        response.raise_for_status()
        return response.json()

    async def _ajmap_call(
        self,
        client: httpx.AsyncClient,
        capability_jwt: str,
        jmap_api_url: str,
        using: List[str],
        method_calls: List[Any],
    ) -> Dict[str, Any]:
        response = await client.post(
            jmap_api_url,
            headers={"Authorization": f"Bearer {capability_jwt}"},
            json=self._jmap_body(using, method_calls),
        )
        response.raise_for_status()
        return response.json()

    async def _aprepare_jmap_context(self, client: httpx.AsyncClient) -> Dict[str, Any]:
        """Async counterpart of `_prepare_jmap_context`."""
        credentials = self._require_credentials()
        cached = self._cached_jmap_context(credentials)
        if cached is not None:
            return cached
        auth = await self._aauthenticate(client, api_key=credentials["api_key"])
        session = await self._ajmap_session(client, auth["capability_jwt"])
        account_id = self._extract_account_id(session)
        mailbox_result = await self._ajmap_call(
            client, auth["capability_jwt"], session["apiUrl"], *self._mailbox_query_call(account_id)
        )
        context = self._build_jmap_context(auth, session, account_id, mailbox_result, credentials)
        self._cache_jmap_context(context)
        return context

    async def _aresolve_account_id(self, client: httpx.AsyncClient, capability_jwt: str) -> Optional[str]:
        """Async counterpart of `_resolve_account_id`."""
        try:
            session = await self._ajmap_session(client, capability_jwt)
            return self._extract_account_id(session)
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError, ValueError) as e:
            log_error(f"AtomicMail inbox registered, but its account id could not be resolved yet: {e}")
            return None

    # -- tools ------------------------------------------------------------------

    def register_inbox(self, username: str, forced: bool = False) -> Dict[str, Any]:
        """Register a new AtomicMail inbox via autonomous proof-of-work signup.

        No domain setup or human verification is required. If an inbox is already
        registered for this credentials directory, this call is idempotent for the
        same username, and refuses to overwrite a different inbox unless `forced`.

        Args:
            username: Desired inbox local-part, 5-21 characters (e.g. "research-agent").
            forced: If True, discard any different inbox already stored locally and
                register a fresh one for `username`.

        Returns:
            Dict with `inbox`, `account_id`, and `idempotent` on success, or `error`.
        """
        normalized = username.strip().lower()
        try:
            early_result = self._start_registration(self.credentials_path, self._load_credentials(), normalized, forced)
            if early_result is not None:
                return early_result

            with httpx.Client(timeout=self.timeout) as client:
                auth = self._authenticate(client, username=normalized)
                if not auth["api_key"]:
                    return {"error": "AtomicMail signup did not return an API key."}
                if not auth["inbox"]:
                    return {"error": "AtomicMail signup did not return an inbox address."}
                account_id = self._resolve_account_id(client, auth["capability_jwt"])
                return self._finalize_registration(auth, account_id)
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError, IndexError) as e:
            return self._registration_error(e)

    async def aregister_inbox(self, username: str, forced: bool = False) -> Dict[str, Any]:
        """Asynchronously register a new AtomicMail inbox via autonomous proof-of-work signup.

        No domain setup or human verification is required. If an inbox is already
        registered for this credentials directory, this call is idempotent for the
        same username, and refuses to overwrite a different inbox unless `forced`.

        Args:
            username: Desired inbox local-part, 5-21 characters (e.g. "research-agent").
            forced: If True, discard any different inbox already stored locally and
                register a fresh one for `username`.

        Returns:
            Dict with `inbox`, `account_id`, and `idempotent` on success, or `error`.
        """
        normalized = username.strip().lower()
        try:
            early_result = self._start_registration(self.credentials_path, self._load_credentials(), normalized, forced)
            if early_result is not None:
                return early_result

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                auth = await self._aauthenticate(client, username=normalized)
                if not auth["api_key"]:
                    return {"error": "AtomicMail signup did not return an API key."}
                if not auth["inbox"]:
                    return {"error": "AtomicMail signup did not return an inbox address."}
                account_id = await self._aresolve_account_id(client, auth["capability_jwt"])
                return self._finalize_registration(auth, account_id)
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError, IndexError) as e:
            return self._registration_error(e)

    def send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Send a plain-text email from the registered AtomicMail inbox.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain-text email body.

        Returns:
            Dict with `email_id`, `submission_id`, `to`, and `subject` on success, or `error`.
        """
        try:
            with httpx.Client(timeout=self.timeout) as client:
                context = self._prepare_jmap_context(client)
                using, method_calls = self._send_email_call(context, to, subject, body)
                result = self._jmap_call(client, context["capability_jwt"], context["api_url"], using, method_calls)
                return self._parse_send_email_result(result, to, subject)
        except ValueError as e:
            return {"error": str(e)}
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError) as e:
            return self._request_error(e)

    async def asend_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Asynchronously send a plain-text email from the registered AtomicMail inbox.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain-text email body.

        Returns:
            Dict with `email_id`, `submission_id`, `to`, and `subject` on success, or `error`.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                context = await self._aprepare_jmap_context(client)
                using, method_calls = self._send_email_call(context, to, subject, body)
                result = await self._ajmap_call(
                    client, context["capability_jwt"], context["api_url"], using, method_calls
                )
                return self._parse_send_email_result(result, to, subject)
        except ValueError as e:
            return {"error": str(e)}
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError) as e:
            return self._request_error(e)

    def list_inbox(self, limit: int = 20) -> Dict[str, Any]:
        """List the most recent emails received in the registered AtomicMail inbox.

        Args:
            limit: Maximum number of emails to return (default 20, capped at 100).

        Returns:
            Dict with `inbox`, `count`, and an `emails` list (id, from, to, subject,
            received_at, preview), or `error`.
        """
        capped_limit = max(1, min(limit, 100))
        try:
            with httpx.Client(timeout=self.timeout) as client:
                context = self._prepare_jmap_context(client)
                using, method_calls = self._list_inbox_call(context, capped_limit)
                result = self._jmap_call(client, context["capability_jwt"], context["api_url"], using, method_calls)
                return self._parse_list_inbox_result(result, context["inbox"])
        except ValueError as e:
            return {"error": str(e)}
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError) as e:
            return self._request_error(e)

    async def alist_inbox(self, limit: int = 20) -> Dict[str, Any]:
        """Asynchronously list the most recent emails received in the registered AtomicMail inbox.

        Args:
            limit: Maximum number of emails to return (default 20, capped at 100).

        Returns:
            Dict with `inbox`, `count`, and an `emails` list (id, from, to, subject,
            received_at, preview), or `error`.
        """
        capped_limit = max(1, min(limit, 100))
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                context = await self._aprepare_jmap_context(client)
                using, method_calls = self._list_inbox_call(context, capped_limit)
                result = await self._ajmap_call(
                    client, context["capability_jwt"], context["api_url"], using, method_calls
                )
                return self._parse_list_inbox_result(result, context["inbox"])
        except ValueError as e:
            return {"error": str(e)}
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, IndexError) as e:
            return self._request_error(e)
