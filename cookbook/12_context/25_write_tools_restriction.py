"""
Restricting Write Operations with write_tools
==============================================

Context providers expose ``write_tools`` to customize or restrict what
write operations an agent can perform. This is useful for:

- Safety: Prevent agents from deleting data
- Compliance: Limit agents to draft-only (human reviews before sending)
- Scoping: Restrict agents to specific operations

This example demonstrates:
1. Gmail: Draft-only mode (no sending)
2. Calendar: Create-only mode (no updates or deletes)
3. Database: Insert-only mode (no updates or deletes)

The ``write_tools`` parameter accepts a list of tools that replace the
default write toolkit. Pass a pre-configured toolkit with specific
operations disabled, or pass completely custom tools.

Requires: OPENAI_API_KEY + provider-specific credentials (see individual
provider cookbooks: 18_gmail.py, 19_calendar.py, 04_database_read_write.py)
"""

from __future__ import annotations

import asyncio

from agno.agent import Agent
from agno.context.calendar import GoogleCalendarContextProvider
from agno.context.database import DatabaseContextProvider
from agno.context.gmail import GmailContextProvider
from agno.models.openai import OpenAIResponses
from agno.tools.google.calendar import GoogleCalendarTools
from agno.tools.google.gmail import GmailTools
from agno.tools.postgres import PostgresTools

# ---------------------------------------------------------------------------
# Example 1: Gmail - Draft Only (No Sending)
# ---------------------------------------------------------------------------
# Agents can create and manage drafts but cannot send emails.
# A human reviews drafts before manually sending.


async def demo_gmail_draft_only():
    print("\n" + "=" * 60)
    print("DEMO 1: Gmail Draft-Only Mode")
    print("=" * 60)

    draft_only_tools = GmailTools(
        send_email=False,
        send_email_reply=False,
        create_draft_email=True,
        get_draft=True,
        list_drafts=True,
        search_emails=True,
        get_thread=True,
    )

    gmail = GmailContextProvider(
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=True,
        write_tools=[draft_only_tools],
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=gmail.get_tools(),
        instructions=gmail.instructions(),
        markdown=True,
    )

    print(f"\nProvider status: {gmail.status()}")
    print("\n--- Agent can draft but NOT send ---\n")

    await agent.aprint_response(
        "Find recent emails about meetings. Draft a polite follow-up "
        "asking for an update on any action items. Save as draft only.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Example 2: Calendar - Create Only (No Deletes)
# ---------------------------------------------------------------------------
# Agents can create events but cannot update or delete existing ones.
# Prevents accidental deletion of important meetings.


async def demo_calendar_create_only():
    print("\n" + "=" * 60)
    print("DEMO 2: Calendar Create-Only Mode")
    print("=" * 60)

    create_only_tools = GoogleCalendarTools(
        create_event=True,
        update_event=False,
        delete_event=False,
        search_events=True,
        get_event=True,
        list_calendars=True,
    )

    calendar = GoogleCalendarContextProvider(
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=True,
        write_tools=[create_only_tools],
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=calendar.get_tools(),
        instructions=calendar.instructions(),
        markdown=True,
    )

    print(f"\nProvider status: {calendar.status()}")
    print("\n--- Agent can create but NOT delete events ---\n")

    await agent.aprint_response(
        "Check my calendar for next week. If there's no 1:1 meeting "
        "scheduled, create a 30-minute placeholder on Tuesday at 2pm.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Example 3: Database - Insert Only (No Updates/Deletes)
# ---------------------------------------------------------------------------
# Agents can insert new records but cannot modify or delete existing ones.
# Useful for audit logs, append-only data patterns.


async def demo_database_insert_only():
    print("\n" + "=" * 60)
    print("DEMO 3: Database Insert-Only Mode")
    print("=" * 60)

    insert_only_tools = PostgresTools(
        db_url="postgresql://user:pass@localhost:5432/mydb",
        enable_run_query=True,
        enable_insert_row=True,
        enable_update_row=False,
        enable_delete_row=False,
        enable_list_tables=True,
        enable_describe_table=True,
    )

    database = DatabaseContextProvider(
        db_url="postgresql://user:pass@localhost:5432/mydb",
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=True,
        write_tools=[insert_only_tools],
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=database.get_tools(),
        instructions=database.instructions(),
        markdown=True,
    )

    print(f"\nProvider status: {database.status()}")
    print("\n--- Agent can insert but NOT update/delete ---\n")

    await agent.aprint_response(
        "Add a new entry to the audit_log table recording that "
        "the daily report was generated at the current timestamp.",
        stream=True,
    )


# ---------------------------------------------------------------------------
# Example 4: Using query_timeout for Safety
# ---------------------------------------------------------------------------
# Combine write_tools with query_timeout to add time bounds.


async def demo_with_timeout():
    print("\n" + "=" * 60)
    print("DEMO 4: Restricted Tools + Timeout")
    print("=" * 60)

    draft_only_tools = GmailTools(
        send_email=False,
        send_email_reply=False,
        create_draft_email=True,
    )

    gmail = GmailContextProvider(
        model=OpenAIResponses(id="gpt-5.4-mini"),
        read=True,
        write=True,
        write_tools=[draft_only_tools],
        query_timeout=30.0,
    )

    print("\n--- Draft-only + 30s timeout ---\n")
    print("Gmail provider configured with:")
    print("  - write_tools: draft-only (no send)")
    print("  - query_timeout: 30s")
    print("  - Tools available:", [t.name for t in gmail.get_tools()])


# ---------------------------------------------------------------------------
# Run Demos
# ---------------------------------------------------------------------------


async def main():
    print("NOTE: These demos require provider credentials to be configured.")
    print("See individual provider cookbooks for setup instructions.")
    print("\nRunning demo_with_timeout (no credentials needed for setup check)...")
    await demo_with_timeout()


if __name__ == "__main__":
    asyncio.run(main())
