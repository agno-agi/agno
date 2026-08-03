import time
from unittest.mock import AsyncMock, patch

import pytest

from agno.os.interfaces.teams.helpers import (
    ActivityContent,
    TeamsConfig,
    _clean_mention_text,
    _get_bot_token,
    _post_activity,
    _reply_endpoint,
    build_conversation_ref,
    download_attachments_async,
    extract_activity_content,
    extract_conversation_ref,
    merge_conversation_ref,
    send_teams_message_async,
    typing_indicator_async,
)


def _make_config(**overrides) -> TeamsConfig:
    base = {
        "app_id": "app-id",
        "app_password": "secret",
        "tenant_id": "botframework.com",
    }
    base.update(overrides)
    return TeamsConfig(**base)


# === TeamsConfig.init env-var handling ===


def test_config_init_from_env_vars():
    with patch.dict(
        "os.environ",
        {
            "MICROSOFT_APP_ID": "env-app",
            "MICROSOFT_APP_PASSWORD": "env-pwd",
            "MICROSOFT_APP_TENANT_ID": "tenant-123",
        },
        clear=True,
    ):
        cfg = TeamsConfig.init()
    assert cfg.app_id == "env-app"
    assert cfg.app_password == "env-pwd"
    assert cfg.tenant_id == "tenant-123"


def test_config_init_arg_overrides_env():
    with patch.dict("os.environ", {"MICROSOFT_APP_ID": "env-app", "MICROSOFT_APP_PASSWORD": "env-pwd"}, clear=True):
        cfg = TeamsConfig.init(app_id="arg-app")
    assert cfg.app_id == "arg-app"


def test_config_init_missing_app_id_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="MICROSOFT_APP_ID"):
            TeamsConfig.init(app_password="secret")


def test_config_init_missing_password_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="MICROSOFT_APP_PASSWORD"):
            TeamsConfig.init(app_id="app-id")


def test_config_defaults_to_botframework_tenant():
    with patch.dict("os.environ", {"MICROSOFT_APP_ID": "a", "MICROSOFT_APP_PASSWORD": "b"}, clear=True):
        cfg = TeamsConfig.init()
    assert cfg.tenant_id == "botframework.com"


def test_token_url_uses_tenant():
    cfg = _make_config(tenant_id="tenant-xyz")
    assert cfg.token_url() == "https://login.microsoftonline.com/tenant-xyz/oauth2/v2.0/token"


# === _get_bot_token cache behaviour ===


@pytest.mark.asyncio
async def test_get_bot_token_fetches_and_caches():
    cfg = _make_config()

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "tok-1", "expires_in": 3600}

    async def fake_post(self, url, data=None):
        assert data["grant_type"] == "client_credentials"
        assert data["scope"] == "https://api.botframework.com/.default"
        assert data["client_id"] == "app-id"
        return FakeResp()

    with patch("httpx.AsyncClient.post", new=fake_post):
        tok = await _get_bot_token(cfg)
    assert tok == "tok-1"
    assert cfg._cached_token == "tok-1"
    assert cfg._token_expires_at > time.time() + 3000


@pytest.mark.asyncio
async def test_get_bot_token_returns_cached_when_fresh():
    cfg = _make_config()
    cfg._cached_token = "cached-tok"
    cfg._token_expires_at = time.time() + 3600

    async def _should_not_be_called(*a, **kw):
        raise AssertionError("Cached token should have been returned")

    with patch("httpx.AsyncClient.post", new=_should_not_be_called):
        tok = await _get_bot_token(cfg)
    assert tok == "cached-tok"


@pytest.mark.asyncio
async def test_get_bot_token_refetches_when_expired():
    cfg = _make_config()
    cfg._cached_token = "old-tok"
    cfg._token_expires_at = time.time() - 10  # expired

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"access_token": "new-tok", "expires_in": 3600}

    async def fake_post(self, url, data=None):
        return FakeResp()

    with patch("httpx.AsyncClient.post", new=fake_post):
        tok = await _get_bot_token(cfg)
    assert tok == "new-tok"


