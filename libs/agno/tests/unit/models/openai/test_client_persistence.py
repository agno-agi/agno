from agno.models.openai import OpenAIChat


class _FakeOpenAIClient:
    def __init__(self, **kwargs):
        self._closed = False

    def is_closed(self):
        return self._closed


class _FakeAsyncOpenAIClient:
    def __init__(self, **kwargs):
        self._closed = False

    def is_closed(self):
        return self._closed


def test_sync_client_persistence(monkeypatch):
    monkeypatch.setattr("agno.models.openai.chat.OpenAIClient", _FakeOpenAIClient)

    model = OpenAIChat(id="gpt-4o-mini", api_key="test-key")

    # First call should create a new client
    first_client = model.get_client()
    assert first_client is not None

    # Second call should reuse the same client
    second_client = model.get_client()
    assert second_client is not None
    assert second_client is first_client

    # Third call should also reuse the same client
    third_client = model.get_client()
    assert third_client is not None
    assert third_client is first_client


def test_sync_client_recreated_when_closed(monkeypatch):
    monkeypatch.setattr("agno.models.openai.chat.OpenAIClient", _FakeOpenAIClient)

    model = OpenAIChat(id="gpt-4o-mini", api_key="test-key")

    # First call creates the client
    first_client = model.get_client()
    assert first_client is not None

    # Simulate the client being closed
    first_client._closed = True

    # Next call should create a new client since the old one is closed
    new_client = model.get_client()
    assert new_client is not None
    assert new_client is not first_client


def test_async_client_persistence(monkeypatch):
    monkeypatch.setattr("agno.models.openai.chat.AsyncOpenAIClient", _FakeAsyncOpenAIClient)

    model = OpenAIChat(id="gpt-4o-mini", api_key="test-key")

    # First call should create a new async client
    first_client = model.get_async_client()
    assert first_client is not None

    # Second call should reuse the same async client
    second_client = model.get_async_client()
    assert second_client is not None
    assert second_client is first_client

    # Third call should also reuse the same async client
    third_client = model.get_async_client()
    assert third_client is not None
    assert third_client is first_client


def test_async_client_recreated_when_closed(monkeypatch):
    monkeypatch.setattr("agno.models.openai.chat.AsyncOpenAIClient", _FakeAsyncOpenAIClient)

    model = OpenAIChat(id="gpt-4o-mini", api_key="test-key")

    # First call creates the async client
    first_client = model.get_async_client()
    assert first_client is not None

    # Simulate the client being closed
    first_client._closed = True

    # Next call should create a new async client since the old one is closed
    new_client = model.get_async_client()
    assert new_client is not None
    assert new_client is not first_client
