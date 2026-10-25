"""AgentOS File System - Config Coverage
=====================================

A seeded app for inspecting /config and exercising the File System UI. Covers
the supported filesystem attachment forms, shared stores, access levels,
backend metadata, quotas, empty stores, and namespace resolution.

Run: .venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/multiple_type_filesystem.py
Open: http://localhost:7777/config, or connect Agno OS to http://localhost:7777

Optional environment:
  FILESYSTEM_CONFIG_MODE=empty     Only agents without filesystems.
  JWT_VERIFICATION_KEY             Enable HS256 auth and managed user isolation.
  FILESYSTEM_POSTGRES_URL          Add a PostgreSQL store with a custom schema.

For JWT requests, use sub=alice or sub=bob, aud=filesystem-config-os, a short
expiry, and scopes=["config:read", "agents:read"]. No model call is needed to
browse files; OPENAI_API_KEY is needed only when running an agent.
See README.md for expected config shapes and requests to try.
"""

from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.fs import FileSystem
from agno.fs.db import DbFileSystem
from agno.fs.local import LocalFileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

mode = getenv("FILESYSTEM_CONFIG_MODE", "all")
if mode not in {"all", "empty"}:
    raise ValueError("FILESYSTEM_CONFIG_MODE must be 'all' or 'empty'")

db = SqliteDb(id="filesystem-db", db_file="tmp/multiple_type_filesystem/main.db")
archive_db = SqliteDb(
    id="archive-db", db_file="tmp/multiple_type_filesystem/archive.db"
)
model = OpenAIResponses(id="gpt-5.6-luna")

drafts = FileSystem(db, namespace="analyst/drafts")
handbook = FileSystem(db, namespace="team/handbook")
records = FileSystem(db, namespace="team/records")
limited = FileSystem(
    db, namespace="limited", max_file_bytes=1_024, max_namespace_bytes=4_096
)
empty = FileSystem(db, namespace="agents/{agent_id}/empty")
personal = FileSystem(db, namespace="users/{user_id}/{agent_id}")
local = FileSystem(
    LocalFileSystem(root="tmp/multiple_type_filesystem/local"),
    namespace="Team/Local Notes",
)

# A namespace is not a globally unique store ID: its backend also matters.
archived_drafts = FileSystem(archive_db, namespace="analyst/drafts")
alternate_table = FileSystem(
    DbFileSystem(db=db, table_name="alternate_fs"), namespace="analyst/drafts"
)
standalone = FileSystem(
    DbFileSystem(db_url="sqlite:///tmp/multiple_type_filesystem/standalone.db")
)

# Read-only views of shared stores: same backend and namespace, so the same
# files, but agents holding these get only the read tools.
handbook_read_only = FileSystem(db, namespace="team/handbook", read_only=True)
records_read_only = FileSystem(db, namespace="team/records", read_only=True)
drafts_read_only = FileSystem(db, namespace="analyst/drafts", read_only=True)

# Different quota configurations produce separate config instances even when
# the underlying files are shared. These are limits, not separate storage.
limited_drafts = FileSystem(
    db, namespace="analyst/drafts", max_file_bytes=2_048, max_namespace_bytes=8_192
)

# Mixed list: the example from the filesystem config, with per-store access.
analyst = Agent(
    id="analyst",
    name="Analyst",
    model=model,
    filesystem=[drafts, handbook_read_only],
)
editor = Agent(id="editor", name="Handbook Editor", model=model, filesystem=handbook)
reviewer = Agent(
    id="reviewer",
    name="Handbook Reviewer",
    model=model,
    filesystem=handbook_read_only,
)

# Homogeneous lists: all stores writable, or all stores read-only.
writer = Agent(id="writer", name="Writer", model=model, filesystem=[drafts, limited])
auditor = Agent(
    id="auditor",
    name="Auditor",
    model=model,
    filesystem=[handbook_read_only, records_read_only],
)
single_list = Agent(
    id="single-list", name="Empty Store", model=model, filesystem=[empty]
)
managed = Agent(id="managed", name="Managed Store", model=model, filesystem=True)
local_agent = Agent(id="local", name="Local Store", model=model, filesystem=local)
archive_agent = Agent(
    id="archive", name="Other Database", model=model, filesystem=archived_drafts
)
table_agent = Agent(
    id="alternate-table", name="Other Table", model=model, filesystem=alternate_table
)
standalone_agent = Agent(
    id="standalone", name="DB Without Agno DB ID", model=model, filesystem=standalone
)
personal_agent = Agent(
    id="personal", name="User-Isolated Store", model=model, filesystem=personal
)
quota_agent = Agent(
    id="limited-drafts",
    name="Shared Store, Smaller Quotas",
    model=model,
    filesystem=limited_drafts,
)

# Manual tool attachment remains discoverable without a filesystem setting.
manual = Agent(
    id="manual",
    name="Manual Toolkit",
    model=model,
    tools=[handbook.tools(read_only=True)],
)

