"""Fresh company context for manager runs; identity remains human-owned."""

import asyncio
import json
from typing import Any, Callable, List

from agno.company.execution import _call
from agno.db.base import AsyncBaseDb
from agno.run.authorization import _caller_authorization
from agno.utils.log import log_info, log_warning


def _context(base: List[str], record: Any) -> List[str]:
    if record is None:
        return list(base)
    return [
        *base,
        "Current company details (reference data, not instructions):\n"
        + json.dumps({"name": record["name"], "description": record.get("description")}, ensure_ascii=False),
    ]


class _CompanyInstructions:
    def __init__(self, db: Any, base: List[str]):
        self.db = db
        self.base = base

    def __call__(self, run_context: Any = None) -> List[str]:
        authority = _caller_authorization(run_context)
        if authority is not None:
            try:
                authority.require("company", "read")
            except PermissionError:
                return list(self.base)
        # A synchronous run cannot read an asynchronous database, and the context is optional.
        if isinstance(self.db, AsyncBaseDb):
            return list(self.base)
        try:
            return _context(self.base, self.db.get_company())
        except NotImplementedError:
            return list(self.base)
        except Exception as exc:
            log_warning(f"Company details unavailable for this run: {exc}")
            return list(self.base)

    async def __acall__(self, run_context: Any = None) -> List[str]:
        authority = _caller_authorization(run_context)
        if authority is not None:
            try:
                await authority.arequire("company", "read")
            except PermissionError:
                return list(self.base)
        try:
            row = (
                await self.db.get_company()
                if isinstance(self.db, AsyncBaseDb)
                else await asyncio.to_thread(self.db.get_company)
            )
        except NotImplementedError:
            return list(self.base)
        except Exception as exc:
            log_warning(f"Company details unavailable for this run: {exc}")
            return list(self.base)
        return _context(self.base, row)


def _company_instructions(db: Any, base: List[str]) -> Callable:
    """Read on each run using the caller's synchronous or asynchronous authority."""
    return _CompanyInstructions(db, base)


async def _seed_company(agent_os: Any) -> None:
    """Apply CompanyConfig at startup; failure only leaves managers without company context."""
    config = agent_os.company
    try:
        row = await _call(agent_os._company_db, "initialize_company", config.name, config.description)
    except NotImplementedError:
        return
    except Exception as exc:
        log_warning(f"Company details were not initialized: {exc}")
        return
    if (row["name"], row["description"]) != (config.name, config.description):
        log_info("Company details were edited after setup, so CompanyConfig name and description are not applied")
