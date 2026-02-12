"""
End-to-end test for all 4 media storage backends with PostgreSQL.

Tests LocalMediaStorage (sync), AsyncLocalMediaStorage (async),
S3MediaStorage (sync), and AsyncS3MediaStorage (async) -- each performing
a 2-turn conversation to verify offloading, persistence, history loading,
and URL refresh.

Requirements:
    - PostgreSQL running (./cookbook/scripts/run_pgvector.sh)
    - pip install 'agno[media-storage-s3]' (for S3 tests)
    - greenlet package (for async tests)

S3 tests are skipped if AWS_ACCESS_KEY_ID is not set (credentials are optional).
All other missing dependencies will fail loudly.

Usage:
    .venvs/demo/bin/python cookbook/06_storage/05_media_storage_test_all.py
"""

import asyncio
import os
import uuid

import httpx
from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.media import Image
from agno.media_storage.async_s3 import AsyncS3MediaStorage
from agno.media_storage.local import AsyncLocalMediaStorage, LocalMediaStorage
from agno.media_storage.s3 import S3MediaStorage
from agno.models.openai import OpenAIChat
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TEST_IMAGE_URL = "https://picsum.photos/seed/agno-test/800/600"
SYNC_DB_URL = "postgresql+psycopg://ai:ai@localhost:5432/ai"
ASYNC_DB_URL = "postgresql+psycopg_async://ai:ai@localhost:5432/ai"
SESSION_TABLE = "media_storage_test_sessions"
LOCAL_STORAGE_PATH = "./tmp/media_storage_test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def print_separator(title: str) -> None:
    print("\n" + "=" * 70)
    print("  %s" % title)
    print("=" * 70)


def _extract_content_preview(msg) -> str:
    """Extract a short content preview from a Message."""
    if isinstance(msg.content, str):
        return msg.content[:80]
    if isinstance(msg.content, list) and msg.content:
        first = msg.content[0]
        if isinstance(first, str):
            return first[:80]
        if isinstance(first, dict) and "text" in first:
            return str(first["text"])[:80]
    return ""


def print_media_info(messages, label: str = "RunOutput.messages") -> None:
    """Print media_reference details for each message."""
    print("-" * 50)
    print("  Media Info: %s" % label)
    print("-" * 50)
    for idx, msg in enumerate(messages or []):
        content_preview = _extract_content_preview(msg)
        print(
            "  Message %d | role=%-10s | from_history=%-5s | content_preview=%s"
            % (idx, msg.role, msg.from_history, content_preview)
        )

        if msg.images:
            for img_idx, img in enumerate(msg.images):
                if img.media_reference:
                    ref = img.media_reference
                    print("    Image %d:" % img_idx)
                    print("      storage_key    : %s" % ref.storage_key)
                    print("      storage_backend: %s" % ref.storage_backend)
                    print("      url            : %s" % ref.url)
                    print("      size           : %s bytes" % ref.size)
                    print("      content_hash   : %s" % ref.content_hash)
                else:
                    print("    Image %d: (no media_reference)" % img_idx)
    print()


def print_chat_history(messages) -> None:
    """Print chat history messages from DB."""
    print("-" * 50)
    print("  Chat History from DB (via get_chat_history)")
    print("-" * 50)
    for idx, msg in enumerate(messages or []):
        has_images = bool(msg.images)
        has_media_ref = False
        media_url = None
        if msg.images:
            for img in msg.images:
                if img.media_reference:
                    has_media_ref = True
                    media_url = img.media_reference.url
                    break

        content_str = _extract_content_preview(msg)

        print(
            "  [%d] role=%-10s | has_images=%-5s | has_media_ref=%s"
            % (idx, msg.role, has_images, has_media_ref)
        )
        if media_url:
            print("      media_ref.url = %s" % media_url)
        if content_str:
            print("      content       = %s" % content_str)
    print()