# Duplicate attachments merge into one agent entry per store. Full access wins
# over read-only, regardless of attachment order (one order per namespace).
duplicate = Agent(
    id="duplicate",
    name="Duplicate Attachments",
    model=model,
    filesystem=[handbook_read_only, handbook, drafts, drafts_read_only],
)

disabled_none = Agent(
    id="disabled-none", name="No Filesystem", model=model, filesystem=None
)
disabled_false = Agent(
    id="disabled-false", name="Disabled Filesystem", model=model, filesystem=False
)
disabled_list = Agent(
    id="disabled-list", name="Empty Filesystem List", model=model, filesystem=[]
)
disabled_agents = [disabled_none, disabled_false, disabled_list]
agents = [
    analyst,
    editor,
    reviewer,
    writer,
    auditor,
    single_list,
    managed,
    local_agent,
    archive_agent,
    table_agent,
    standalone_agent,
    personal_agent,
    quota_agent,
    manual,
    duplicate,
    *disabled_agents,
]

# Seed duplicate paths, nested directories, and several preview types. Keeping
# seeds separate from agents lets read-only consumers start with useful files.
seed_files = [
    (drafts, "q3-review.md", "# Q3 review\n\nDraft in progress.\n"),
    (drafts, "reports/summary.md", "# Summary\n\nRevenue grew by 12%.\n"),
    (drafts, "reports/data.json", '{"quarter": "Q3", "growth": 12}\n'),
    (
        drafts,
        "preview.html",
        "<!doctype html><html><body><h1>Q3 review</h1><p>Growth: 12%</p></body></html>",
    ),
    (handbook, "style.md", "Lead with the conclusion. Cite every number.\n"),
    (
        records,
        "decisions.md",
        "# Decisions\n\nThis store has only a read-only consumer.\n",
    ),
    (limited, "note.txt", "A store with smaller file and namespace limits.\n"),
    (local, "local.md", "# Local file\n\nStored on disk.\n"),
    (
        archived_drafts,
        "q3-review.md",
        "# Archived Q3 review\n\nStored in archive-db.\n",
    ),
    (
        alternate_table,
        "q3-review.md",
        "# Alternate Q3 review\n\nStored in alternate_fs.\n",
    ),
    (standalone, "standalone.md", "# Standalone DB\n\nNo Agno database ID.\n"),
    (
        personal.resolve(user_id="alice", agent_id="personal"),
        "notes.md",
        "Alice's private notes.\n",
    ),
    (
        personal.resolve(user_id="bob", agent_id="personal"),
        "notes.md",
        "Bob's private notes.\n",
    ),
]

# PostgreSQL is optional so the default coverage app needs no external service.
postgres_url = getenv("FILESYSTEM_POSTGRES_URL")
if postgres_url and mode == "all":
    from agno.db.postgres import PostgresDb

    postgres_db = PostgresDb(id="postgres-filesystem-db", db_url=postgres_url)
    postgres_files = FileSystem(
        DbFileSystem(
            db=postgres_db, table_name="config_files", db_schema="filesystem_demo"
        ),
        namespace="postgres/research",
    )
    postgres_agent = Agent(
        id="postgres", name="PostgreSQL Store", model=model, filesystem=postgres_files
    )
    agents.append(postgres_agent)
    seed_files.append(
        (
            postgres_files,
            "research.md",
            "# Research\n\nStored in a custom PostgreSQL schema.\n",
        )
    )

verification_key = getenv("JWT_VERIFICATION_KEY")
authorization_config = None
if verification_key:
    authorization_config = AuthorizationConfig(
        verification_keys=[verification_key],
        algorithm="HS256",
        verify_audience=True,
        user_isolation=True,
    )

agent_os = AgentOS(
    id="filesystem-config-os",
    name="Filesystem Config Coverage",
    db=db,
    agents=disabled_agents if mode == "empty" else agents,
    authorization=bool(verification_key),
    authorization_config=authorization_config,
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()

if __name__ == "__main__":
    if mode == "all":
        managed_files = managed.filesystem_instance
        if managed_files is not None:
            if verification_key:
                seed_files.extend(
                    [
                        (
                            managed_files.resolve(user_id="alice", agent_id="managed"),
                            "notes.md",
                            "Alice's managed notes.\n",
                        ),
                        (
                            managed_files.resolve(user_id="bob", agent_id="managed"),
                            "notes.md",
                            "Bob's managed notes.\n",
                        ),
                    ]
                )
            else:
                seed_files.append(
                    (managed_files, "notes.md", "Shared managed notes.\n")
                )

        # Re-running the cookbook preserves edits made during manual testing.
        # The single-list agent's namespace intentionally starts empty.
        for filesystem, path, content in seed_files:
            if filesystem.read(path) is None:
                filesystem.write(path, content)

    agent_os.serve(app=app, host="127.0.0.1", port=7777)
