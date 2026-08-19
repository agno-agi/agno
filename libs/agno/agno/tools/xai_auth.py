import json
from inspect import iscoroutinefunction
from os import getenv
from time import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from agno.exceptions import ModelAuthenticationError
from agno.run import RunContext
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.models.xai.oauth import XAITokenManager

# Pending logins share the auth-token table with the token itself, under their
# own service key: one in-flight login per user, wiped on completion or retry.
_PENDING_SERVICE = "supergrok-pending"

_ALREADY_SIGNED_IN = (
    "Already signed in with SuperGrok (token valid). To sign in with a different account, "
    "say 'sign out and sign in again' — I'll restart the login."
)
_SIGNED_IN = "Signed in with SuperGrok. The xAI model will now use this subscription."
_NOT_APPROVED = "Not approved yet. Open the link, approve the sign-in, then tell me again when you're done."
_NO_PENDING = "No sign-in is in progress. Call sign_in_with_supergrok first."
_NOT_SAVED = (
    "Signed in, but the token was NOT saved: XAI_TOKEN_ENCRYPTION_KEY is not set. "
    "Set it (see the cookbook) and sign in again, or pass encrypt_tokens=False for local dev."
)
_FILE_DEGRADE_NOTE = " (Note: token stored to a local file — this database does not support token storage.)"


def _requester(run_context: Optional[RunContext]) -> str:
    """The user an in-flight login belongs to; a script user has no id and gets the empty slot."""
    return (run_context.user_id if run_context else None) or ""


def _failed(reason: str) -> str:
    # The manager's terminal messages are whole sentences: drop the trailing
    # period so the composed line does not read "in the browser.. Start again".
    return f"Sign-in failed: {reason.rstrip('.')}. Start again with sign_in_with_supergrok."