@pytest.mark.asyncio
async def test_get_bot_token_raises_on_missing_access_token():
    cfg = _make_config()

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "unauthorized_client"}

    async def fake_post(self, url, data=None):
        return FakeResp()

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(RuntimeError, match="missing access_token"):
            await _get_bot_token(cfg)


# === _reply_endpoint URL construction ===


def test_reply_endpoint_strips_trailing_slash():
    url = _reply_endpoint("https://smba.trafficmanager.net/emea/", "conv-1")
    assert url == "https://smba.trafficmanager.net/emea/v3/conversations/conv-1/activities"


def test_reply_endpoint_with_activity_id():
    url = _reply_endpoint("https://smba.example.com", "conv-1", "act-42")
    assert url == "https://smba.example.com/v3/conversations/conv-1/activities/act-42"


# === extract_activity_content ===


def test_extract_content_plain_text():
    activity = {"type": "message", "text": "hello bot"}
    parsed = extract_activity_content(activity)
    assert parsed is not None
    assert parsed.text == "hello bot"
    assert parsed.image_attachments == []
    assert parsed.file_attachments == []


def test_extract_content_strips_bot_mention():
    activity = {
        "type": "message",
        "text": "<at>MyBot</at> what is the weather",
        "entities": [{"type": "mention", "text": "<at>MyBot</at>"}],
    }
    parsed = extract_activity_content(activity)
    assert parsed is not None
    assert parsed.text == "what is the weather"


def test_extract_content_ignores_non_message_activity():
    assert extract_activity_content({"type": "typing"}) is None
    assert extract_activity_content({"type": "conversationUpdate"}) is None


def test_extract_content_separates_image_and_file_attachments():
    activity = {
        "type": "message",
        "text": "see attached",
        "attachments": [
            {"contentType": "image/png", "contentUrl": "https://ex/image.png"},
            {"contentType": "application/pdf", "contentUrl": "https://ex/report.pdf"},
            {"contentType": "text/html", "content": "<div/>"},  # no contentUrl → dropped
        ],
    }
    parsed = extract_activity_content(activity)
    assert parsed is not None
    assert len(parsed.image_attachments) == 1
    assert parsed.image_attachments[0]["contentUrl"] == "https://ex/image.png"
    assert len(parsed.file_attachments) == 1
    assert parsed.file_attachments[0]["contentUrl"] == "https://ex/report.pdf"


def test_extract_content_returns_none_when_empty():
    # message with no text and no attachments — nothing to do
    activity = {"type": "message", "text": ""}
    assert extract_activity_content(activity) is None


def test_extract_content_image_only_still_returns():
    activity = {
        "type": "message",
        "text": "",
        "attachments": [{"contentType": "image/png", "contentUrl": "https://ex/img.png"}],
    }
    parsed = extract_activity_content(activity)
    assert parsed is not None
    assert parsed.text == ""
    assert len(parsed.image_attachments) == 1


# === send_teams_message_async ===


@pytest.mark.asyncio
async def test_send_message_posts_markdown_activity():
    cfg = _make_config()
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async(
            "https://svc.example.com",
            "conv-1",
            "hello",
            cfg,
            reply_to_activity_id="act-1",
        )
    mock_post.assert_awaited_once()
    args, _kwargs = mock_post.call_args
    service_url, conversation_id, activity = args[0], args[1], args[2]
    assert service_url == "https://svc.example.com"
    assert conversation_id == "conv-1"
    assert activity["type"] == "message"
    assert activity["text"] == "hello"
    assert activity["textFormat"] == "markdown"
    assert activity["replyToId"] == "act-1"


@pytest.mark.asyncio
async def test_send_message_skips_empty_content():
    cfg = _make_config()
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "", cfg)
        await send_teams_message_async("svc", "conv", "   ", cfg)
        await send_teams_message_async("svc", "conv", None, cfg)
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_italics_wraps_each_line():
    cfg = _make_config()
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "line1\nline2", cfg, italics=True)
    activity = mock_post.call_args.args[2]
    assert activity["text"] == "_line1_\n_line2_"


