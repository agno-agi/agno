from dataclasses import dataclass
from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple

DEFAULT_EVENTS = ("issues.opened", "issue_comment.created")

# author_association values that show the sender works on the repository.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# Who may start a run through a trigger: people GitHub shows as working on the repository, or anyone.
ALLOW_MEMBERS = "members"
ALLOW_ANYONE = "anyone"


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
    # Set on pull request events, in the shape of ``issue``.
    pull_request: Optional[Dict[str, Any]] = None

    @property
    def kind(self) -> str:
        """The event and action together, e.g. "issues.opened"."""
        return f"{self.name}.{self.action}" if self.action else self.name

    @property
    def number(self) -> Optional[int]:
        """The issue or pull request the event is about."""
        subject = self.issue or self.pull_request
        return subject["number"] if subject else None

    @property
    def key(self) -> Optional[str]:
        """What groups events into one conversation: the issue or pull request, e.g. "owner/name#12"."""
        number = self.number
        return f"{self.repository}#{number}" if number is not None else None

    def to_dict(self, payload: bool = True) -> Dict[str, Any]:
        """The event as stored. Without the payload it only describes what arrived."""
        data: Dict[str, Any] = {
            "delivery_id": self.delivery_id,
            "name": self.name,
            "action": self.action,
            "repository": self.repository,
            "sender": self.sender,
            "sender_type": self.sender_type,
            "issue": self.issue,
            "comment": self.comment,
            "pull_request": self.pull_request,
            "installation_id": self.installation_id,
        }
        if payload:
            data["payload"] = self.payload
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GitHubEvent":
        return cls(
            delivery_id=data.get("delivery_id") or "",
            name=data.get("name") or "",
            action=data.get("action"),
            repository=data.get("repository") or "",
            sender=data.get("sender") or "",
            sender_type=data.get("sender_type") or "",
            issue=data.get("issue"),
            comment=data.get("comment"),
            payload=data.get("payload") or {},
            installation_id=data.get("installation_id"),
            pull_request=data.get("pull_request"),
        )


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
        pull_request=_issue(payload.get("pull_request")),
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


def _login(value: Any) -> str:
    return str(((value or {}).get("user") or {}).get("login") or "")


def sender_association(event: GitHubEvent) -> Optional[str]:
    """What the payload says about the sender's tie to the repository, when it says anything.

    GitHub puts author_association on what the sender wrote: the comment for a comment event, the
    issue or pull request when the sender opened it. For anything else, such as a label added by
    someone other than the author, the payload carries no association for the sender.
    """
    for name in ("comment", "review", "issue", "pull_request"):
        written = event.payload.get(name)
        if isinstance(written, dict) and event.sender and _login(written) == event.sender:
            association = written.get("author_association")
            return association if isinstance(association, str) else None
    return None


def label_names(event: GitHubEvent) -> List[str]:
    """The labels on the event's issue or pull request, lowercased."""
    subject = event.payload.get("issue") or event.payload.get("pull_request") or {}
    labels = subject.get("labels") if isinstance(subject, dict) else None
    return [str(label.get("name") or "").lower() for label in labels or [] if isinstance(label, dict)]


def start_refusal(
    event: GitHubEvent, labels: Optional[Sequence[str]] = None, allow: str = ALLOW_MEMBERS
) -> Tuple[Optional[str], bool]:
    """Why an event may not start a run for a trigger, and whether asking GitHub could still allow it.

    On a public repository anyone can open an issue or comment, so by default only people GitHub
    shows as working on the repository start a run. A labeled event with a label filter is let
    through on the label alone: applying a label takes triage access. Use a label no issue
    template applies, because a template applies its labels for whoever opens the issue.
    """
    wanted = [label.lower() for label in labels or []]
    labeled = event.action == "labeled"
    if wanted:
        if labeled:
            added = str((event.payload.get("label") or {}).get("name") or "").lower()
            if added not in wanted:
                return f"the label added, {added or 'none'}, is not one of {wanted}", False
        elif not set(wanted) & set(label_names(event)):
            return f"none of the labels {wanted} is on #{event.number}", False
    if allow == ALLOW_ANYONE or (labeled and wanted):
        return None, False
    association = sender_association(event)
    if association in TRUSTED_ASSOCIATIONS:
        return None, False
    shown = f"author_association {association}" if association else "no association for the sender"
    return (
        f"{event.sender or 'the sender'} is not shown as a member or collaborator of {event.repository} "
        f'({shown}). To let them start a run, pass allow="anyone" to on(), or use the issues.labeled '
        "event with labels=[...] so that a maintainer starts it by adding a label",
        True,
    )
