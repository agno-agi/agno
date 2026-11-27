"""Who Super Agent is talking to and what time it is, told to it on every turn.

The note is the first part of the unstored user message that also carries the conversation's linked
work, sent right before the person's input. It is built from what the request already carries: the
caller AgentOS verified when authorization is on, otherwise the user id the request sent, and the
user directory's name and email and the caller's roles where those exist.
"""

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from agno.db.schemas.scheduler import SCHEDULED_RUN_METADATA_KEY
from agno.run.authorization import _caller_authorization, in_finished_work_report
from agno.utils.log import log_debug, log_warning

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
    # A schedule with a saved authority marks the run on it. One with none, as when authorization is
    # off, marks the run's metadata.
    metadata = getattr(run_context, "metadata", None)
    marked = isinstance(metadata, dict) and bool(metadata.get(SCHEDULED_RUN_METADATA_KEY))
    return {
        "user_id": _clean(user_id),
        "verified": bool(principal),
        "service_account": bool(getattr(authority, "service_account", False)),
        "scheduled": bool(getattr(authority, "scheduled", False)) or marked,
        "roles": list(getattr(context, "roles", None) or []),
        "report": in_finished_work_report(run_context),
    }


def _note(who: Dict[str, Any], row: Optional[Dict[str, Any]], roles: List[str]) -> str:
    user_id = who["user_id"]
    if who["report"]:
        owner = f"This conversation belongs to user id {user_id}." if user_id else "This conversation names no user."
        return f"{_HEADER} {_FROM}: nobody. This is a finished-work report and no person is typing. {owner}"
    if who["scheduled"]:
        # Before the unknown user: a schedule that names no owner still has nobody present.
        owner = f" for user id {user_id}" if user_id else ", and the schedule names no user"
        return f"{_HEADER} {_FROM}: nobody. A schedule started this run{owner}."
    if user_id is None:
        return (
            f"{_HEADER} {_FROM}: unknown. The request named no user. Do not guess who the person is, "
            'and say you do not know when asked. Work asked for "me" is recorded with no owner.'
        )
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


def _now(timezone_identifier: Optional[str] = None, datetime_format: Optional[str] = None) -> str:
    """The current date and time in one line: weekday, date, time to the minute and timezone.

    The timezone and the format are the Team's own settings. With no timezone it is the server's
    local time, named with its offset. A set format is used as it is.
    """
    zone = None
    if timezone_identifier:
        try:
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(timezone_identifier)
        except Exception as exc:
            log_warning(f"Invalid timezone identifier: {exc}")
    now = datetime.now(zone) if zone is not None else datetime.now().astimezone()
    if datetime_format:
        return f"Now: {now.strftime(datetime_format)}."
    offset = now.strftime("%z")
    place = timezone_identifier if zone is not None else (now.tzname() or "server time")
    return f"Now: {now:%A} {now.day} {now:%B %Y}, {now:%H:%M} {place} (UTC{offset[:3]}:{offset[3:]})."


class TurnContext:
    """What Super Agent is told right before each message: the time, who the person is, then the
    work this conversation started. One unstored user message holds all of it.

    clock returns the Team's timezone identifier and datetime format, or is None to leave the time out.
    """

    def __init__(
        self,
        person: Person,
        work: Any,
        delivers: Optional[Callable[[], bool]] = None,
        clock: Optional[Callable[[], Tuple[Optional[str], Optional[str]]]] = None,
    ):
        self.person = person
        self.work = work
        # Whether Super Agent's model is sent the message at all.
        self.delivers = delivers
        self.clock = clock

    def _join(self, note: str, work: Optional[str]) -> str:
        # The time is read when the message is built, so each turn and each report carries its own.
        head = f"{_now(*self.clock())}\n{note}" if self.clock is not None else note
        return f"{head}\n\n{work}" if work else head

    def read(self, run_context: Any, session: Any = None) -> Optional[str]:
        if self.delivers is not None and not self.delivers():
            return None
        work = self.work.read(run_context, session) if self.work is not None else None
        return self._join(self.person.read(run_context), work)

    async def aread(self, run_context: Any, session: Any = None) -> Optional[str]:
        if self.delivers is not None and not self.delivers():
            return None
        work = await self.work.aread(run_context, session) if self.work is not None else None
        return self._join(await self.person.aread(run_context), work)
