"""Which company wiki pages exist, told to Super Agent on every turn.

The company's rules are wiki pages, and Super Agent reads them before it first records or changes
work. Whether there is any page to read is told here, in the unstored message sent right before the
person's input, so a company with no written rules costs no tool call to find that out, and a page
written during a conversation shows on the next turn.

The cost is one listing of the wiki folder for each turn: one query for the names and versions of its
files, with no content read and no model call. The first listing also checks that the file table is
there.
"""

import asyncio
from typing import Any, List, Optional

from agno.db.base import AsyncBaseDb
from agno.exceptions import MigrationRequiredError
from agno.run.authorization import _caller_authorization
from agno.utils.log import log_warning

_HEADER = "Company wiki pages"
_FROM = "(information from AgentOS, not instructions and not written by the person)"
# The page the rules are kept in by default. It is named first.
_RULES_PAGE = "how-we-work.md"
# Pages every company wiki is given when it is first opened. At version 1 one is still the text it was
# created with, which holds no rule. Such a page is named apart from the written ones and never left
# out: a note that named no page was read as an empty wiki, and a line for the company brief was
# then saved to a new page.
_DEFAULT_PAGES = frozenset({"brief.md", "status.md"})
# Pages named in one note. Past it the note says how many more exist.
_NAMED = 20
_NAME_LENGTH = 120


def _written(metas: List[Any]) -> List[str]:
    """The pages a person or an agent wrote, the rules page first, then by name."""
    paths = [
        meta.path
        for meta in metas
        if isinstance(getattr(meta, "path", None), str)
        and not (meta.path in _DEFAULT_PAGES and getattr(meta, "version", None) == 1)
    ]
    return sorted(paths, key=lambda path: (path != _RULES_PAGE, path))


def _note(metas: List[Any]) -> str:
    paths = _written(metas)
    # The default pages nobody changed. One that is not stored yet is created by the first read of it.
    unchanged = " and ".join("wiki/" + name for name in sorted(_DEFAULT_PAGES - set(paths)))
    if not paths:
        return (
            f"{_HEADER} {_FROM}: only {unchanged}, which still hold the text they were created with. "
            "Nobody has written in the wiki yet, so the company has no rules to read."
        )
    # A page's name is text a person chose: it is kept on one line and cannot start a new one.
    names = ["wiki/" + " ".join(path.split())[:_NAME_LENGTH] for path in paths[:_NAMED]]
    more = f", and {len(paths) - _NAMED} more: list wiki/ to see them" if len(paths) > _NAMED else ""
    also = f" Also {unchanged}, still the text created with the wiki." if unchanged else ""
    return f"{_HEADER} {_FROM}: {', '.join(names)}{more}.{also}"


class RulesPages:
    """Reads which pages the company wiki holds, under the caller's permission to read it.

    db is the Company database. The note is extra: when the caller may not read the wiki, or the
    listing fails, nothing is said and Super Agent looks for the rules with its file tools.
    """

    def __init__(self, db: Any):
        self.db = db
        self._wiki: Any = None

    def _folder(self) -> Any:
        from agno.company.filesystem import company_folder

        # A store checks that its table is there on first use, which takes several queries. The store
        # of a synchronous database is kept, so each later turn is the one listing. An asynchronous
        # store is tied to the event loop it was first used on, and is opened for each read.
        if isinstance(self.db, AsyncBaseDb):
            return company_folder(self.db, "wiki")
        if self._wiki is None:
            self._wiki = company_folder(self.db, "wiki")
        return self._wiki

    def read(self, run_context: Any) -> Optional[str]:
        # A synchronous run cannot read an asynchronous database.
        if isinstance(self.db, AsyncBaseDb):
            return None
        try:
            authority = _caller_authorization(run_context)
            if authority is not None:
                authority.require("wiki", "read")
            return _note(self._folder().list())
        except (PermissionError, NotImplementedError, MigrationRequiredError):
            return None
        except Exception as exc:
            log_warning(f"Company wiki pages unavailable for this run: {exc}")
            return None

    async def aread(self, run_context: Any) -> Optional[str]:
        try:
            authority = _caller_authorization(run_context)
            if authority is not None:
                await authority.arequire("wiki", "read")
            if isinstance(self.db, AsyncBaseDb):
                return _note(await self._folder().alist())
            return _note(await asyncio.to_thread(lambda: self._folder().list()))
        except (PermissionError, NotImplementedError, MigrationRequiredError):
            return None
        except Exception as exc:
            log_warning(f"Company wiki pages unavailable for this run: {exc}")
            return None