# ---------------------------------------------------------------------------
# Test 1: LocalMediaStorage (sync)
# ---------------------------------------------------------------------------
def test_local_sync(image_bytes: bytes) -> None:
    session_id = "test_local_sync_%s" % uuid.uuid4().hex[:8]
    print_separator("TEST 1: LocalMediaStorage (sync)")
    print("  session_id: %s" % session_id)

    storage = LocalMediaStorage(base_path=LOCAL_STORAGE_PATH)
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        media_storage=storage,
        db=PostgresDb(db_url=SYNC_DB_URL, session_table=SESSION_TABLE),
        session_id=session_id,
        add_history_to_context=True,
        debug_mode=True,
        debug_level=2,
    )

    # Turn 1
    print("\n  [Turn 1] Sending image with bytes content...")
    run_output = agent.run(
        "Describe this image in detail.",
        images=[Image(content=image_bytes, format="jpeg")],
    )
    print("  Agent response: %s" % str(run_output.content)[:120])
    print_media_info(run_output.messages, label="Turn 1 RunOutput.messages")

    history = agent.get_chat_history()
    print_chat_history(history)

    # Turn 2 -- same session, history should reload with refreshed URLs
    print("  [Turn 2] Asking a visual-only question on same session...")
    run_output_2 = agent.run(
        "Looking at the image from my first message, "
        "estimate the number of pebbles visible and tell me the dominant color palette."
    )
    print("  Agent response: %s" % str(run_output_2.content)[:120])
    print_media_info(
        run_output_2.messages, label="Turn 2 RunOutput.messages (check from_history)"
    )

    history_2 = agent.get_chat_history()
    print_chat_history(history_2)

    print("  [DONE] LocalMediaStorage sync test complete.\n")


# ---------------------------------------------------------------------------
# Test 2: AsyncLocalMediaStorage (async)
# ---------------------------------------------------------------------------
async def test_local_async(image_bytes: bytes) -> None:
    session_id = "test_local_async_%s" % uuid.uuid4().hex[:8]
    print_separator("TEST 2: AsyncLocalMediaStorage (async)")
    print("  session_id: %s" % session_id)

    storage = AsyncLocalMediaStorage(base_path=LOCAL_STORAGE_PATH)
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        media_storage=storage,
        db=AsyncPostgresDb(db_url=ASYNC_DB_URL, session_table=SESSION_TABLE),
        session_id=session_id,
        add_history_to_context=True,
        debug_mode=True,
        debug_level=2,
    )

    # Turn 1
    print("\n  [Turn 1] Sending image with bytes content...")
    run_output = await agent.arun(
        "Describe this image in detail.",
        images=[Image(content=image_bytes, format="jpeg")],
    )
    print("  Agent response: %s" % str(run_output.content)[:120])
    print_media_info(run_output.messages, label="Turn 1 RunOutput.messages")

    history = await agent.aget_chat_history()
    print_chat_history(history)

    # Turn 2 -- same session, history should reload with refreshed URLs
    print("  [Turn 2] Asking a visual-only question on same session...")
    run_output_2 = await agent.arun(
        "Looking at the image from my first message, "
        "estimate the number of pebbles visible and tell me the dominant color palette."
    )
    print("  Agent response: %s" % str(run_output_2.content)[:120])
    print_media_info(
        run_output_2.messages, label="Turn 2 RunOutput.messages (check from_history)"
    )

    history_2 = await agent.aget_chat_history()
    print_chat_history(history_2)

    print("  [DONE] AsyncLocalMediaStorage async test complete.\n")