class XAIAuth(Toolkit):
    """Toolkit that exposes SuperGrok sign-in tools for web/chat UI OAuth flows.

    Use this when a terminal device flow won't work (e.g., chatbot interfaces).
    The agent calls sign_in_with_supergrok() to get the approval URL for the
    user, then check_supergrok_login() to finish.

    Signing in provisions the deployment's SuperGrok credential (single-user
    mode): the token is stored on the slot the xAI model already reads.
    """

    def __init__(
        self,
        token_manager: Optional["XAITokenManager"] = None,
        db: Optional[Any] = None,
        token_path: Optional[str] = None,
        encryption_key: Optional[str] = None,
        encrypt_tokens: bool = True,
        **kwargs: Any,
    ):
        super().__init__(
            name="xai_auth",
            instructions=(
                "When the xAI model returns an authentication error or the user asks to sign in with "
                "SuperGrok, call sign_in_with_supergrok to get the approval URL for the user, then call "
                "check_supergrok_login after they confirm."
            ),
            **kwargs,
        )
        # Imported here, not at module scope: the xai model package pulls in the
        # OpenAI SDK, and a toolkit import must not require it (unsplash.py idiom).
        from agno.models.xai.oauth import XAITokenManager

        self.token_manager: XAITokenManager = token_manager or XAITokenManager(
            db=db,
            token_path=token_path,
            encryption_key=encryption_key or getenv("XAI_TOKEN_ENCRYPTION_KEY"),
            encrypt_tokens=encrypt_tokens,
        )
        # Fallback for a pending login no database can hold: single-process by
        # nature, which is exactly the script and local-dev case.
        self._pending: Dict[str, Dict[str, Any]] = {}
        self.register(self.sign_in_with_supergrok)
        self.register(self.check_supergrok_login)

    def sign_in_with_supergrok(self, run_context: Optional[RunContext] = None, force: bool = False) -> str:
        """Start a SuperGrok sign-in and give the user a link to approve it.

        Args:
            force: Forget the stored session and start a fresh login. Only set this
                when the user asks to sign in with a different account.

        Returns:
            JSON string containing the approval message and URL, or an error message.
        """
        if force:
            self.token_manager.sign_out()
        elif self._is_signed_in():
            return json.dumps({"message": _ALREADY_SIGNED_IN})

        try:
            info = self.token_manager.start_device_login()
        except ModelAuthenticationError as e:
            return json.dumps({"error": str(e)})

        self._stash(
            _requester(run_context),
            {"device_code": info.device_code, "interval": info.interval, "deadline": time() + info.expires_in},
        )
        return json.dumps(
            {
                "message": (
                    "Open this link, check the code matches, and approve the sign-in. "
                    f"Code: {info.user_code}. Then tell me when you're done."
                ),
                "url": info.verification_uri_complete,
            }
        )

    def check_supergrok_login(self, run_context: Optional[RunContext] = None) -> str:
        """Check whether the user approved the SuperGrok sign-in, and store the token.

        Call this after the user says they approved the link. It polls once, so
        call it again if the sign-in has not been approved yet.

        Returns:
            JSON string confirming the sign-in, or reporting that it is still
            pending or has failed.
        """
        from agno.models.xai.oauth import DevicePollStatus

        user_id = _requester(run_context)
        pending = self._read_pending(user_id)
        if pending is None:
            return json.dumps({"error": _NO_PENDING})

        try:
            result = self.token_manager.poll_once(pending["device_code"], int(pending["interval"]))
        except ModelAuthenticationError as e:
            self._clear_pending(user_id)
            return json.dumps({"error": _failed(str(e))})

        if result.status is DevicePollStatus.pending:
            # Re-stash so the RFC 8628 slow_down back-off reaches the next turn
            pending["interval"] = result.interval
            self._stash(user_id, pending)
            return json.dumps({"message": _NOT_APPROVED})

        self._clear_pending(user_id)
        if result.status is not DevicePollStatus.success:
            return json.dumps({"error": _failed(result.message or "")})
        # poll_once already persisted the token through the manager's own save path
        if self.token_manager.encrypt_tokens and not self.token_manager.encryption_key:
            return json.dumps({"error": _NOT_SAVED})
        return json.dumps({"message": _SIGNED_IN + self._degrade_note()})

    def _is_signed_in(self) -> bool:
        """Whether a usable SuperGrok session already exists, refreshing it if needed."""
        try:
            self.token_manager.get_access_token()
            return True
        except ModelAuthenticationError:
            return False

    def _degrade_note(self) -> str:
        """The note for a database that could not hold the token, so the manager wrote a file."""
        db = self.token_manager.db
        if db is None:
            return ""
        try:
            # The manager owns the deployment slot; read it rather than restate it
            if db.get_auth_token(*self.token_manager._store_key()) is not None:
                return ""
        except NotImplementedError:
            pass
        except Exception as e:
            log_debug(f"Could not confirm where the SuperGrok token was stored: {e}")
        return _FILE_DEGRADE_NOTE

    # ------------------------------------------------------------------
    # The pending login: a db row when the backend can hold one, else memory
    # ------------------------------------------------------------------

    def _pending_db(self) -> Optional[Any]:
        """The database to keep pending logins on, or None when process state must serve.

        These tools are sync (the GoogleAuth template), so an async backend cannot
        be awaited here; it degrades to memory exactly as the manager's own sync
        path degrades to a file.
        """
        db = self.token_manager.db
        if db is None or iscoroutinefunction(db.upsert_auth_token):
            return None
        return db

    def _stash(self, user_id: str, pending: Dict[str, Any]) -> None:
        db = self._pending_db()
        payload = self._encrypt(pending) if db is not None else None
        if db is not None and payload is not None:
            try:
                db.upsert_auth_token(
                    {
                        "provider": "xai",
                        "user_id": user_id,
                        "service": _PENDING_SERVICE,
                        "token_data": payload,
                        "granted_scopes": [],
                    }
                )
                return
            except NotImplementedError:
                log_warning("Database does not support auth token storage")
            except Exception as e:
                log_debug(f"Could not save the pending SuperGrok login to the DB: {e}")
        self._pending[user_id] = pending

    def _read_pending(self, user_id: str) -> Optional[Dict[str, Any]]:
        db = self._pending_db()
        if db is not None:
            row = None
            try:
                row = db.get_auth_token("xai", user_id, _PENDING_SERVICE)
            except NotImplementedError:
                log_warning("Database does not support auth token storage")
            except Exception as e:
                log_debug(f"Could not read the pending SuperGrok login from the DB: {e}")
            if row is not None:
                stored = self._decrypt(row.get("token_data"))
                if stored is not None:
                    return stored
        return self._pending.get(user_id)

    def _clear_pending(self, user_id: str) -> None:
        db = self._pending_db()
        if db is not None:
            try:
                db.delete_auth_token("xai", user_id, _PENDING_SERVICE)
            except NotImplementedError:
                log_warning("Database does not support auth token deletion")
            except Exception as e:
                log_debug(f"Could not delete the pending SuperGrok login from the DB: {e}")
        self._pending.pop(user_id, None)

    def _encrypt(self, pending: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Encrypt under the manager's key; None when encryption is required but unconfigured."""
        if not self.token_manager.encrypt_tokens:
            return dict(pending)
        if not self.token_manager.encryption_key:
            return None
        from agno.utils.encryption import encrypt_dict

        return encrypt_dict(pending, key=self.token_manager.encryption_key)

    def _decrypt(self, payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        from agno.utils.encryption import decrypt_dict, is_encrypted

        if not payload:
            return None
        if not is_encrypted(payload):
            return payload
        if not self.token_manager.encryption_key:
            log_warning("Could not decrypt the pending SuperGrok login: XAI_TOKEN_ENCRYPTION_KEY is not set")
            return None
        try:
            return decrypt_dict(payload, key=self.token_manager.encryption_key)
        except ValueError as e:
            log_warning(f"Could not decrypt the pending SuperGrok login: {e}")
            return None
