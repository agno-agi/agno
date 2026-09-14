from agno.os.interfaces.slack.prompts import normalize_prompts


def test_normalize_prompts_accepts_strings_and_dicts():
    raw = [
        "plain string",
        {"title": "T", "message": "M"},
        {"message": "only message"},
        {"title": "no message"},
        42,
        {"title": "five", "message": "five"},
        {"title": "six", "message": "six"},
    ]
    prompts = normalize_prompts(raw)
    assert prompts == [
        {"title": "plain string", "message": "plain string"},
        {"title": "T", "message": "M"},
        {"title": "only message", "message": "only message"},
        {"title": "five", "message": "five"},
    ]
    assert normalize_prompts(None) == []