@pytest.mark.asyncio
async def test_send_message_coerces_pydantic_model():
    from pydantic import BaseModel

    class Payload(BaseModel):
        answer: str

    cfg = _make_config()
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", Payload(answer="42"), cfg)
    activity = mock_post.call_args.args[2]
    assert '"answer": "42"' in activity["text"]


# === typing_indicator_async ===


@pytest.mark.asyncio
async def test_send_message_includes_bot_identity():
    """Bot Connector rejects outbound activities without `from`; verify we pass it through."""
    cfg = _make_config()
    bot_id = {"id": "28:bot-guid", "name": "Agno Bot"}
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "hi", cfg, bot_identity=bot_id)
    activity = mock_post.call_args.args[2]
    assert activity["from"] == bot_id


@pytest.mark.asyncio
async def test_send_message_omits_bot_identity_when_absent():
    cfg = _make_config()
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "hi", cfg)
    activity = mock_post.call_args.args[2]
    assert "from" not in activity


@pytest.mark.asyncio
async def test_typing_indicator_sends_typing_activity():
    cfg = _make_config()
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await typing_indicator_async("svc", "conv-1", cfg, reply_to_activity_id="act-1")
    activity = mock_post.call_args.args[2]
    assert activity["type"] == "typing"
    assert activity["replyToId"] == "act-1"


