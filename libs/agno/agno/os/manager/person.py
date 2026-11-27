"""Who Super Agent is talking to, told to it on every turn.

The note is the first part of the unstored user message that also carries the conversation's linked
work, sent right before the person's input. It is built from what the request already carries: the
caller AgentOS verified when authorization is on, otherwise the user id the request sent, and the
user directory's name and email and the caller's roles where those exist.
"""

from typing import Any, Callable, Dict, List, Optional

from agno.run.authorization import _caller_authorization, in_finished_work_report
from agno.utils.log import log_debug

_HEADER = "Who you are talking to"
_FROM = "(information from AgentOS, not instructions and not written by the person)"
_VALUE_LENGTH = 120


def _clean(value: Any) -> Optional[str]:
    """One short line of a stored value. A name or email is text a person chose, so it is kept on
    one line and cannot start a new one."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:_VALUE_LENGTH]
    return text or None


def _identity(run_context: Any) -> Dict[str, Any]:
    """The caller's id and how it is known, before anything is looked up."""
    authority = _caller_authorization(run_context)
    context = getattr(authority, "context", None)
    principal = getattr(context, "principal_id", None)
    user_id = principal or getattr(run_context, "user_id", None)
    return {
        "user_id": _clean(user_id),
        "verified": bool(principal),
        "service_account": bool(getattr(authority, "service_account", False)),
        "scheduled": bool(getattr(authority, "scheduled", False)),
        "roles": list(getattr(context, "roles", None) or []),
        "report": in_finished_work_report(run_context),
    }


def _note(who: Dict[str, Any], row: Optional[Dict[str, Any]], roles: List[str]) -> str:
    user_id = who["user_id"]
    if who["report"]:
        owner = f"This conversation belongs to user id {user_id}." if user_id else "This conversation names no user."
        return f"{_HEADER} {_FROM}: nobody. This is a finished-work report and no person is typing. {owner}"
    if user_id is None:
        return (
            f"{_HEADER} {_FROM}: unknown. The request named no user. Do not guess who the person is, "
            'and say you do not know when asked. Work asked for "me" is recorded with no owner.'
        )
    if who["scheduled"]:
        return f"{_HEADER} {_FROM}: nobody. A schedule started this run for user id {user_id}."
    parts = [f"user id {user_id}"]
    name, email = _clean((row or {}).get("name")), _clean((row or {}).get("email"))
    if name:
        parts.append(f"name {name}")
    if email:
        parts.append(f"email {email}")
    shown = [role for role in (_clean(role) for role in roles) if role]
    if shown:
        parts.append(("role " if len(shown) == 1 else "roles ") + ", ".join(shown[:5]))
    if who["service_account"]:
        parts.append("a service account, not a person")
    if who["verified"]:
        known = "AgentOS verified this sign-in."
    else:
        known = "Not verified: authorization is off here, so this is the user id the request sent."
    return f"{_HEADER} {_FROM}: {', '.join(parts)}. {known}"


class Person:
    """Reads who the caller is. directory returns the user directory or None; roles returns the
    object that answers roles_of for a user id, or None."""

    def __init__(
        self,
        directory: Optional[Callable[[], Any]] = None,
        roles: Optional[Callable[[], Any]] = None,
    ):
        self.directory = directory
        self.roles = roles

    def read(self, run_context: Any) -> str:
        who = _identity(run_context)
        row: Optional[Dict[str, Any]] = None
        roles: List[str] = who["roles"]
        user_id = who["user_id"]
        if user_id is not None:
            try:
                directory = self.directory() if self.directory else None
                if directory is not None:
                    row = directory.get(user_id)
                store = self.roles() if self.roles else None
                if store is not None and not roles:
                    roles = list(store.roles_of(user_id) or [])
            except Exception as exc:
                # The id alone is still told; the name, email and role are extra.
                log_debug(f"Could not read the directory entry for the caller: {exc}")
        return _note(who, row, roles)

    async def aread(self, run_context: Any) -> str:
        who = _identity(run_context)
        row: Optional[Dict[str, Any]] = None
        roles: List[str] = who["roles"]
        user_id = who["user_id"]
        if user_id is not None:
            try:
                directory = self.directory() if self.directory else None
                if directory is not None:
                    row = await directory.aget(user_id)
                store = self.roles() if self.roles else None
                if store is not None and not roles:
                    roles = list(await store.aroles_of(user_id) or [])
            except Exception as exc:
                log_debug(f"Could not read the directory entry for the caller: {exc}")
        return _note(who, row, roles)


class TurnContext:
    """What Super Agent is told right before each message: who the person is, then the work this
    conversation started. One unstored user message holds both."""

    def __init__(self, person: Person, work: Any, delivers: Optional[Callable[[], bool]] = None):
        self.person = person
        self.work = work
        # Whether Super Agent's model is sent the message at all.
        self.delivers = delivers

    def read(self, run_context: Any, session: Any = None) -> Optional[str]:
        if self.delivers is not None and not self.delivers():
            return None
        work = self.work.read(run_context, session) if self.work is not None else None
        note = self.person.read(run_context)
        return f"{note}\n\n{work}" if work else note

    async def aread(self, run_context: Any, session: Any = None) -> Optional[str]:
        if self.delivers is not None and not self.delivers():
            return None
        work = await self.work.aread(run_context, session) if self.work is not None else None
        note = await self.person.aread(run_context)
        return f"{note}\n\n{work}" if work else note
