"""Check AgentOS settings, database access and service status without model calls.

Each check reports whether it inspected settings (``configuration``) or made a
database or network request (``live``). Reports do not include secret values.
Credential checks report whether a value is set. Errors include the exception
type but omit the message, which could contain credentials.
"""

import asyncio
import inspect
import os
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

if TYPE_CHECKING:
    from agno.os.app import AgentOS

Status = Literal["PASS", "WARN", "FAIL", "SKIP"]
Evidence = Literal["configuration", "live"]

CHECKS: Sequence[str] = ("database", "authorization", "components", "registry", "interfaces", "scheduler", "mcp")

# Worst status wins for the report as a whole.
_SEVERITY = {"FAIL": 3, "WARN": 2, "PASS": 1, "SKIP": 0}
_SCHEDULE_PAGE_SIZE = 100
_SCHEDULE_MAX_PAGES = 100


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str
    evidence: Evidence = "configuration"


@dataclass
class DiagnosticReport:
    run_id: str
    created_at: int
    status: Status
    checks: List[CheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def _call_db(db: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    fn = getattr(db, method_name)
    # Pass only the optional arguments this database adapter supports.
    parameters = inspect.signature(fn).parameters
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
        kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


async def _probe_sql_connection(db: Any) -> None:
    # SQL table discovery can suppress connection errors and make a failed session
    # read look empty. Probe the connection without requiring or creating tables.
    engine = getattr(db, "db_engine", None)
    if engine is None:
        return
    from sqlalchemy import Engine, text
    from sqlalchemy.ext.asyncio import AsyncEngine

    if isinstance(engine, AsyncEngine):
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    elif isinstance(engine, Engine):

        def probe() -> None:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))

        await asyncio.to_thread(probe)


async def arun_diagnostics(
    agent_os: "AgentOS",
    *,
    required_env: Sequence[str] = (),
    network_probe: bool = False,
    public_url: Optional[str] = None,
) -> DiagnosticReport:
    """Run every check and return a report.

    Args:
        agent_os: The OS to inspect.
        required_env: Environment variable names whose presence is required. Only
            presence is reported, never the value.
        network_probe: Also POST an MCP initialize to ``public_url`` and report the
            HTTP status. Off by default: it needs the public address and a network.
        public_url: The public OS base URL, including any proxy path prefix. The probe
            appends the configured MCP path, or uses the root for the configured MCP
            root host. Required when ``network_probe`` is on.
    """
    if network_probe and not public_url:
        raise ValueError("network_probe requires public_url")
    checks: List[CheckResult] = []
    for name in CHECKS:
        try:
            checks.append(await _check(agent_os, name, network_probe=network_probe, public_url=public_url))
        except Exception as exc:
            # Driver and provider exceptions can echo credentials; keep the type only.
            checks.append(CheckResult(name=name, status="FAIL", detail=f"Check failed ({type(exc).__name__})"))
    if agent_os.company is not None:
        reason = agent_os.company_manager_unavailable_reason
        checks.append(
            CheckResult(
                "company", "WARN" if reason else "PASS", reason or "Company Manager configured; model not called"
            )
        )
    source_env: set[str] = set()
    if agent_os.company is not None:
        for declaration in agent_os.company.products:
            from agno.company.declarations import Product

            product = declaration if isinstance(declaration, Product) else Product.model_validate(declaration)
            source_env.update(source.credential_ref for source in product.sources if source.credential_ref)
        if agent_os._company_db is not None:
            try:
                page = 1
                while True:
                    rows, total = await _call_db(agent_os._company_db, "get_sources", limit=100, page=page)
                    source_env.update(row["credential_ref"] for row in rows if row.get("credential_ref"))
                    if page * 100 >= total:
                        break
                    page += 1
            except Exception as exc:
                checks.append(CheckResult("company_sources", "FAIL", f"Source check failed ({type(exc).__name__})"))
    for key in sorted(set(required_env) | source_env):
        present = bool(os.getenv(key))
        checks.append(
            CheckResult(
                name=f"env:{key}",
                status="PASS" if present else "FAIL",
                detail="Set" if present else "Not set",
            )
        )
    status: Status = max((check.status for check in checks), key=lambda s: _SEVERITY[s], default="SKIP")
    return DiagnosticReport(run_id=str(uuid4()), created_at=int(time.time()), status=status, checks=checks)


