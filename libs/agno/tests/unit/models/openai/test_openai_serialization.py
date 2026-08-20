from agno.models.openai.chat import OpenAIChat
from agno.models.utils import get_model_from_dict, resolve_model


def test_config_survives_a_dict_round_trip():
    """to_dict -> get_model_from_dict rebuilds the same class with its config intact."""
    model = OpenAIChat(id="gpt-4o", api_key="test-key", temperature=0.5, seed=7)

    rebuilt = get_model_from_dict(model.to_dict())

    assert isinstance(rebuilt, OpenAIChat)
    assert rebuilt.id == "gpt-4o"
    assert rebuilt.temperature == 0.5
    assert rebuilt.seed == 7


def test_to_dict_omits_the_api_key():
    """The API key never serializes; it is recovered from the live registry instance."""
    data = OpenAIChat(id="gpt-4o", api_key="super-secret").to_dict()

    assert "api_key" not in data


def test_from_dict_ignores_unknown_and_sensitive_keys():
    """from_dict passes only declared fields, so a stray key cannot reach the constructor."""
    rebuilt = OpenAIChat.from_dict({"id": "gpt-4o", "temperature": 0.5, "unknown": "x"})

    assert rebuilt.id == "gpt-4o"
    assert rebuilt.temperature == 0.5


def test_rehydration_tolerates_a_key_this_version_does_not_declare():
    """A row written by a different agno version must still rebuild, not crash the agent load.

    Serialized rows outlive the code that wrote them, so a payload can carry a field this
    version's dataclass no longer declares. Before the `from_dict` dispatch existed this rebuilt
    from `id` alone and ignored the extra; it must not regress to a TypeError.
    """
    payload = {
        "id": "gpt-4o",
        "name": "OpenAIChat",
        "provider": "OpenAI",
        "temperature": 0.5,
        "some_future_field": True,
    }

    rebuilt = resolve_model(payload, None)

    assert isinstance(rebuilt, OpenAIChat)
    assert rebuilt.id == "gpt-4o"
    assert rebuilt.temperature == 0.5
