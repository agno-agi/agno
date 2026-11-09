"""Opt in to a weekly review by the framework Company Manager.

Check configuration without model calls:
    .venv/bin/python cookbook/05_agent_os/30_company/10_weekly_product_review.py --check

Serve locally and enable Monday reviews at 09:00 Europe/London:
    .venv/bin/python cookbook/05_agent_os/30_company/10_weekly_product_review.py --enable-weekly-review

Add --with-os-manager to also serve OS Manager; Company Manager still runs the
review, since OS Manager cannot execute Routines. Running scheduled reviews
requires provider credentials and makes model calls. This local example has no
authentication; use the authenticated Routine API for production caller grants.
"""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from agno.company import Product, Routine, Source
from agno.company.bootstrap import rehydrate_product
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, CompanyConfig, OSManager

# ---------------------------------------------------------------------------
# Review instructions
# ---------------------------------------------------------------------------
REVIEW = """Review this Product without accepting or executing work.
Read the company and Product playbooks and current status. List existing Projects
and Tasks before proposing anything. Inspect configured Sources with
read_product_source, first discovering paths and then reading useful evidence.
Propose work only when it addresses a concrete gap that existing work does not
cover. Reuse a suitable Project; propose one only when necessary.
Use intake_product_source with the Project id, observed evidence links and
content hashes, and a stable proposal_key for the underlying issue. Reuse the
key on later reviews. Never use propose_company_task during a Routine.
If nothing useful has changed, create no Tasks. Read status.md and use its current
version to update a concise status with evidence, proposed work and open questions.
Leave every Task in Backlog. Do not accept Tasks, complete Projects, or edit
schedules. Automatic acceptance is disabled."""


# ---------------------------------------------------------------------------
# AgentOS configuration
# ---------------------------------------------------------------------------
def build_os(
    db_file: str,
    source: Path,
    *,
    enable_weekly_review: bool = False,
    with_os_manager: bool = False,
) -> AgentOS:
    product = Product(
        id="documentation",
        name="Documentation",
        purpose="Keep the documentation accurate and useful.",
        sources=[Source(type="markdown", reference=str(source.resolve()))],
        routines=[
            Routine(
                name="weekly-review",
                executor_type="agent",
                executor_id="company-manager-internal",
                cron_expr="0 9 * * 1",
                timezone="Europe/London",
                instructions=REVIEW,
                auto_accept=False,
            )
        ]
        if enable_weekly_review
        else [],
    )
    model = OpenAIResponses(id="gpt-5.6-luna")
    return AgentOS(
        db=SqliteDb(db_file=db_file),
        company=CompanyConfig(model=model, products=[product]),
        manager=OSManager(model=model, access_docs=False) if with_os_manager else None,
        telemetry=False,
    )


# ---------------------------------------------------------------------------
# Run or check
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable-weekly-review", action="store_true")
    parser.add_argument("--with-os-manager", action="store_true")
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).with_name("README.md")
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with TemporaryDirectory() as directory:
            agent_os = build_os(
                directory + "/company.db",
                args.source,
                enable_weekly_review=True,
                with_os_manager=args.with_os_manager,
            )
            product = agent_os.company.products[0]
            rehydrate_product(
                agent_os.db, product, agent_os.registry, agent_os=agent_os
            )
            schedule = agent_os.db.get_schedule_by_name("documentation.weekly-review")
            assert schedule["endpoint"] == "/agents/company-manager-internal/runs"
            assert schedule["payload"]["metadata"]["auto_accept"] is False
            assert agent_os.registry.get_agent("company-manager-internal") is None
            print("Weekly Company Manager review configured; no model calls made.")
            agent_os.db.close()
    else:
        agent_os = build_os(
            "tmp/weekly-product-review.db",
            args.source,
            enable_weekly_review=args.enable_weekly_review,
            with_os_manager=args.with_os_manager,
        )
        agent_os.serve(app=agent_os.get_app(), host="127.0.0.1", reload=False)