def run_diagnostics(
    agent_os: "AgentOS",
    *,
    required_env: Sequence[str] = (),
    network_probe: bool = False,
    public_url: Optional[str] = None,
) -> DiagnosticReport:
    """Sync variant of arun_diagnostics. Inside a running event loop use the async variant."""
    coroutine = arun_diagnostics(
        agent_os, required_env=required_env, network_probe=network_probe, public_url=public_url
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    coroutine.close()
    raise RuntimeError("run_diagnostics was called inside an event loop; await arun_diagnostics instead")


async def _check(agent_os: "AgentOS", name: str, *, network_probe: bool, public_url: Optional[str]) -> CheckResult:
    if name == "database":
        if agent_os.db is None:
            return CheckResult(name, "SKIP", "No OS database configured")
        await _probe_sql_connection(agent_os.db)
        # Also exercise session reads. Runs are not attached and rows are not
        # deserialized: a long conversation must not make this slow.
        await _call_db(agent_os.db, "get_sessions", limit=1, page=1, deserialize=False, include_runs=False)
        return CheckResult(name, "PASS", "Session read succeeded", evidence="live")

    if name == "authorization":
        if agent_os.authorization:
            return CheckResult(name, "PASS", "Authorization enabled")
        return CheckResult(name, "WARN", "Authorization disabled; every caller is anonymous")

    if name == "components":
        entries = [*(agent_os.agents or []), *(agent_os.teams or []), *(agent_os.workflows or [])]
        if any(not getattr(entry, "id", None) for entry in entries):
            return CheckResult(name, "FAIL", "A registered component has no id")
        for components in (agent_os.agents, agent_os.teams, agent_os.workflows):
            ids = [entry.id for entry in components or []]
            if len(ids) != len(set(ids)):
                return CheckResult(name, "FAIL", "Duplicate component ids within a component type")
        return CheckResult(name, "PASS", f"{len(entries)} components registered with unique ids within each type")

    if name == "registry":
        registry = agent_os.registry
        if registry is None:
            return CheckResult(name, "SKIP", "No registry")
        knowledge_names = [getattr(k, "name", None) for k in registry.knowledge]
        learning_names = [getattr(m, "name", None) for m in registry.learning]
        if len(knowledge_names) != len(set(knowledge_names)) or len(learning_names) != len(set(learning_names)):
            return CheckResult(name, "FAIL", "Two registry knowledge bases or learning machines share a name")
        return CheckResult(name, "PASS", "Declared knowledge and learning names are unique")

    if name == "interfaces":

        def credentials_present(interface: Any) -> bool:
            # Match SlackTools' token fallback and the signature verifier's
            # explicit-secret precedence (an empty explicit secret stays empty).
            from agno.os.interfaces.slack.security import SLACK_SIGNING_SECRET

            token = getattr(interface, "token", None) or os.getenv("SLACK_TOKEN")
            secret = getattr(interface, "signing_secret", None)
            if secret is None:
                secret = SLACK_SIGNING_SECRET
            return bool(token and secret)

        missing = [
            interface
            for interface in agent_os.interfaces
            if getattr(interface, "type", None) == "slack" and not credentials_present(interface)
        ]
        if missing:
            return CheckResult(name, "FAIL", "A Slack interface is missing its token or signing secret")
        return CheckResult(name, "PASS", f"{len(agent_os.interfaces)} interfaces configured; delivery not tested")

    if name == "scheduler":
        if not getattr(agent_os, "_scheduler_enabled", False):
            return CheckResult(name, "SKIP", "Scheduler disabled")
        if agent_os.db is None:
            return CheckResult(name, "FAIL", "Scheduler enabled without a database")
        # raise_on_error: adapters otherwise answer an unreadable table with an empty list,
        # which would read as "no overdue schedules".
        now = int(time.time())
        scanned = 0
        for page in range(1, _SCHEDULE_MAX_PAGES + 1):
            result = await _call_db(
                agent_os.db, "get_schedules", enabled=True, limit=_SCHEDULE_PAGE_SIZE, page=page, raise_on_error=True
            )
            rows, total = result if isinstance(result, tuple) else (result, None)
            rows = rows or []
            scanned += len(rows)
            overdue = [
                row
                for row in rows
                if (row.get("next_run_at") or now) < now - 900
                and not (row.get("locked_by") and (row.get("locked_at") or 0) > now - 300)
            ]
            if overdue:
                return CheckResult(
                    name, "WARN", f"At least {len(overdue)} enabled schedules are overdue by 15 minutes", "live"
                )
            if (total is not None and scanned >= total) or (total is None and len(rows) < _SCHEDULE_PAGE_SIZE):
                return CheckResult(name, "PASS", "No overdue schedules; poller liveness not proven", evidence="live")
            if not rows:
                break  # The catalog changed or the adapter could not supply the remaining rows.
        return CheckResult(name, "WARN", f"Schedule scan incomplete after {scanned} rows; health not proven", "live")

    if name == "mcp":
        if not agent_os.mcp:
            return CheckResult(name, "SKIP", "MCP server disabled")
        if not network_probe:
            return CheckResult(name, "PASS", "MCP server configured; endpoint not probed")
        import httpx

        assert public_url is not None
        config = agent_os.mcp_config
        path = config.path if config is not None else "/mcp"
        if config is not None and config.root_host == urlsplit(public_url).hostname:
            path = "/"
        async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
            response = await client.post(
                public_url.rstrip("/") + path,
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "agno-diagnostics", "version": "1"},
                    },
                },
            )
        code = response.status_code
        if 200 <= code < 300:
            return CheckResult(name, "PASS", f"MCP initialize answered HTTP {code}; tool execution not tested", "live")
        if code in (401, 403):
            # A gated server refusing an anonymous probe is the healthy answer.
            return CheckResult(name, "PASS", f"MCP endpoint requires authentication (HTTP {code})", "live")
        if code == 404 or code >= 500:
            return CheckResult(name, "FAIL", f"MCP endpoint returned HTTP {code}", evidence="live")
        return CheckResult(name, "WARN", f"MCP endpoint returned unexpected HTTP {code}", evidence="live")

    raise ValueError(f"Unknown diagnostic check: {name}")
