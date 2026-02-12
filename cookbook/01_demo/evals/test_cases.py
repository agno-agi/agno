"""
Test cases for evaluating all demo agents.

Each test case targets a specific agent and checks for expected strings
in the response. Tests are organized by agent/component.
"""

from dataclasses import dataclass


@dataclass
class TestCase:
    """A test case for evaluating a demo component."""

    agent: str  # Agent/team/workflow ID
    question: str
    expected_strings: list[str]
    category: str
    match_mode: str = "all"  # "all" = all must match, "any" = at least one must match


# ---------------------------------------------------------------------------
# Agent Test Cases
# ---------------------------------------------------------------------------

DASH_TESTS: list[TestCase] = [
    TestCase(
        agent="dash",
        question="Who won the most races in 2019?",
        expected_strings=["Hamilton", "11"],
        category="dash_basic",
    ),
    TestCase(
        agent="dash",
        question="Which team won the 2020 constructors championship?",
        expected_strings=["Mercedes"],
        category="dash_basic",
    ),
    TestCase(
        agent="dash",
        question="Which driver has won the most world championships?",
        expected_strings=["Schumacher", "7"],
        category="dash_aggregation",
    ),
]

SCOUT_TESTS: list[TestCase] = [
    TestCase(
        agent="scout",
        question="What is our PTO policy?",
        expected_strings=["PTO", "days"],
        category="scout_knowledge",
        match_mode="all",
    ),
    TestCase(
        agent="scout",
        question="Find the deployment runbook",
        expected_strings=["deployment", "runbook"],
        category="scout_knowledge",
        match_mode="all",
    ),
    TestCase(
        agent="scout",
        question="What are the incident severity levels?",
        expected_strings=["severity"],
        category="scout_knowledge",
    ),
]

PAL_TESTS: list[TestCase] = [
    TestCase(
        agent="pal",
        question="Tell me about yourself",
        expected_strings=["Pal", "knowledge"],
        category="pal_identity",
        match_mode="any",
    ),
    TestCase(
        agent="pal",
        question="Note: We decided to use PostgreSQL for the new analytics service",
        expected_strings=["saved", "note", "PostgreSQL"],
        category="pal_capture",
        match_mode="any",
    ),
]

SEEK_TESTS: list[TestCase] = [
    TestCase(
        agent="seek",
        question="Tell me about yourself",
        expected_strings=["Seek", "research"],
        category="seek_identity",
        match_mode="any",
    ),
]

DEX_TESTS: list[TestCase] = [
    TestCase(
        agent="dex",
        question="Tell me about yourself",
        expected_strings=["Dex", "relationship", "people"],
        category="dex_identity",
        match_mode="any",
    ),
]

ACE_TESTS: list[TestCase] = [
    TestCase(
        agent="ace",
        question="Tell me about yourself",
        expected_strings=["Ace", "draft", "response"],
        category="ace_identity",
        match_mode="any",
    ),
    TestCase(
        agent="ace",
        question="Draft a reply to: 'Thanks for the demo. Can we discuss pricing next week?'",
        expected_strings=["pricing", "week", "meeting"],
        category="ace_drafting",
        match_mode="any",
    ),
]

# ---------------------------------------------------------------------------
# Team Test Cases
# ---------------------------------------------------------------------------

RESEARCH_TEAM_TESTS: list[TestCase] = [
    TestCase(
        agent="research-team",
        question="Research Anthropic - what do they do and who are the key people?",
        expected_strings=["Anthropic", "Claude"],
        category="research_team",
        match_mode="any",
    ),
]

SUPPORT_TEAM_TESTS: list[TestCase] = [
    TestCase(
        agent="support-team",
        question="What is our company's PTO policy?",
        expected_strings=["PTO"],
        category="support_team",
    ),
]

# ---------------------------------------------------------------------------
# Workflow Test Cases
# ---------------------------------------------------------------------------

DAILY_BRIEF_TESTS: list[TestCase] = [
    TestCase(
        agent="daily-brief",
        question="Generate my daily brief for today",
        expected_strings=["calendar", "email", "meeting"],
        category="daily_brief",
        match_mode="any",
    ),
]

MEETING_PREP_TESTS: list[TestCase] = [
    TestCase(
        agent="meeting-prep",
        question="Prepare me for my 10 AM Product Strategy Review meeting",
        expected_strings=["Product Strategy", "talking point"],
        category="meeting_prep",
        match_mode="any",
    ),
]

# ---------------------------------------------------------------------------
# All test cases combined
# ---------------------------------------------------------------------------

ALL_TEST_CASES: list[TestCase] = (
    DASH_TESTS
    + SCOUT_TESTS
    + PAL_TESTS
    + SEEK_TESTS
    + DEX_TESTS
    + ACE_TESTS
    + RESEARCH_TEAM_TESTS
    + SUPPORT_TEAM_TESTS
    + DAILY_BRIEF_TESTS
    + MEETING_PREP_TESTS
)

CATEGORIES = sorted(set(tc.category for tc in ALL_TEST_CASES))

# Agent-specific test collections for targeted evaluation
AGENT_TESTS: dict[str, list[TestCase]] = {
    "dash": DASH_TESTS,
    "scout": SCOUT_TESTS,
    "pal": PAL_TESTS,
    "seek": SEEK_TESTS,
    "dex": DEX_TESTS,
    "ace": ACE_TESTS,
    "research-team": RESEARCH_TEAM_TESTS,
    "support-team": SUPPORT_TEAM_TESTS,
    "daily-brief": DAILY_BRIEF_TESTS,
    "meeting-prep": MEETING_PREP_TESTS,
}
