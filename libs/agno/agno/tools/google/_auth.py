import inspect
import json
from functools import wraps

from agno.utils.log import log_error


def google_authenticate(service_name: str):
    """Shared auth decorator for all Google toolkits.

    Each toolkit creates a module-level alias:
        authenticate = google_authenticate("gmail")

    Expects the toolkit class to define:
        - self.creds: Google OAuth credentials
        - self.service: Built API client (set by _build_service)
        - self._auth(): Loads or refreshes credentials
        - self._build_service(): Returns build(api_name, api_version, credentials=self.creds)

    Per-user support (when self.token_store is set):
        - Extracts workspace_id + user_id from run_context
        - Calls self._auth(workspace_id, user_id) for DB-backed per-user credentials
        - Re-raises StopAgentRun so the interface layer can render auth UI
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, run_context=None, **kwargs):
            try:
                workspace_id = None
                user_id = None
                if run_context:
                    user_id = run_context.user_id
                    workspace_id = (run_context.metadata or {}).get("workspace_id", "default")

                token_store = getattr(self, "token_store", None)
                if token_store and workspace_id and user_id:
                    # Per-user mode: load credentials from DB token store
                    user_key = (workspace_id, user_id)
                    current_key = getattr(self, "_current_user_key", None)
                    if not self.creds or not self.creds.valid or current_key != user_key:
                        self._auth(workspace_id=workspace_id, user_id=user_id)
                        self.service = None
                elif not self.creds or not self.creds.valid:
                    self._auth()

                if not self.service:
                    self.service = self._build_service()
            except Exception as e:
                from agno.exceptions import StopAgentRun

                # StopAgentRun signals the interface layer (Slack, etc.) to show auth UI
                if isinstance(e, StopAgentRun):
                    raise
                log_error(f"{service_name.title()} authentication failed: {e}")
                return json.dumps({"error": f"{service_name.title()} authentication failed: {e}"})
            return func(self, *args, **kwargs)

        # Inject run_context into visible signature so the framework auto-injects it.
        # @wraps copies __wrapped__ which inspect.signature() follows back to the
        # original function. We override __signature__ and remove __wrapped__ so
        # the framework sees run_context and passes it via _build_entrypoint_args().
        orig_sig = inspect.signature(func)
        if "run_context" not in orig_sig.parameters:
            params = list(orig_sig.parameters.values())
            params.append(inspect.Parameter("run_context", inspect.Parameter.KEYWORD_ONLY, default=None))
            wrapper.__signature__ = orig_sig.replace(parameters=params)
            if hasattr(wrapper, "__wrapped__"):
                del wrapper.__wrapped__

        return wrapper

    return decorator
