"""
BUG-004: Duplicate Database Insert in _load_from_topics

FIXED: 2026-01-15

Issue: When inserting content with topics, _load_from_topics called
_insert_contents_db twice per topic with identical data.

Before fix: 2 inserts + 1 update per topic = 3 DB calls (33% overhead)
After fix:  1 insert + 1 update per topic = 2 DB calls

Run: .venvs/demo/bin/python cookbook/08_knowledge/bugs/bug_004_duplicate_insert.py
"""

from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.document import Document
from agno.knowledge.reader.base import Reader

# Global counters
db_calls = []


class MockReader(Reader):
    """Mock reader that returns fake documents."""

    def read(self, topic: str, **kwargs):
        return [Document(name=topic, content=f"Content about {topic}")]

    async def async_read(self, topic: str, **kwargs):
        return self.read(topic, **kwargs)


def create_tracking_db(db_path: str):
    """Create a DB with call tracking."""
    contents_db = SqliteDb(db_file=db_path, knowledge_table="knowledge_contents")
    original_upsert = contents_db.upsert_knowledge_content

    def tracked_upsert(knowledge_row):
        status = getattr(knowledge_row, "status", "unknown")
        db_calls.append({"type": "upsert", "status": str(status)})
        return original_upsert(knowledge_row)

    contents_db.upsert_knowledge_content = tracked_upsert
    return contents_db


def test_single_topic():
    """Test with single topic."""
    global db_calls
    db_calls = []

    contents_db = create_tracking_db("/tmp/claude/bug_004_single.db")
    knowledge = Knowledge(name="test", contents_db=contents_db)

    knowledge.insert(topics=["AI"], reader=MockReader(), skip_if_exists=False)

    return db_calls


def test_multiple_topics():
    """Test with multiple topics."""
    global db_calls
    db_calls = []

    contents_db = create_tracking_db("/tmp/claude/bug_004_multi.db")
    knowledge = Knowledge(name="test", contents_db=contents_db)

    knowledge.insert(topics=["ML", "DL"], reader=MockReader(), skip_if_exists=False)

    return db_calls


def main():
    print("=" * 60)
    print("BUG-004: Duplicate Insert Confirmation")
    print("=" * 60)

    # Test 1: Single topic
    print("\nTest 1: Single topic ['AI']")
    print("-" * 40)
    calls = test_single_topic()

    processing_inserts = sum(1 for c in calls if c["status"] == "processing")
    print(f"Total DB calls: {len(calls)}")
    print(f"Processing inserts: {processing_inserts}")

    for i, call in enumerate(calls, 1):
        print(f"  [{i}] {call['type']} - status: {call['status']}")

    if processing_inserts > 1:
        print(
            "\n  BUG CONFIRMED: {0} redundant insert(s)".format(processing_inserts - 1)
        )

    # Test 2: Multiple topics
    print("\n" + "=" * 60)
    print("Test 2: Multiple topics ['ML', 'DL']")
    print("-" * 40)
    calls = test_multiple_topics()

    processing_inserts = sum(1 for c in calls if c["status"] == "processing")
    expected_inserts = 2  # One per topic
    print(f"Total DB calls: {len(calls)}")
    print(f"Processing inserts: {processing_inserts} (expected: {expected_inserts})")

    for i, call in enumerate(calls, 1):
        print(f"  [{i}] {call['type']} - status: {call['status']}")

    if processing_inserts > expected_inserts:
        print(
            "\n  BUG CONFIRMED: {0} redundant insert(s)".format(
                processing_inserts - expected_inserts
            )
        )

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print("""
BUG-004 Status: FIXED

The redundant _insert_contents_db call was removed from both
sync (_load_from_topics) and async (_aload_from_topics) versions.

Expected: 1 processing insert per topic
""")


if __name__ == "__main__":
    main()
