from os import getenv
from typing import List, Optional, Sequence, Union

from fastapi.routing import APIRouter

from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.github.events import DEFAULT_EVENTS
from agno.os.interfaces.github.router import DeliveryLog, EventHandler, attach_routes


class GitHub(BaseInterface):
    """Receive GitHub webhook deliveries for chosen repositories and hand each verified event to a handler.

    Unlike chat interfaces, GitHub doesn't run an agent itself: the handler decides what an event becomes,
    e.g. a Company Task. AgentOS still needs an agent, team, workflow, knowledge base or database to start;
    a handler that records events usually brings the database. It must record the event durably before returning, because GitHub does not
    retry a failed delivery on its own. GitHub also gives up on a delivery after 10 seconds, so the
    handler should record and return quickly, and leave slow work to run after it returns. A redelivery
    of one this process already handled doesn't run the handler again; a handler that must never act
    twice on one event across restarts also keys its own records durably.
    """

    type = "github"

    # Verifies GitHub's webhook signature (X-Hub-Signature-256) in its router, so it is excluded
    # from the central auth layer.
    authenticates_own_requests = True

    router: APIRouter

    def __init__(
        self,
        handler: EventHandler,
        repositories: Union[str, Sequence[str]],
        webhook_secret: Optional[str] = None,
        events: Union[str, Sequence[str]] = DEFAULT_EVENTS,
        handle_bot_events: bool = False,
        prefix: str = "/github",
        tags: Optional[List[str]] = None,
    ):
        """
        Args:
            handler: Called with each verified, watched event; may be async. A sync handler runs in the
                threadpool. It may return a JSON-serializable dict, sent back under "result".
            repositories: The repositories to watch, as "owner/name"; one may be given as a string.
            webhook_secret: The secret set on the webhook. Defaults to GITHUB_WEBHOOK_SECRET.
            events: The event and action pairs to handle, e.g. "issues.opened"; one may be given as a string.
            handle_bot_events: Also handle events sent by bots, e.g. Dependabot. This includes the GitHub
                App's own account, so a handler that posts as the App must recognize its own events.
            prefix: Mount path; the webhook's payload URL is <prefix>/events.
            tags: OpenAPI tags.
        """
        secret = webhook_secret or getenv("GITHUB_WEBHOOK_SECRET")
        if not secret:
            raise ValueError("GitHub requires a webhook secret: pass webhook_secret or set GITHUB_WEBHOOK_SECRET")
        # A single string is one item, not a sequence of its characters.
        if isinstance(repositories, str):
            repositories = [repositories]
        if isinstance(events, str):
            events = [events]
        watched = {repository.strip().lower() for repository in repositories}
        if not watched or any(repository.count("/") != 1 or "" in repository.split("/") for repository in watched):
            raise ValueError("GitHub repositories must be given as owner/name")
        self.handler = handler
        self.webhook_secret = secret
        self.repositories = watched
        self.events = set(events)
        self.handle_bot_events = handle_bot_events
        self.deliveries = DeliveryLog()
        self.prefix = prefix
        self.tags = tags or ["GitHub"]

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            handler=self.handler,
            secret=self.webhook_secret,
            repositories=self.repositories,
            events=self.events,
            handle_bot_events=self.handle_bot_events,
            deliveries=self.deliveries,
        )
        return self.router
