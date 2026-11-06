"""Pure request validation shared by the control plane and Linux runtime."""

import json
import math
import os
from typing import Any, Dict

_VERSION = 1
_MAX_REQUEST = 1024 * 1024
# Where each runtime records its own conversation id in the session data it returns.
NATIVE_SESSION_KEYS = {"claude": "claude_sdk_session_id", "codex": "codex_thread_id", "fixture": "fixture_session_id"}


def validate_request(request: Dict[str, Any]) -> None:
    if type(request.get("version")) is not int or request["version"] != _VERSION:
        raise ValueError("Unsupported runtime protocol version")
    for key in ("execution_id", "run_id", "session_id", "agent_id"):
        if not isinstance(request.get(key), str) or not request[key] or len(request[key]) > 256:
            raise ValueError("Runtime requires bounded string identities")
    if request.get("sdk") not in ("claude", "codex", "fixture"):
        raise ValueError("Unsupported runtime SDK")
    if not isinstance(request.get("input"), str) or not isinstance(request.get("config", {}), dict):
        raise ValueError("Runtime input must be text and configuration must be JSON")
    if request["sdk"] == "fixture" and os.environ.get("AGNO_SANDBOX_TEST_RUNTIME") != "1":
        raise ValueError("The fixture runtime is disabled")
    if {
        "db",
        "cwd",
        "id",
        "retries",
        "env",
        "client_options",
        "options",
        "options_kwargs",
        "thread_kwargs",
        "keep_uploads",
        "codex_bin",
    } & set(request.get("config", {})):
        raise ValueError("Runtime owns database, workspace, identity, process environment and retry configuration")
    if "repository" in request:
        raise ValueError("repository is agent configuration; set agent.repository=Repository(...)")
    if "repository" in request.get("config", {}):
        from agno.sandbox.repository import validate_repository

        validate_repository(request["config"]["repository"])
    from agno.sandbox.repository import validate_repository_override

    validate_repository_override(request.get("metadata"), request.get("config", {}).get("repository"))
    from agno.sandbox.media import validate_media

    validate_media(request.get("media", []))
    timeout = request.get("execution_timeout", 900)
    if not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 0 < timeout <= 86400:
        raise ValueError("Runtime execution timeout must be between 0 and 86400 seconds")
    expected = request.get("native_session_id")
    if expected is not None and (not isinstance(expected, str) or not expected or len(expected) > 256):
        raise ValueError("Runtime native_session_id must be a bounded native session id or null")
    if len(json.dumps(request, allow_nan=False, separators=(",", ":")).encode()) > _MAX_REQUEST:
        raise ValueError("Runtime request exceeds its limit")
