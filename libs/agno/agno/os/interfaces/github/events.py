from dataclasses import dataclass
from typing import Any, Collection, Dict, Optional

DEFAULT_EVENTS = ("issues.opened", "issue_comment.created")


@dataclass(frozen=True)
class GitHubEvent:
    """One verified webhook delivery, reduced to what handlers act on. The full payload stays available."""

    delivery_id: str
    name: str
    action: Optional[str]
    repository: str
    sender: str
    sender_type: str
    issue: Optional[Dict[str, Any]]
    comment: Optional[Dict[str, Any]]
    payload: Dict[str, Any]
    # Set when a GitHub App sent the delivery: the installation whose token acts on this repository.
    installation_id: Optional[int] = None

    @property
    def kind(self) -> str:
        """The event and action together, e.g. "issues.opened"."""
        return f"{self.name}.{self.action}" if self.action else self.name


def _issue(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("number"), int):
        return None
    return {
        "number": value["number"],
        "title": value.get("title") or "",
        "body": value.get("body") or "",
        "url": value.get("html_url"),
        "state": value.get("state"),
        "author": (value.get("user") or {}).get("login"),
        # GitHub sends pull request conversations as issues with this key.
        "pull_request": "pull_request" in value,
    }


def _comment(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict) or value.get("id") is None:
        return None
    return {
        "id": value["id"],
        "body": value.get("body") or "",
        "url": value.get("html_url"),
        "author": (value.get("user") or {}).get("login"),
    }


def parse_event(name: str, delivery_id: str, payload: Dict[str, Any]) -> Optional[GitHubEvent]:
    """The event a delivery describes, or None when it names no repository."""
    repository = (payload.get("repository") or {}).get("full_name")
    if not isinstance(repository, str):
        return None
    sender = payload.get("sender") or {}
    action = payload.get("action")
    installation = (payload.get("installation") or {}).get("id")
    return GitHubEvent(
        delivery_id=delivery_id,
        name=name,
        action=action if isinstance(action, str) else None,
        repository=repository.lower(),
        sender=str(sender.get("login") or ""),
        sender_type=str(sender.get("type") or ""),
        issue=_issue(payload.get("issue")),
        comment=_comment(payload.get("comment")),
        payload=payload,
        installation_id=installation if isinstance(installation, int) else None,
    )


def ignore_reason(
    event: GitHubEvent,
    repositories: Collection[str],
    events: Collection[str],
    handle_bot_events: bool = False,
) -> Optional[str]:
    """Why an event is not handled, or None when it is."""
    if event.repository not in repositories:
        return f"repository {event.repository} is not watched"
    if event.kind not in events:
        return f"{event.kind} is not handled"
    # Bots include this integration's own GitHub App, so what it posts is not handled again.
    if event.sender_type == "Bot" and not handle_bot_events:
        return f"sent by {event.sender}"
    return None
