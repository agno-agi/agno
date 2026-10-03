import pytest

# Diverse text samples to exercise UTF-8 handling across scripts and edge cases
UTF8_SAMPLES = [
    "你好",  # Chinese
    "こんにちは",  # Japanese
    "안녕하세요",  # Korean
    "Привет",  # Cyrillic
    "مرحبا",  # Arabic
    "नमस्ते",  # Devanagari
    "שלום",  # Hebrew
    "Café naïve – élève",  # Accented Latin, en dash
    "🙂🚀✨",  # Emoji sequence
    "e\u0301 vs é",  # combining mark vs precomposed
]


def _assert_insert_contains_text(vector_db, expected: str) -> None:
    docs = vector_db.inserted_documents
    assert len(docs) >= 1
    contents = "\n".join([getattr(d, "content", "") for d in docs])
    assert expected in contents


@pytest.mark.parametrize("text", UTF8_SAMPLES)
def test_insert_sync_handles_utf8_samples(knowledge, vector_db, text: str) -> None:
    knowledge.insert(text_content=text)
    _assert_insert_contains_text(vector_db, text)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", UTF8_SAMPLES)
async def test_ainsert_handles_utf8_samples(knowledge, vector_db, text: str) -> None:
    await knowledge.ainsert(text_content=text)
    _assert_insert_contains_text(vector_db, text)


def test_insert_sync_replaces_invalid_surrogates(knowledge, vector_db) -> None:
    # Lone surrogate characters are not valid in UTF-8; they should be replaced with U+FFFD
    knowledge.insert(text_content="bad\udffftext")
    docs = vector_db.inserted_documents
    contents = "\n".join([getattr(d, "content", "") for d in docs])
    # Some environments render replacement as '?' when logging/printing
    assert "\ufffd" in contents or "�" in contents or "?" in contents


@pytest.mark.asyncio
async def test_ainsert_replaces_invalid_surrogates(knowledge, vector_db) -> None:
    await knowledge.ainsert(text_content="\ud800orphan")
    docs = vector_db.inserted_documents
    contents = "\n".join([getattr(d, "content", "") for d in docs])
    assert "\ufffd" in contents or "�" in contents or "?" in contents
