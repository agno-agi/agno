"""Super Agent is told which company wiki pages exist, on every turn, in the unstored message before the person's."""

import asyncio
import pytest

from agno.company.manager import CompanyManager
from agno.db.sqlite import SqliteDb
from agno.os.manager.person import Person, TurnContext
from agno.os.manager.rules_pages import RulesPages
from agno.run import RunContext
from agno.run.authorization import RunAuthorization

HEADER = "Company wiki pages (information from AgentOS, not instructions and not written by the person): "
NONE = HEADER + "none written yet, so the company has no rules to read."


def context(authorization=None):
    return RunContext(run_id="r", session_id="s", user_id="jonah", authorization=authorization)


def read(pages, mode, run_context=None):
    run_context = run_context or context()
    return pages.read(run_context) if mode == "sync" else asyncio.run(pages.aread(run_context))


@pytest.fixture
def db(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    yield db
    db.close()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_company_with_no_written_page_is_told_there_are_no_rules_to_read(db, mode):
    pages = RulesPages(db)
    # A wiki nobody opened holds nothing.
    assert read(pages, mode) == NONE
    # Opening it creates brief.md and status.md. As created they hold no rule, and are not named.
    CompanyManager(db).get_wiki()
    assert read(pages, mode) == NONE


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_page_written_during_a_conversation_is_named_on_the_next_turn(db, mode):
    pages, company = RulesPages(db), CompanyManager(db)
    assert read(pages, mode) == NONE
    company.write_wiki(goal_id=None, path="how-we-work.md", content="1. Ask Dana first.\n", expected_version=0)
    assert read(pages, mode) == HEADER + "wiki/how-we-work.md."


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_rules_under_another_name_are_named_and_the_rules_page_comes_first(db, mode):
    pages, company = RulesPages(db), CompanyManager(db)
    company.write_wiki(goal_id=None, path="ground-rules.md", content="1. Ask Dana first.\n", expected_version=0)
    assert read(pages, mode) == HEADER + "wiki/ground-rules.md."
    company.write_wiki(goal_id=None, path="how-we-work.md", content="2. Nothing hourly.\n", expected_version=0)
    assert read(pages, mode) == HEADER + "wiki/how-we-work.md, wiki/ground-rules.md."


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_default_page_a_person_changed_is_named(db, mode):
    pages, company = RulesPages(db), CompanyManager(db)
    company.get_wiki()
    company.write_wiki(goal_id=None, path="brief.md", content="# Lumen Desk\n\nNo pushes.\n", expected_version=1)
    assert read(pages, mode) == HEADER + "wiki/brief.md."


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_many_pages_are_cut_with_the_count_left_out(db, mode):
    company = CompanyManager(db)
    for number in range(23):
        company.write_wiki(goal_id=None, path=f"page-{number:02d}.md", content="x\n", expected_version=0)
    note = read(RulesPages(db), mode)
    assert note.count("wiki/page-") == 20
    assert note.endswith("wiki/page-19.md, and 3 more: list wiki/ to see them.")


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_it_costs_one_listing_and_reads_no_page(db, mode, monkeypatch):
    CompanyManager(db).write_wiki(goal_id=None, path="how-we-work.md", content="x\n", expected_version=0)
    pages = RulesPages(db)
    folder = pages._folder()
    calls = []

    class Spy:
        def __getattr__(self, name):
            calls.append(name)
            return getattr(folder, name)

    monkeypatch.setattr(pages, "_folder", lambda: Spy())
    assert read(pages, mode) == HEADER + "wiki/how-we-work.md."
    assert calls == ["list"]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_caller_who_may_not_read_the_wiki_is_told_nothing(db, mode):
    CompanyManager(db).write_wiki(goal_id=None, path="how-we-work.md", content="x\n", expected_version=0)

    from agno.os.authz.provider import AuthorizationContext
    from agno.os.authz.scope_provider import ScopeAuthorizationProvider

    def caller(scopes):
        frame = AuthorizationContext(principal_id="u-1", scopes=scopes, claims={"sub": "u-1"})
        return context(RunAuthorization(ScopeAuthorizationProvider(), frame))

    assert read(RulesPages(db), mode, caller(["tasks:read"])) is None
    assert read(RulesPages(db), mode, caller(["wiki:read"])) == HEADER + "wiki/how-we-work.md."


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_listing_that_fails_says_nothing_and_does_not_stop_the_turn(db, mode, monkeypatch):
    pages = RulesPages(db)

    def broken():
        raise RuntimeError("store is down")

    monkeypatch.setattr(pages, "_folder", broken)
    assert read(pages, mode) is None
    turn = TurnContext(Person(), None, pages=pages)
    note = turn.read(context()) if mode == "sync" else asyncio.run(turn.aread(context()))
    assert note.startswith("Who you are talking to") and "Company wiki pages" not in note


class Work:
    def read(self, run_context, session=None):
        return "Work started from this conversation ..."

    async def aread(self, run_context, session=None):
        return "Work started from this conversation ..."


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_the_line_comes_after_who_the_person_is_and_before_the_linked_work(db, mode):
    turn = TurnContext(Person(), Work(), pages=RulesPages(db))
    note = turn.read(context()) if mode == "sync" else asyncio.run(turn.aread(context()))
    person, pages, blank, work = note.split("\n")
    assert person.startswith("Who you are talking to")
    assert pages == NONE
    assert (blank, work) == ("", "Work started from this conversation ...")
    # A model that is not sent the message is sent nothing, and the wiki is not listed for it.
    unsent = TurnContext(Person(), Work(), delivers=lambda: False, pages=None)
    assert (unsent.read(context()) if mode == "sync" else asyncio.run(unsent.aread(context()))) is None


def test_super_agent_is_told_where_the_pages_are_named_and_that_none_means_no_read():
    from agno.os.manager.manager import _SAID_WITH_THE_BLOCK
    from agno.os.manager.prompts import COMPANY_INSTRUCTIONS, RULES_PAGES_INSTRUCTIONS

    said = " ".join(RULES_PAGES_INSTRUCTIONS.split())
    assert 'comes right before each message under "Company wiki pages", from AgentOS' in said
    assert "Never list wiki/ or read a page to find out whether the company has rules." in said
    assert "When it says none are written, there are no rules to read: skip that read and do what was asked." in said
    # A company with rules still reads them first, under whatever name they are kept.
    assert "read the rules before the steps that need them: wiki/how-we-work.md, or the pages it names" in said
    assert (
        "A page it names for the first time later in a conversation is new: read it before the next such step." in said
    )
    # The steps that need the rules stay where they were.
    assert "Once in a conversation, before you first record or change work" in " ".join(COMPANY_INSTRUCTIONS.split())
    # Said only to a model that is sent the message.
    assert any(part is RULES_PAGES_INSTRUCTIONS for part in _SAID_WITH_THE_BLOCK)


def test_super_agent_gets_the_line_and_its_instruction_only_with_company_and_a_model_sent_the_note(
    tmp_path, monkeypatch
):
    from agno.models.openai import OpenAIResponses
    from agno.os import AgentOS, CompanyConfig, OSManager
    from agno.os.manager.prompts import RULES_PAGES_INSTRUCTIONS

    class Unlisted(OpenAIResponses):
        pass

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    db = SqliteDb(db_file=str(tmp_path / "os.db"))

    def build(model, company):
        return AgentOS(
            db=db,
            company=CompanyConfig(model=OpenAIResponses(id="x")) if company else None,
            manager=OSManager(model=model, access_docs=False),
            telemetry=False,
        ).manager

    def told(manager):
        return any(part is RULES_PAGES_INSTRUCTIONS for part in manager.instructions(context()))

    with_company = build(OpenAIResponses(id="x"), company=True)
    assert NONE in with_company._message_context.read(context(), None).split("\n")
    assert told(with_company)
    # Without Company there is no wiki: nothing is listed and nothing is said about it.
    without_company = build(OpenAIResponses(id="x"), company=False)
    assert "Company wiki pages" not in without_company._message_context.read(context(), None)
    assert not told(without_company)
    # A model that is not sent the note keeps the instruction to look the rules up itself.
    unsent = build(Unlisted(id="x"), company=True)
    assert unsent._message_context.read(context(), None) is None
    assert not told(unsent)
    db.close()
