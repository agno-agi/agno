from agno.os.interfaces.agui.redact import redact_sensitive_data


def test_redact_sensitive_data_keys():
    # Test dictionary key matching (case-insensitive)
    data = {
        "normal_key": "visible",
        "API_KEY": "secret123",
        "db_password": "supersecret",
        "nested": {"token": "hidden_token", "innocuous": "shown"},
    }

    redacted = redact_sensitive_data(data)

    assert redacted["normal_key"] == "visible"
    assert redacted["API_KEY"] == "[REDACTED]"
    assert redacted["db_password"] == "[REDACTED]"
    assert redacted["nested"]["token"] == "[REDACTED]"
    assert redacted["nested"]["innocuous"] == "shown"


def test_redact_sensitive_data_nested_structures():
    # Test lists and tuples
    data = {"items": [{"name": "test"}, {"secret": "hidden"}], "tuple_data": (1, {"password": "pwd"})}

    redacted = redact_sensitive_data(data)

    assert redacted["items"][0]["name"] == "test"
    assert redacted["items"][1]["secret"] == "[REDACTED]"
    assert redacted["tuple_data"][0] == 1
    assert redacted["tuple_data"][1]["password"] == "[REDACTED]"


def test_redact_sensitive_data_regex_values():
    # Test values that match regexes under innocuous keys
    data = {
        "my_string": "sk-1234567890abcdefg",  # OpenAI
        "aws_key": "AKIAIOSFODNN7EXAMPLE",  # AWS
        "github": "ghp_123456789012345678901234567890",  # GitHub
        "slack": "xoxb-1234567890-1234567890-abcdefg",  # Slack
        "stripe": "sk_live_1234567890abcdefg",  # Stripe
        "google": "AIzaSyB-1234567890abcdefghijklmnopqrst",  # Google
        "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZS.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",  # JWT
        "bearer1": "Bearer <token>",
        "bearer2": "Bearer abcdefg.1234",
        "normal": "just a normal string with sk-123 inside",  # Should not match regex (sk- has to be 10+ chars)
    }

    redacted = redact_sensitive_data(data)

    assert redacted["my_string"] == "[REDACTED]"
    assert redacted["aws_key"] == "[REDACTED]"
    assert redacted["github"] == "[REDACTED]"
    assert redacted["slack"] == "[REDACTED]"
    assert redacted["stripe"] == "[REDACTED]"
    assert redacted["google"] == "[REDACTED]"
    assert redacted["jwt"] == "[REDACTED]"
    assert redacted["bearer1"] == "[REDACTED]"
    assert redacted["bearer2"] == "[REDACTED]"
    assert redacted["normal"] == "just a normal string with sk-123 inside"


def test_redact_sensitive_data_no_mutation():
    # Ensure original object is not mutated
    data = {"secret": "123", "nested": {"password": "abc"}}
    redacted = redact_sensitive_data(data)

    assert redacted["secret"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"

    assert data["secret"] == "123"
    assert data["nested"]["password"] == "abc"


def test_redact_sensitive_data_weird_input():
    # Should not crash on weird input
    class WeirdObject:
        pass

    weird = WeirdObject()
    data = {"normal": "ok", "weird": weird}

    redacted = redact_sensitive_data(data)
    assert redacted["normal"] == "ok"
    assert redacted["weird"] == weird
