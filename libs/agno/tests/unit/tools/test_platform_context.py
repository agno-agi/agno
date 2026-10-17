import asyncio
import json
from types import SimpleNamespace

import pytest

from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.db.sqlite import SqliteDb
from agno.tools import platform_context
from agno.tools.platform_context import PlatformContextTools


@pytest.fixture
def db(tmp_path):
    return SqliteDb(db_file=str(tmp_path / "os.db"), id="os-db")


def read(tools, **kwargs):
    return json.loads(tools.read_context(**kwargs))


def test_reads_a_referenced_knowledge_item_and_caps_long_text(db):
    db.upsert_knowledge_content(KnowledgeRow(id="kc-1", name="pricing.pdf", description="x" * 2000))
    result = read(PlatformContextTools(db=db), kind="knowledge_content", id="kc-1")
    assert result["kind"] == "knowledge_content" and result["item"]["name"] == "pricing.pdf"
    assert len(result["item"]["description"]) < 600


def test_reports_unknown_kinds_missing_items_and_unknown_databases(db):
    tools = PlatformContextTools(db=db, get_dbs=lambda: {"os-db": [db]})
    assert "Unknown kind" in read(tools, kind="widget", id="1")["error"]
    assert read(tools, kind="trace", id="missing")["error"] == "trace missing not found"
    assert read(tools, kind="session", id="s-1", db_id="elsewhere")["error"] == "Database 'elsewhere' not found"
    # A reference naming the OS database resolves to it.
    db.upsert_knowledge_content(KnowledgeRow(id="kc-1", name="notes.md", description="Notes"))
    assert read(tools, kind="knowledge_content", id="kc-1", db_id="os-db")["item"]["name"] == "notes.md"


def test_each_kind_is_gated_by_its_read_scope(db, monkeypatch):
    checked = []

    def deny(resource, action, run_context=None):
        checked.append(f"{resource}:{action}")
        raise PermissionError(f"Permission required: {resource}:{action}")

    monkeypatch.setattr(platform_context, "require_permission", deny)
    tools = PlatformContextTools(db=db)
    for kind in platform_context.CONTEXT_KINDS:
        assert "Permission required" in read(tools, kind=kind, id="1")["error"]
    assert checked == ["sessions:read", "traces:read", "knowledge:read", "memories:read", "evals:read"]


@pytest.mark.asyncio
async def test_async_reads_work_on_a_sync_database(db):
    db.upsert_knowledge_content(KnowledgeRow(id="kc-2", name="faq.md", description="FAQ"))
    result = json.loads(await PlatformContextTools(db=db).aread_context(kind="knowledge_content", id="kc-2"))
    assert result["item"]["name"] == "faq.md"


class FakeAuthority:
    """Caller authority: admins pass agent_os:admin, everyone else is refused it."""

    def __init__(self, principal_id, admin=False):
        self.context = SimpleNamespace(principal_id=principal_id)
        self.admin = admin

    def require(self, resource, action, resource_id=None):
        if (resource, action) == ("agent_os", "admin") and not self.admin:
            raise PermissionError("Permission required: agent_os:admin")

    async def arequire(self, resource, action, resource_id=None):
        self.require(resource, action, resource_id)


@pytest.fixture
def owned_memory(db):
    db.upsert_user_memory(UserMemory(memory_id="m-1", memory="Prefers short answers", user_id="u2"))
    return "m-1"


@pytest.mark.parametrize(
    "authority, visible",
    [
        (FakeAuthority("u1"), False),  # another user
        (FakeAuthority("u2"), True),  # the owner
        (FakeAuthority("u1", admin=True), True),  # admins read everything
        (None, True),  # no caller authority: trusted Python use
    ],
)
@pytest.mark.parametrize("use_async", [False, True])
def test_reads_are_scoped_to_the_caller_like_the_routes(db, owned_memory, monkeypatch, authority, visible, use_async):
    monkeypatch.setattr(platform_context, "authorization_for", lambda run_context=None: authority)
    tools = PlatformContextTools(db=db)
    if use_async:
        result = json.loads(asyncio.run(tools.aread_context(kind="memory", id=owned_memory)))
    else:
        result = read(tools, kind="memory", id=owned_memory)
    if visible:
        assert result["item"]["memory"] == "Prefers short answers"
    else:
        assert result["error"] == "memory m-1 not found"


def test_a_non_admin_caller_without_identity_reads_nothing(db, owned_memory, monkeypatch):
    monkeypatch.setattr(platform_context, "authorization_for", lambda run_context=None: FakeAuthority(None))
    assert read(PlatformContextTools(db=db), kind="memory", id=owned_memory)["error"] == (
        "No caller identity to scope the read to"
    )


def test_scoped_callers_only_see_their_own_traces():
    trace = SimpleNamespace(user_id="u2")
    assert platform_context._owned(trace, None) is trace
    assert platform_context._owned(trace, "u2") is trace
    assert platform_context._owned(trace, "u1") is None