# ---------------------------------------------------------------------------
# Test 3: S3MediaStorage (sync)
# ---------------------------------------------------------------------------
def test_s3_sync(image_bytes: bytes) -> None:
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        print_separator("TEST 3: S3MediaStorage (sync) -- SKIPPED (no AWS credentials)")
        return

    session_id = "test_s3_sync_%s" % uuid.uuid4().hex[:8]
    bucket = os.environ.get("AGNO_S3_BUCKET", "my-agno-media")
    region = os.environ.get("AWS_REGION", "us-east-1")

    print_separator("TEST 3: S3MediaStorage (sync)")
    print("  session_id: %s" % session_id)
    print("  bucket: %s | region: %s" % (bucket, region))

    storage = S3MediaStorage(
        bucket=bucket,
        region=region,
        prefix="agno/media-test/",
        presigned_url_expiry=3600,
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        media_storage=storage,
        db=PostgresDb(db_url=SYNC_DB_URL, session_table=SESSION_TABLE),
        session_id=session_id,
        add_history_to_context=True,
        debug_mode=True,
        debug_level=2,
    )

    # Turn 1
    print("\n  [Turn 1] Sending image with bytes content...")
    run_output = agent.run(
        "Describe this image in detail.",
        images=[Image(content=image_bytes, format="jpeg")],
    )
    print("  Agent response: %s" % str(run_output.content)[:120])
    print_media_info(run_output.messages, label="Turn 1 RunOutput.messages")

    history = agent.get_chat_history()
    print_chat_history(history)

    # Turn 2 -- same session, history should reload with refreshed URLs
    print("  [Turn 2] Asking a visual-only question on same session...")
    run_output_2 = agent.run(
        "Looking at the image from my first message, "
        "estimate the number of pebbles visible and tell me the dominant color palette."
    )
    print("  Agent response: %s" % str(run_output_2.content)[:120])
    print_media_info(
        run_output_2.messages, label="Turn 2 RunOutput.messages (check from_history)"
    )

    history_2 = agent.get_chat_history()
    print_chat_history(history_2)

    print("  [DONE] S3MediaStorage sync test complete.\n")


# ---------------------------------------------------------------------------
# Test 4: AsyncS3MediaStorage (async)
# ---------------------------------------------------------------------------
async def test_s3_async(image_bytes: bytes) -> None:
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        print_separator(
            "TEST 4: AsyncS3MediaStorage (async) -- SKIPPED (no AWS credentials)"
        )
        return

    session_id = "test_s3_async_%s" % uuid.uuid4().hex[:8]
    bucket = os.environ.get("AGNO_S3_BUCKET", "my-agno-media")
    region = os.environ.get("AWS_REGION", "us-east-1")

    print_separator("TEST 4: AsyncS3MediaStorage (async)")
    print("  session_id: %s" % session_id)
    print("  bucket: %s | region: %s" % (bucket, region))

    storage = AsyncS3MediaStorage(
        bucket=bucket,
        region=region,
        prefix="agno/media-test/",
        presigned_url_expiry=3600,
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        media_storage=storage,
        db=AsyncPostgresDb(db_url=ASYNC_DB_URL, session_table=SESSION_TABLE),
        session_id=session_id,
        add_history_to_context=True,
        debug_mode=True,
        debug_level=2,
    )

    # Turn 1
    print("\n  [Turn 1] Sending image with bytes content...")
    run_output = await agent.arun(
        "Describe this image in detail.",
        images=[Image(content=image_bytes, format="jpeg")],
    )
    print("  Agent response: %s" % str(run_output.content)[:120])
    print_media_info(run_output.messages, label="Turn 1 RunOutput.messages")

    history = await agent.aget_chat_history()
    print_chat_history(history)

    # Turn 2 -- same session, history should reload with refreshed URLs
    print("  [Turn 2] Asking a visual-only question on same session...")
    run_output_2 = await agent.arun(
        "Looking at the image from my first message, "
        "estimate the number of pebbles visible and tell me the dominant color palette."
    )
    print("  Agent response: %s" % str(run_output_2.content)[:120])
    print_media_info(
        run_output_2.messages, label="Turn 2 RunOutput.messages (check from_history)"
    )

    history_2 = await agent.aget_chat_history()
    print_chat_history(history_2)

    print("  [DONE] AsyncS3MediaStorage async test complete.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def _run_async_tests(image_bytes: bytes) -> None:
    await test_local_async(image_bytes)
    await test_s3_async(image_bytes)


if __name__ == "__main__":
    print("Downloading test image...")
    response = httpx.get(TEST_IMAGE_URL, follow_redirects=True)
    response.raise_for_status()
    test_image_bytes = response.content
    print("Downloaded %d bytes\n" % len(test_image_bytes))

    # Sync tests
    # test_local_sync(test_image_bytes)
    # test_s3_sync(test_image_bytes)

    # Async tests
    asyncio.run(_run_async_tests(test_image_bytes))

    print("\n" + "=" * 70)
    print("  ALL TESTS COMPLETE")
    print("=" * 70)