@pytest.mark.asyncio
async def test_typing_indicator_includes_bot_identity():
    cfg = _make_config()
    bot_id = {"id": "28:bot-guid"}
    with patch("agno.os.interfaces.teams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await typing_indicator_async("svc", "conv", cfg, bot_identity=bot_id)
    activity = mock_post.call_args.args[2]
    assert activity["from"] == bot_id
    assert activity["type"] == "typing"


@pytest.mark.asyncio
async def test_typing_indicator_swallows_errors():
    cfg = _make_config()
    with patch(
        "agno.os.interfaces.teams.helpers._post_activity",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise — typing failures are non-fatal
        await typing_indicator_async("svc", "conv-1", cfg)


# === download_attachments_async ===


def test_build_conversation_ref_shape():
    ref = build_conversation_ref("https://svc", "conv-1", {"id": "28:bot", "name": "Bot"})
    assert ref == {
        "service_url": "https://svc",
        "conversation_id": "conv-1",
        "bot_identity": {"id": "28:bot", "name": "Bot"},
    }


def test_build_conversation_ref_allows_none_bot_identity():
    # Should never happen in practice, but the helper mustn't blow up
    ref = build_conversation_ref("https://svc", "conv-1", None)
    assert ref["bot_identity"] is None


def test_extract_conversation_ref_returns_none_when_missing():
    assert extract_conversation_ref(None) is None
    assert extract_conversation_ref({}) is None
    assert extract_conversation_ref({"unrelated": "value"}) is None


def test_extract_conversation_ref_rejects_incomplete_ref():

    bad = {"teams_conversation_ref": {"conversation_id": "conv-1"}}
    assert extract_conversation_ref(bad) is None

    bad = {"teams_conversation_ref": {"service_url": "https://svc"}}
    assert extract_conversation_ref(bad) is None

    bad = {"teams_conversation_ref": "garbage"}
    assert extract_conversation_ref(bad) is None


def test_extract_conversation_ref_returns_valid_ref():
    session_data = {
        "session_state": {"foo": "bar"},
        "teams_conversation_ref": {
            "service_url": "https://svc",
            "conversation_id": "conv-1",
            "bot_identity": {"id": "28:bot"},
        },
    }
    ref = extract_conversation_ref(session_data)
    assert ref is not None
    assert ref["service_url"] == "https://svc"
    assert ref["bot_identity"] == {"id": "28:bot"}


def test_merge_conversation_ref_preserves_existing_keys():
    existing = {"session_state": {"foo": "bar"}, "images": ["x.png"]}
    ref = build_conversation_ref("https://svc", "conv-1", {"id": "28:bot"})
    merged = merge_conversation_ref(existing, ref)

    assert "teams_conversation_ref" not in existing
    assert merged["session_state"] == {"foo": "bar"}
    assert merged["images"] == ["x.png"]
    assert merged["teams_conversation_ref"] == ref


def test_merge_conversation_ref_handles_none_session_data():
    ref = build_conversation_ref("https://svc", "conv-1", None)
    merged = merge_conversation_ref(None, ref)
    assert merged == {"teams_conversation_ref": ref}


def test_merge_conversation_ref_overwrites_stale_ref():
    old_ref = build_conversation_ref("https://old-svc", "old-conv", None)
    existing = {"teams_conversation_ref": old_ref}
    new_ref = build_conversation_ref("https://new-svc", "new-conv", {"id": "28:bot"})
    merged = merge_conversation_ref(existing, new_ref)
    assert merged["teams_conversation_ref"]["service_url"] == "https://new-svc"


@pytest.mark.asyncio
async def test_download_attachments_returns_images_and_files():
    parsed = ActivityContent(
        text="hi",
        image_attachments=[{"contentUrl": "https://ex/i.png"}],
        file_attachments=[{"contentUrl": "https://ex/f.pdf"}],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=True):
        if url.endswith(".png"):
            return b"pngbytes", "image/png"
        return b"pdfbytes", "application/pdf"

    with patch("agno.os.interfaces.teams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert skipped == []
    assert "images" in run_kwargs
    assert len(run_kwargs["images"]) == 1
    assert run_kwargs["images"][0].content == b"pngbytes"
    assert "files" in run_kwargs
    assert len(run_kwargs["files"]) == 1
    assert run_kwargs["files"][0].content == b"pdfbytes"


@pytest.mark.asyncio
async def test_download_attachments_records_failures():
    parsed = ActivityContent(
        text="hi",
        image_attachments=[{"contentUrl": "https://ex/i.png"}],
        file_attachments=[{"contentUrl": "https://ex/f.pdf"}],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=True):
        return None, None

    with patch("agno.os.interfaces.teams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert run_kwargs == {}
    assert "image" in skipped
    assert "file" in skipped


@pytest.mark.asyncio
async def test_download_attachments_skips_missing_url():
    parsed = ActivityContent(
        text="hi",
        image_attachments=[{"contentType": "image/png"}],
        file_attachments=[],
    )
    cfg = _make_config()
    with patch("agno.os.interfaces.teams.helpers._download_attachment", new_callable=AsyncMock) as mock_dl:
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)
    mock_dl.assert_not_called()
    assert run_kwargs == {}
    assert skipped == []


# === _clean_mention_text ===


def test_clean_mention_returns_empty_for_empty_input():
    assert _clean_mention_text("") == ""


def test_clean_mention_returns_empty_for_none_input():
    # activity.get("text") can be None if the field is absent
    assert _clean_mention_text(None) == ""  # type: ignore[arg-type]


def test_clean_mention_strips_multiple_at_tags():
    text = "<at>Bot</at> hi <at>User</at> there"
    assert _clean_mention_text(text) == "hi  there"


def test_clean_mention_case_insensitive():
    text = "<AT>Bot</AT> hello"
    assert _clean_mention_text(text) == "hello"


def test_clean_mention_leaves_plain_text_alone():
    assert _clean_mention_text("just some text") == "just some text"


# === _post_activity error path ===


@pytest.mark.asyncio
async def test_post_activity_raises_on_http_status_error():
    """HTTP 4xx/5xx from Bot Connector must surface — router uses this
    to trigger the fallback error reply."""
    import httpx

    cfg = _make_config()
    cfg._cached_token = "tok"
    cfg._token_expires_at = time.time() + 3600

    request = httpx.Request("POST", "https://svc/v3/conversations/c/activities")
    response = httpx.Response(status_code=401, request=request, text="Unauthorized")

    async def fake_post(self, url, headers=None, json=None):
        return response

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(httpx.HTTPStatusError):
            await _post_activity("https://svc", "conv-1", {"type": "message"}, cfg)


@pytest.mark.asyncio
async def test_post_activity_returns_none_when_response_has_no_json():
    """Bot Connector sometimes returns 200 with an empty body — the helper
    should treat that as success (no dict payload)."""
    cfg = _make_config()
    cfg._cached_token = "tok"
    cfg._token_expires_at = time.time() + 3600

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("no json body")

    async def fake_post(self, url, headers=None, json=None):
        return FakeResp()

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await _post_activity("https://svc", "conv-1", {"type": "message"}, cfg)
    assert result is None


# === TeamsConfig tenant env override ===


def test_config_init_uses_arg_tenant_over_env():
    from unittest.mock import patch as _patch

    with _patch.dict(
        "os.environ",
        {
            "MICROSOFT_APP_ID": "app",
            "MICROSOFT_APP_PASSWORD": "pw",
            "MICROSOFT_APP_TENANT_ID": "env-tenant",
        },
        clear=True,
    ):
        cfg = TeamsConfig.init(tenant_id="arg-tenant")
    assert cfg.tenant_id == "arg-tenant"


# === _get_jwks cache TTL ===


def test_get_jwks_caches_within_ttl():
    """Second call inside TTL must not re-fetch OpenID metadata or JWKS."""
    from agno.os.interfaces.teams import security as teams_security

    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0

    metadata_calls = {"n": 0}
    jwks_calls = {"n": 0}

    def fake_metadata():
        metadata_calls["n"] += 1
        return {"jwks_uri": "https://example/jwks", "issuer": "https://api.botframework.com"}

    def fake_jwks(uri):
        jwks_calls["n"] += 1
        return [{"kty": "RSA", "kid": "k1"}]

    with (
        patch("agno.os.interfaces.teams.security._fetch_openid_metadata", side_effect=fake_metadata),
        patch("agno.os.interfaces.teams.security._fetch_jwks", side_effect=fake_jwks),
    ):
        keys1 = teams_security._get_jwks()
        keys2 = teams_security._get_jwks()

    assert keys1 == keys2
    assert metadata_calls["n"] == 1
    assert jwks_calls["n"] == 1

    # cleanup
    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0


def test_get_jwks_raises_when_metadata_missing_jwks_uri():
    from agno.os.interfaces.teams import security as teams_security

    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0

    with patch("agno.os.interfaces.teams.security._fetch_openid_metadata", return_value={"issuer": "x"}):
        with pytest.raises(RuntimeError, match="jwks_uri"):
            teams_security._get_jwks()

    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0


def test_get_jwks_refetches_after_ttl_expiry():
    """After TTL expiry, next call should hit metadata + JWKS endpoints again."""
    from agno.os.interfaces.teams import security as teams_security

    # Seed cache as if fetched long ago
    teams_security._jwks_cache["keys"] = [{"kty": "RSA", "kid": "old"}]
    teams_security._jwks_cache["fetched_at"] = time.time() - teams_security._JWKS_CACHE_TTL_SECONDS - 10

    with (
        patch(
            "agno.os.interfaces.teams.security._fetch_openid_metadata",
            return_value={"jwks_uri": "https://example/jwks", "issuer": "https://api.botframework.com"},
        ) as mock_meta,
        patch(
            "agno.os.interfaces.teams.security._fetch_jwks",
            return_value=[{"kty": "RSA", "kid": "new"}],
        ) as mock_jwks,
    ):
        keys = teams_security._get_jwks()

    assert keys[0]["kid"] == "new"
    mock_meta.assert_called_once()
    mock_jwks.assert_called_once()

    teams_security._jwks_cache["keys"] = None
    teams_security._jwks_cache["fetched_at"] = 0.0
