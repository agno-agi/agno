from os import getenv
from typing import Any, Dict, List, Optional, Sequence, Union

from fastapi import HTTPException
from fastapi.routing import APIRouter

from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.github.events import (
    ALLOW_ANYONE,
    ALLOW_MEMBERS,
    COMMON_EVENT_KINDS,
    DEFAULT_EVENTS,
    GitHubEvent,
    parse_event,
    start_refusal,
)
from agno.os.interfaces.github.router import DeliveryLog, EventHandler, attach_routes
from agno.triggers.source import Delivery, EventField, SenderCheckFailed, Verdict
from agno.triggers.trigger import Events

# The permissions GitHub reports for a user on a repository that let them push to it.
_WRITE_PERMISSIONS = frozenset({"admin", "write"})


class GitHub(BaseInterface):
    """Receive GitHub webhook deliveries for chosen repositories.

    Without a handler, GitHub is a source for triggers: every verified delivery for a watched
    repository is matched against the triggers declared on AgentOS, stored, and answered; the runs
    start after the delivery is acknowledged. ``github.on("issues.opened")`` names the events a
    trigger listens for.

    With a handler, each verified, watched event is handed to it and GitHub runs no agent itself:
    the handler decides what an event becomes, e.g. a Company Task. AgentOS still needs an agent,
    team, workflow, knowledge base or database to start; a handler that records events usually
    brings the database. It must record the event durably before returning, because GitHub does not
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
        handler: Optional[EventHandler] = None,
        repositories: Optional[Union[str, Sequence[str]]] = None,
        webhook_secret: Optional[str] = None,
        events: Optional[Union[str, Sequence[str]]] = None,
        handle_bot_events: bool = False,
        prefix: str = "/github",
        tags: Optional[List[str]] = None,
        credentials: Optional[Any] = None,
    ):
        """
        Args:
            handler: Called with each verified, watched event; may be async. A sync handler runs in the
                threadpool. It may return a JSON-serializable dict, sent back under "result". Leave it
                out to send events to triggers.
            repositories: The repositories to watch, as "owner/name"; one may be given as a string.
            webhook_secret: The secret set on the webhook. Defaults to GITHUB_WEBHOOK_SECRET.
            events: The event and action pairs a handler receives, e.g. "issues.opened"; one may be given
                as a string. Defaults to new issues and comments. Triggers name their own events.
            handle_bot_events: Also handle events sent by bots, e.g. Dependabot. This includes the GitHub
                App's own account, so a handler that posts as the App must recognize its own events.
            prefix: Mount path; the webhook's payload URL is <prefix>/events.
            tags: OpenAPI tags.
            credentials: A ``GitHubAppCredentials``. With it, a trigger event whose payload does not show
                the sender as a member or collaborator still starts a run when GitHub reports that the
                sender has write access to the repository. Payloads have been seen to show a member
                whose organization membership is private as a contributor; without credentials such a
                member is ignored.
        """
        secret = webhook_secret or getenv("GITHUB_WEBHOOK_SECRET")
        if not secret:
            raise ValueError("GitHub requires a webhook secret: pass webhook_secret or set GITHUB_WEBHOOK_SECRET")
        if repositories is None:
            raise ValueError("GitHub requires the repositories to watch, as owner/name")
        if handler is None and events is not None:
            raise ValueError(
                "GitHub events= chooses what a handler receives. Without a handler, each trigger names "
                'its events: Trigger(on=github.on("issues.opened"), ...)'
            )
        # A single string is one item, not a sequence of its characters.
        if isinstance(repositories, str):
            repositories = [repositories]
        if events is None:
            events = DEFAULT_EVENTS
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
        self.credentials = credentials
        # Set by AgentOS: where deliveries go when there is no handler.
        self.triggers: Optional[Any] = None
        # The transport of the calls to GitHub's API; None is the network.
        self._http_transport: Optional[Any] = None

    @property
    def id(self) -> str:
        """The source id triggers point at: "github", or "github/<prefix>" for one mounted elsewhere."""
        name = self.prefix.strip("/")
        return "github" if name == "github" else f"github/{name}"

    # Offered as choices when a trigger is created. A trigger may name any kind GitHub sends.
    event_kinds = COMMON_EVENT_KINDS

    @property
    def accepts_triggers(self) -> bool:
        """Whether deliveries go to triggers: true when there is no handler."""
        return self.handler is None

    def on(
        self,
        *events: str,
        labels: Optional[Union[str, Sequence[str]]] = None,
        allow: str = ALLOW_MEMBERS,
    ) -> Events:
        """The events a trigger listens for, e.g. ``Trigger(on=github.on("issues.opened"), ...)``.

        Args:
            events: Event and action pairs, e.g. "issues.opened", "issues.labeled", "pull_request.opened".
            labels: Only events about an issue or pull request that has one of these labels. For a
                labeled event, the label just added must be one of them.
            allow: Who may start a run. "members", the default, is people GitHub shows as an owner,
                member or collaborator of the repository: the issue's author for a new issue, the
                commenter for a comment. "anyone" lets every sender through. A labeled event with
                ``labels`` is let through on the label when somebody other than the issue's author
                added it, because labeling another person's issue takes triage access. A label on
                the sender's own issue, such as one an issue template applies, is not a gate: the
                sender is then checked like any other.
        """
        if self.handler is not None:
            raise ValueError("This GitHub interface has a handler; triggers need one without: GitHub(repositories=...)")
        if not events or not all(isinstance(kind, str) and kind for kind in events):
            raise ValueError('on() takes event kinds, e.g. github.on("issues.opened")')
        filters = self.validate_filters({"allow": allow, "labels": labels})
        return Events(source_id=self.id, kinds=tuple(events), filters=filters, source=self)

    def validate_filters(self, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """A trigger's filter as it is stored: who may start a run, and the labels it is limited to.

        Raises:
            ValueError: The filter names something a GitHub trigger does not filter on.
        """
        given = dict(filters or {})
        unknown = sorted(set(given) - {"allow", "labels"})
        if unknown:
            raise ValueError(f"A GitHub trigger filters on allow and labels, got {unknown}")
        allow = given.get("allow") or ALLOW_MEMBERS
        if allow not in (ALLOW_MEMBERS, ALLOW_ANYONE):
            raise ValueError(f'allow must be "{ALLOW_MEMBERS}" or "{ALLOW_ANYONE}", got {allow!r}')
        labels = given.get("labels")
        if isinstance(labels, str):
            labels = [labels]
        if labels is not None and not (
            isinstance(labels, (list, tuple)) and all(isinstance(label, str) and label for label in labels)
        ):
            raise ValueError("labels is a list of label names")
        stored: Dict[str, Any] = {"allow": allow}
        if labels:
            stored["labels"] = [label.lower() for label in labels]
        return stored

    # -- What the trigger runtime asks of a source --

    def delivery(self, name: str, delivery_id: str, payload: Dict[str, Any]) -> Delivery:
        """A verified delivery as the trigger runtime takes it."""
        event = parse_event(name, delivery_id, payload)
        if event is None:
            action = payload.get("action")
            kind = f"{name}.{action}" if isinstance(action, str) else name
            described = {
                "delivery_id": delivery_id,
                "name": name,
                "action": action if isinstance(action, str) else None,
            }
            return Delivery(
                source_id=self.id,
                delivery_id=delivery_id,
                kind=kind,
                key=None,
                event=None,
                stored=described,
                trimmed=described,
                ignore_reason="the delivery names no repository",
            )
        reason = None
        if event.repository not in self.repositories:
            # A repository nobody chose to watch leaves only what says which delivery it was.
            unwatched = {
                "delivery_id": delivery_id,
                "name": event.name,
                "action": event.action,
                "repository": event.repository,
            }
            return Delivery(
                source_id=self.id,
                delivery_id=delivery_id,
                kind=event.kind,
                key=event.key,
                event=event,
                stored=unwatched,
                trimmed=unwatched,
                ignore_reason=f"repository {event.repository} is not watched",
            )
        if event.sender_type == "Bot" and not self.handle_bot_events:
            # Bots include this integration's own GitHub App, so what an agent posts starts no run.
            reason = f"sent by {event.sender}"
        return Delivery(
            source_id=self.id,
            delivery_id=delivery_id,
            kind=event.kind,
            key=event.key,
            event=event,
            stored=event.to_dict(),
            trimmed=event.trimmed(),
            ignore_reason=reason,
        )

    def check(self, event: GitHubEvent, filters: Dict[str, Any]) -> Verdict:
        """Whether an event passes a trigger's filter: its labels, and who may start a run."""
        reason, sender_unknown = start_refusal(
            event, labels=filters.get("labels"), allow=filters.get("allow") or ALLOW_MEMBERS
        )
        if reason is None:
            return Verdict()
        # The payload can understate a sender. With credentials GitHub is asked, when the event is claimed.
        return Verdict(reason=reason, check_sender=sender_unknown and self.credentials is not None)

    def load(self, stored: Dict[str, Any]) -> GitHubEvent:
        return GitHubEvent.from_dict(stored)

    def trim(self, stored: Dict[str, Any]) -> Dict[str, Any]:
        return GitHubEvent.from_dict(stored).trimmed()

    def describe(self, event: GitHubEvent) -> List[EventField]:
        """The event as a run reads it."""
        subject = event.issue or event.pull_request or {}
        fields = [EventField("repository", event.repository)]
        if subject:
            pull_request = event.pull_request is not None or bool(subject.get("pull_request"))
            fields.append(EventField("pull request" if pull_request else "issue", str(subject["number"])))
            fields.append(EventField("title", subject.get("title") or ""))
            fields.append(EventField("author", subject.get("author") or ""))
            fields.append(EventField("url", subject.get("url") or ""))
        if event.action == "labeled":
            fields.append(EventField("label added", str((event.payload.get("label") or {}).get("name") or "")))
        if event.comment:
            fields.append(EventField("comment by", event.comment.get("author") or ""))
            fields.append(EventField("comment url", event.comment.get("url") or ""))
            fields.append(EventField("comment", event.comment.get("body") or "", block=True))
        elif subject:
            fields.append(EventField("body", subject.get("body") or "", block=True))
        else:
            fields.append(EventField("sender", event.sender))
        return fields

    def run_metadata(self, event: GitHubEvent) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {"repository": event.repository, "delivery_id": event.delivery_id}
        if event.installation_id is not None:
            metadata["installation_id"] = event.installation_id
        return metadata

    async def asender_refusal(self, event: GitHubEvent) -> Optional[str]:
        """Ask GitHub for the sender's permission on the repository; the reason when it is below write.

        Raises:
            SenderCheckFailed: GitHub refused the credentials (401 or 403).
        """
        if self.credentials is None:
            return f"{event.sender} is not shown as a member or collaborator, and no GitHub App credentials are set"
        import httpx

        installation_id = event.installation_id
        if installation_id is None:
            installation_id = await self.credentials.ainstallation_id(event.repository)
        token = await self.credentials.atoken(installation_id)
        api_url = getattr(self.credentials, "api_url", "https://api.github.com")
        async with httpx.AsyncClient(timeout=10.0, transport=self._http_transport) as client:
            response = await client.get(
                f"{api_url}/repos/{event.repository}/collaborators/{event.sender}/permission",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if response.status_code in (401, 403):
            # An answer about the credentials, not about the sender. Asking again changes nothing.
            raise SenderCheckFailed(
                f"GitHub refused the credentials ({response.status_code}) for {event.repository}; "
                "check the GitHub App's permissions and its installation"
            )
        # GitHub answers 404 for a user who is not a collaborator.
        permission = "none"
        if response.status_code != 404:
            response.raise_for_status()
            permission = str(response.json().get("permission") or "none")
        if permission in _WRITE_PERMISSIONS:
            return None
        return (
            f"{event.sender} has {permission} access to {event.repository}; write access starts a run. "
            'To let them start one, pass allow="anyone" to on(), or use the issues.labeled event with labels=[...]'
        )

    async def _deliver(self, name: str, delivery_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.triggers is None:
            raise HTTPException(status_code=503, detail="No trigger is declared for this GitHub source")
        return await self.triggers.areceive(self, self.delivery(name, delivery_id, payload))

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            handler=self.handler,
            secret=self.webhook_secret,
            repositories=self.repositories,
            events=self.events,
            handle_bot_events=self.handle_bot_events,
            deliveries=self.deliveries,
            deliver=self._deliver if self.handler is None else None,
        )
        return self.router
