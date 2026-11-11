from os import getenv
from typing import List, Optional, Sequence

from fastapi.routing import APIRouter

from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.github.events import DEFAULT_EVENTS
from agno.os.interfaces.github.router import EventHandler, attach_routes


class GitHub(BaseInterface):
    """Receive GitHub webhook deliveries for chosen repositories and hand each verified event to a handler.

    Unlike chat interfaces, GitHub is not bound to an agent: the handler decides what an event becomes,
    e.g. a Company Task. It must record the event durably before returning, because GitHub does not
    retry a failed delivery on its own.
    """

    type = "github"

    # Verifies GitHub's webhook signature (X-Hub-Signature-256) in its router, so it is excluded
    # from the central auth layer.
    authenticates_own_requests = True

    router: APIRouter

    def __init__(
        self,
        handler: EventHandler,
        repositories: Sequence[str],
        webhook_secret: Optional[str] = None,
        events: Sequence[str] = DEFAULT_EVENTS,
        ignore_logins: Sequence[str] = (),
        prefix: str = "/github",
        tags: Optional[List[str]] = None,
    ):
        """
        Args:
            handler: Called with each verified, watched event; may be async. Its return value is merged into
                the response.
            repositories: The repositories to watch, as "owner/name".
            webhook_secret: The secret set on the webhook. Defaults to GITHUB_WEBHOOK_SECRET.
            events: The event and action pairs to handle, e.g. "issues.opened".
            ignore_logins: Logins whose events are ignored, e.g. the account whose token posts Agno's comments.
            prefix: Mount path; the webhook's payload URL is <prefix>/events.
            tags: OpenAPI tags.
        """
        secret = webhook_secret or getenv("GITHUB_WEBHOOK_SECRET")
        if not secret:
            raise ValueError("GitHub requires a webhook secret: pass webhook_secret or set GITHUB_WEBHOOK_SECRET")
        watched = {repository.strip().lower() for repository in repositories}
        if not watched or any(repository.count("/") != 1 or "" in repository.split("/") for repository in watched):
            raise ValueError("GitHub repositories must be given as owner/name")
        self.handler = handler
        self.webhook_secret = secret
        self.repositories = watched
        self.events = set(events)
        self.ignore_logins = {login.lower() for login in ignore_logins}
        self.prefix = prefix
        self.tags = tags or ["GitHub"]

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        return attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            handler=self.handler,
            secret=self.webhook_secret,
            repositories=self.repositories,
            events=self.events,
            ignore_logins=self.ignore_logins,
        )
