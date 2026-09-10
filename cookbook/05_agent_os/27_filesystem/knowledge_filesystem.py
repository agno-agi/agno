"""Read-only Knowledge pages with automatic tools and AgentOS registration.

Use an existing PostgreSQL database with pgvector; see README.md for setup.
Sync is explicit because it fetches documents and makes embedding calls.
"""

import argparse
from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.page import PageFileSystem
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

db = PostgresDb(
    id="filesystem-knowledge-db",
    db_url=getenv(
        "FILESYSTEM_KNOWLEDGE_DB_URL",
        "postgresql+psycopg://ai:ai@localhost:5532/filesystem_knowledge",
    ),
)

# Preserve the earlier cookbook's corpus and vector table. For a new corpus,
# only db and namespace are required; name and table_name have defaults.
pages = PageFileSystem(
    db=db,
    namespace="reference-docs",
    name="Reference documentation",
    table_name="reference_page_vectors",
)

agent = Agent(
    id="docs-assistant",
    name="Docs Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=pages,
    markdown=True,
)

agent_os = AgentOS(
    id="filesystem-knowledge-os",
    db=db,
    agents=[agent],
    cors_allowed_origins=["http://localhost:3000"],
)
app = agent_os.get_app()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", nargs="?", default="serve", choices=["sync", "serve", "chat"]
    )
    parser.add_argument("--url", help="Public HTTPS llms.txt index to sync")
    parser.add_argument(
        "--message",
        default="Explore the reference docs and explain one useful concept. Cite the documentation paths you read.",
    )
    args = parser.parse_args()
    if args.mode == "sync":
        if not args.url:
            parser.error(
                "sync requires --url pointing to a public HTTPS llms.txt index"
            )
        pages.setup()
        report = pages.sync_pages(url=args.url)
        print(report.model_dump_json(indent=2))
        if report.status == "partial":
            raise SystemExit(1)
    elif args.mode == "chat":
        pages.setup()
        agent.print_response(args.message, stream=True)
    else:
        agent_os.serve(app=app, host="127.0.0.1", port=7777)
