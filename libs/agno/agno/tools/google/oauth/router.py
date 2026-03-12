from os import getenv
from typing import List, Optional

from agno.tools.google.oauth.state import create_state, verify_state
from agno.tools.google.oauth.token_store import BaseGoogleTokenStore
from agno.utils.log import log_debug, log_error

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
except ImportError:
    raise ImportError("fastapi required: pip install fastapi")

try:
    from google_auth_oauthlib.flow import Flow
except ImportError:
    raise ImportError("google-auth-oauthlib required: pip install google-auth-oauthlib")

_SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Google Connected</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 60px;">
  <h1>Google account connected</h1>
  <p>You can close this tab and return to Slack.</p>
</body>
</html>
"""

_ERROR_HTML = """
<!DOCTYPE html>
<html>
<head><title>Connection Failed</title></head>
<body style="font-family: sans-serif; text-align: center; padding: 60px;">
  <h1>Connection failed</h1>
  <p>{error}</p>
  <p>Please try again from Slack.</p>
</body>
</html>
"""


def create_google_oauth_router(
    token_store: BaseGoogleTokenStore,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    scopes: Optional[List[str]] = None,
    encryption_key: Optional[str] = None,
    slack_token: Optional[str] = None,
) -> APIRouter:
    _client_id = client_id or getenv("GOOGLE_CLIENT_ID")
    _client_secret = client_secret or getenv("GOOGLE_CLIENT_SECRET")
    _redirect_uri = redirect_uri or getenv("GOOGLE_OAUTH_REDIRECT_URI")
    _scopes = scopes or []
    _encryption_key = encryption_key or getenv("GOOGLE_OAUTH_ENCRYPTION_KEY")

    if not _client_id or not _client_secret:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET required")
    if not _redirect_uri:
        raise ValueError("redirect_uri or GOOGLE_OAUTH_REDIRECT_URI required")

    # Web app client config — NOT "installed" (which uses run_local_server)
    client_config = {
        "web": {
            "client_id": _client_id,
            "client_secret": _client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [_redirect_uri],
        }
    }

    router = APIRouter(tags=["google-oauth"])

    @router.get("/google/auth/initiate")
    async def initiate_google_auth(
        workspace_id: str,
        user_id: str,
        channel_id: str = "",
        thread_ts: str = "",
    ):
        # Carry Slack thread context so the callback can reply in the same thread
        extra = {}
        if channel_id:
            extra["channel_id"] = channel_id
        if thread_ts:
            extra["thread_ts"] = thread_ts
        state = create_state(workspace_id, user_id, encryption_key=_encryption_key, extra=extra or None)

        flow = Flow.from_client_config(client_config, scopes=_scopes, redirect_uri=_redirect_uri)
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=state,
        )

        log_debug(f"Google OAuth initiated for team={workspace_id} user={user_id}")
        return RedirectResponse(url=auth_url, status_code=302)

    @router.get("/google/auth/callback")
    async def google_auth_callback(request: Request):
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        error = request.query_params.get("error")

        if error:
            log_error(f"Google OAuth error: {error}")
            return HTMLResponse(content=_ERROR_HTML.format(error=error), status_code=400)

        if not code or not state:
            return HTMLResponse(
                content=_ERROR_HTML.format(error="Missing authorization code or state"),
                status_code=400,
            )

        try:
            workspace_id, user_id, state_payload = verify_state(state, encryption_key=_encryption_key)
        except ValueError as e:
            log_error(f"Invalid OAuth state: {e}")
            return HTMLResponse(content=_ERROR_HTML.format(error=str(e)), status_code=400)

        try:
            # Google may return more scopes than requested (e.g. previously
            # granted scopes). Use the returned scopes so fetch_token doesn't
            # raise a "scope has changed" error.
            returned_scopes_str = request.query_params.get("scope", "")
            callback_scopes = returned_scopes_str.split() if returned_scopes_str else _scopes
            flow = Flow.from_client_config(client_config, scopes=callback_scopes, redirect_uri=_redirect_uri)
            flow.fetch_token(code=code)
            creds = flow.credentials
        except Exception as e:
            log_error(f"Token exchange failed: {e}")
            return HTMLResponse(
                content=_ERROR_HTML.format(error="Failed to exchange authorization code"),
                status_code=500,
            )

        token_store.save_token(workspace_id, user_id, creds, callback_scopes)
        log_debug(f"Google OAuth completed for team={workspace_id} user={user_id}")

        # Notify user in Slack — reply in original thread if available, else DM
        if slack_token:
            try:
                await _notify_slack_user(
                    slack_token,
                    user_id,
                    channel_id=state_payload.get("channel_id"),
                    thread_ts=state_payload.get("thread_ts"),
                )
            except Exception as e:
                # Non-fatal — token is already saved
                log_error(f"Failed to send Slack notification: {e}")

        return HTMLResponse(content=_SUCCESS_HTML, status_code=200)

    @router.post("/google/auth/revoke")
    async def revoke_google_auth(workspace_id: str, user_id: str):
        creds = token_store.get_token(workspace_id, user_id)
        if creds is None:
            raise HTTPException(status_code=404, detail="No Google token found")

        # Revoke at Google
        if creds.token:
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    await client.post(
                        "https://oauth2.googleapis.com/revoke",
                        params={"token": creds.token},
                    )
            except Exception as e:
                log_error(f"Google token revocation failed: {e}")

        token_store.delete_token(workspace_id, user_id)
        return {"status": "revoked"}

    return router


async def _notify_slack_user(
    slack_token: str,
    user_id: str,
    channel_id: Optional[str] = None,
    thread_ts: Optional[str] = None,
) -> None:
    try:
        from slack_sdk.web.async_client import AsyncWebClient
    except ImportError:
        return

    client = AsyncWebClient(token=slack_token)
    msg_kwargs: dict = {
        "text": "Your Google account has been connected. Try your request again!",
    }
    if channel_id and thread_ts:
        # Reply in the same thread where the Connect button was shown
        msg_kwargs["channel"] = channel_id
        msg_kwargs["thread_ts"] = thread_ts
    else:
        # Fall back to DM
        msg_kwargs["channel"] = user_id
    await client.chat_postMessage(**msg_kwargs)
