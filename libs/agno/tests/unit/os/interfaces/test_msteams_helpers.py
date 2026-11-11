import time
from unittest.mock import AsyncMock, patch

import pytest

from agno.os.interfaces.msteams.helpers import (
    ActivityContent,
    MSTeamsConfig,
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


def _make_config(**overrides) -> MSTeamsConfig:
    base = {
        "app_id": "app-id",
        "app_password": "secret",
        "tenant_id": "botframework.com",
    }
    base.update(overrides)
    return MSTeamsConfig(**base)


# === MSTeamsConfig.init env-var handling ===


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
        cfg = MSTeamsConfig.init()
    assert cfg.app_id == "env-app"
    assert cfg.app_password == "env-pwd"
    assert cfg.tenant_id == "tenant-123"


def test_config_init_arg_overrides_env():
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_ID": "env-app", "MICROSOFT_APP_PASSWORD": "env-pwd", "MICROSOFT_APP_TENANT_ID": "tenant"},
        clear=True,
    ):
        cfg = MSTeamsConfig.init(app_id="arg-app")
    assert cfg.app_id == "arg-app"


def test_config_init_missing_app_id_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="MICROSOFT_APP_ID"):
            MSTeamsConfig.init(app_password="secret")


def test_config_init_missing_password_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="MICROSOFT_APP_PASSWORD"):
            MSTeamsConfig.init(app_id="app-id")


def test_dev_bypass_requires_both_credentials_absent():
    """A password without an app id would leave app_id="", which the validator
    reads as "no credentials" and bypasses."""
    with patch.dict(
        "os.environ",
        {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true", "MICROSOFT_APP_PASSWORD": "a-real-secret"},
        clear=True,
    ):
        with pytest.raises(ValueError, match="MICROSOFT_APP_ID"):
            MSTeamsConfig.init()


def test_dev_bypass_allows_a_fully_credential_free_config():
    """The genuine dev shape -- neither credential set -- still builds."""
    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"}, clear=True):
        cfg = MSTeamsConfig.init()
    assert cfg.app_id == ""
    assert cfg.app_password == ""


def test_config_requires_explicit_tenant():
    with patch.dict("os.environ", {"MICROSOFT_APP_ID": "a", "MICROSOFT_APP_PASSWORD": "b"}, clear=True):
        with pytest.raises(ValueError, match="MICROSOFT_APP_TENANT_ID"):
            MSTeamsConfig.init()


@pytest.mark.parametrize("from_env", [False, True])
def test_config_strips_credentials_and_tenant(from_env):
    values = {"app_id": " app ", "app_password": " secret ", "tenant_id": " tenant "}
    env = (
        {
            "MICROSOFT_APP_ID": values["app_id"],
            "MICROSOFT_APP_PASSWORD": values["app_password"],
            "MICROSOFT_APP_TENANT_ID": values["tenant_id"],
        }
        if from_env
        else {}
    )
    with patch.dict("os.environ", env, clear=True):
        cfg = MSTeamsConfig.init(**({} if from_env else values))
    assert (cfg.app_id, cfg.app_password, cfg.tenant_id) == ("app", "secret", "tenant")


@pytest.mark.asyncio
async def test_bypass_posts_without_auth_or_token_fetch(caplog):
    import httpx

    with patch.dict("os.environ", {"MICROSOFT_APP_SKIP_JWT_VALIDATION": "true"}, clear=True):
        cfg = MSTeamsConfig.init()
    seen = []

    async def post(self, url, headers, json):
        seen.append(headers)
        return httpx.Response(200, request=httpx.Request("POST", url), json={"id": "reply"})

    with (
        patch("httpx.AsyncClient.post", new=post),
        patch("agno.os.interfaces.msteams.helpers._get_bot_token", new_callable=AsyncMock) as token,
    ):
        await _post_activity("https://svc", "personal", {"type": "message"}, cfg)
        await _post_activity("https://svc", "personal", {"type": "message"}, cfg)
    token.assert_not_called()
    assert len(seen) == 2
    assert all("Authorization" not in headers for headers in seen)
    assert caplog.text.count("Bot Framework JWT check disabled") == 1


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


def test_extract_content_preserves_own_bot_display_name():
    activity = {
        "type": "message",
        "text": "<at>MyBot</at> what is the weather",
        "recipient": {"id": "bot", "name": "MyBot"},
        "entities": [{"type": "mention", "text": "<at>MyBot</at>", "mentioned": {"id": "bot"}}],
    }
    parsed = extract_activity_content(activity)
    assert parsed is not None
    assert parsed.text == "MyBot what is the weather"


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
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
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
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "", cfg)
        await send_teams_message_async("svc", "conv", "   ", cfg)
        await send_teams_message_async("svc", "conv", None, cfg)
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_send_message_italics_wraps_each_line():
    cfg = _make_config()
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "line1\nline2", cfg, italics=True)
    activity = mock_post.call_args.args[2]
    # Two trailing spaces, not a bare newline: this is sent as markdown, which
    # renders a single newline as a space and welds the lines into one
    # paragraph. Reasoning is the only caller, and it is a list of steps.
    assert activity["text"] == "_line1_  \n_line2_"


@pytest.mark.asyncio
async def test_send_message_coerces_pydantic_model():
    from pydantic import BaseModel

    class Payload(BaseModel):
        answer: str

    cfg = _make_config()
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", Payload(answer="42"), cfg)
    activity = mock_post.call_args.args[2]
    assert '"answer": "42"' in activity["text"]


# === send_teams_message_async — bot identity ===


@pytest.mark.asyncio
async def test_send_message_includes_bot_identity():
    """`from` is passed through when the caller supplies it."""
    cfg = _make_config()
    bot_id = {"id": "28:bot-guid", "name": "Agno Bot"}
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "hi", cfg, bot_identity=bot_id)
    activity = mock_post.call_args.args[2]
    assert activity["from"] == bot_id


@pytest.mark.asyncio
async def test_send_message_omits_bot_identity_when_absent():
    cfg = _make_config()
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await send_teams_message_async("svc", "conv", "hi", cfg)
    activity = mock_post.call_args.args[2]
    assert "from" not in activity


@pytest.mark.asyncio
async def test_typing_indicator_sends_typing_activity():
    cfg = _make_config()
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await typing_indicator_async("svc", "conv-1", cfg, reply_to_activity_id="act-1")
    activity = mock_post.call_args.args[2]
    assert activity["type"] == "typing"
    assert activity["replyToId"] == "act-1"


@pytest.mark.asyncio
async def test_typing_indicator_includes_bot_identity():
    cfg = _make_config()
    bot_id = {"id": "28:bot-guid"}
    with patch("agno.os.interfaces.msteams.helpers._post_activity", new_callable=AsyncMock) as mock_post:
        await typing_indicator_async("svc", "conv", cfg, bot_identity=bot_id)
    activity = mock_post.call_args.args[2]
    assert activity["from"] == bot_id
    assert activity["type"] == "typing"


@pytest.mark.asyncio
async def test_typing_indicator_swallows_errors():
    cfg = _make_config()
    with patch(
        "agno.os.interfaces.msteams.helpers._post_activity",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        # Must not raise — typing failures are non-fatal
        await typing_indicator_async("svc", "conv-1", cfg)


# === conversation reference helpers ===


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
    bad = {"msteams_conversation_ref": {"conversation_id": "conv-1"}}
    assert extract_conversation_ref(bad) is None

    bad = {"msteams_conversation_ref": {"service_url": "https://svc"}}
    assert extract_conversation_ref(bad) is None

    bad = {"msteams_conversation_ref": "garbage"}
    assert extract_conversation_ref(bad) is None


def test_extract_conversation_ref_returns_valid_ref():
    session_data = {
        "session_state": {"foo": "bar"},
        "msteams_conversation_ref": {
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

    assert "msteams_conversation_ref" not in existing
    assert merged["session_state"] == {"foo": "bar"}
    assert merged["images"] == ["x.png"]
    assert merged["msteams_conversation_ref"] == ref


def test_merge_conversation_ref_handles_none_session_data():
    ref = build_conversation_ref("https://svc", "conv-1", None)
    merged = merge_conversation_ref(None, ref)
    assert merged == {"msteams_conversation_ref": ref}


def test_merge_conversation_ref_overwrites_stale_ref():
    old_ref = build_conversation_ref("https://old-svc", "old-conv", None)
    existing = {"msteams_conversation_ref": old_ref}
    new_ref = build_conversation_ref("https://new-svc", "new-conv", {"id": "28:bot"})
    merged = merge_conversation_ref(existing, new_ref)
    assert merged["msteams_conversation_ref"]["service_url"] == "https://new-svc"


@pytest.mark.asyncio
async def test_download_attachments_returns_images_and_files():
    parsed = ActivityContent(
        text="hi",
        image_attachments=[{"contentUrl": "https://ex/i.png"}],
        file_attachments=[{"contentUrl": "https://ex/f.pdf"}],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        if url.endswith(".png"):
            return b"pngbytes", "image/png"
        return b"pdfbytes", "application/pdf"

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert skipped == []
    assert "images" in run_kwargs
    assert len(run_kwargs["images"]) == 1
    assert run_kwargs["images"][0].content == b"pngbytes"
    assert "files" in run_kwargs
    assert len(run_kwargs["files"]) == 1
    assert run_kwargs["files"][0].content == b"pdfbytes"


@pytest.mark.asyncio
async def test_download_attachments_image_keeps_the_activitys_declared_type():
    """Teams serves its attachment CDN as application/octet-stream, which the
    model rejects outright. The activity already declares the real type -- it is
    what classified this attachment as an image -- so it wins over the header."""
    parsed = ActivityContent(
        text="hi",
        image_attachments=[{"contentType": "image/png", "contentUrl": "https://ex/i.png"}],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        return b"pngbytes", "application/octet-stream"

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert skipped == []
    assert run_kwargs["images"][0].mime_type == "image/png"


@pytest.mark.asyncio
async def test_download_attachments_records_failures():
    parsed = ActivityContent(
        text="hi",
        image_attachments=[{"contentUrl": "https://ex/i.png"}],
        file_attachments=[{"contentUrl": "https://ex/f.pdf"}],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        return None, None

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert run_kwargs == {}
    assert "image" in skipped
    assert "file" in skipped


@pytest.mark.asyncio
async def test_download_attachments_skips_missing_url():
    """No url means nothing to fetch, so no request is made -- but the attachment is
    still gone, and the user hears about it the same way a failed download is
    reported."""
    parsed = ActivityContent(
        text="hi",
        image_attachments=[{"contentType": "image/png"}],
        file_attachments=[],
    )
    cfg = _make_config()
    with patch("agno.os.interfaces.msteams.helpers._download_attachment", new_callable=AsyncMock) as mock_dl:
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)
    mock_dl.assert_not_called()
    assert run_kwargs == {}
    assert skipped == ["image"]


@pytest.mark.asyncio
async def test_download_attachments_unsupported_mime_is_skipped():
    """An unsupported type cannot be forwarded at all. mime_type=None does not hide
    it: the model re-derives the type from the filename and the provider rejects the
    whole run, so the user loses their text along with the attachment. Skipping the
    file and telling them keeps the message alive."""
    parsed = ActivityContent(
        text="see attached",
        image_attachments=[],
        file_attachments=[
            {"contentUrl": "https://ex/report", "name": "report.bin"},
            {"contentUrl": "https://ex/clip", "name": "clip.mp4"},
        ],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        # no content-type header at all, then a type outside the allowlist
        return (b"binbytes", None) if url.endswith("report") else (b"mp4bytes", "video/mp4")

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert "files" not in run_kwargs
    assert skipped == ["report.bin", "clip.mp4"]


def test_extract_content_classifies_a_file_that_carries_only_a_download_url():
    """_attachment_download_url prefers content.downloadUrl, so gating classification
    on contentUrl makes that preference unreachable for an attachment that has only
    the one field. The attachment is then dropped before anything can report it."""
    activity = {
        "type": "message",
        "text": "see attached",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.teams.file.download.info",
                "name": "report.pdf",
                "content": {"downloadUrl": "https://ex/dl/report.pdf"},
            }
        ],
    }

    parsed = extract_activity_content(activity)

    assert parsed is not None
    assert len(parsed.file_attachments) == 1


@pytest.mark.asyncio
async def test_download_attachments_reports_an_attachment_with_no_url():
    """A failed download is reported; a missing url was not, so the attachment
    vanished with the user told nothing at all. Both are the same loss to them."""
    parsed = ActivityContent(
        text="see attached",
        image_attachments=[{"contentType": "image/png"}],
        file_attachments=[{"name": "report.pdf"}],
    )
    cfg = _make_config()

    run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert run_kwargs == {}
    assert skipped == ["image", "report.pdf"]


@pytest.mark.asyncio
async def test_download_attachments_image_sent_as_a_file_is_still_an_image():
    """Teams classifies a pasted image as image/* but an uploaded one as a file
    attachment, so the paperclip path arrives here rather than in image_attachments.
    File's allowlist carries no image types, so testing it against that list drops
    the photo and tells the user it could not be read. It is an image either way."""
    parsed = ActivityContent(
        text="what is in this",
        image_attachments=[],
        file_attachments=[
            {
                "contentType": "application/vnd.microsoft.teams.file.download.info",
                "contentUrl": "https://ex/photo",
                "name": "photo.png",
            }
        ],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        return b"pngbytes", "image/png"

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert skipped == []
    assert "files" not in run_kwargs
    assert len(run_kwargs["images"]) == 1
    assert run_kwargs["images"][0].content == b"pngbytes"
    assert run_kwargs["images"][0].mime_type == "image/png"


@pytest.mark.asyncio
async def test_download_attachments_resolves_supported_mime_from_filename():
    """A download that omits content-type must not cost the user a supported file:
    the type is resolved from the name, the way the model would have."""
    parsed = ActivityContent(
        text="see attached",
        image_attachments=[],
        file_attachments=[{"contentUrl": "https://ex/report", "name": "report.pdf"}],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        return b"pdfbytes", None

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert skipped == []
    assert run_kwargs["files"][0].mime_type == "application/pdf"


@pytest.mark.asyncio
async def test_download_attachments_prefers_content_download_url():
    """The pre-authorised link is content.downloadUrl; contentUrl is SharePoint."""
    parsed = ActivityContent(
        text="see attached",
        image_attachments=[],
        file_attachments=[
            {
                "contentType": "application/vnd.microsoft.teams.file.download.info",
                "name": "report.pdf",
                "contentUrl": "https://sharepoint.example/personal/report.pdf",
                "content": {"downloadUrl": "https://download.example/preauth/report.pdf", "uniqueId": "u1"},
            }
        ],
    )
    cfg = _make_config()
    requested = []

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        requested.append(url)
        return b"pdfbytes", "application/pdf"

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert requested == ["https://download.example/preauth/report.pdf"]
    assert skipped == []
    assert run_kwargs["files"][0].content == b"pdfbytes"


@pytest.mark.asyncio
async def test_download_attachments_falls_back_to_content_url():
    """Inline attachments without a content.downloadUrl still use contentUrl."""
    parsed = ActivityContent(
        text="hi",
        image_attachments=[],
        file_attachments=[{"contentUrl": "https://ex/plain.pdf", "name": "plain.pdf"}],
    )
    cfg = _make_config()
    requested = []

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        requested.append(url)
        return b"bytes", "application/pdf"

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        await download_attachments_async(parsed, cfg)

    assert requested == ["https://ex/plain.pdf"]


@pytest.mark.asyncio
async def test_download_attachments_supported_mime_is_preserved():
    """A type on the allowlist must survive unchanged — the guard must not blanket-None."""
    parsed = ActivityContent(
        text="hi",
        image_attachments=[],
        file_attachments=[{"contentUrl": "https://ex/f.pdf", "name": "f.pdf"}],
    )
    cfg = _make_config()

    async def fake_download(url, config, use_bot_token=False, **kwargs):
        return b"pdfbytes", "application/pdf"

    with patch("agno.os.interfaces.msteams.helpers._download_attachment", side_effect=fake_download):
        run_kwargs, skipped = await download_attachments_async(parsed, cfg)

    assert skipped == []
    assert run_kwargs["files"][0].mime_type == "application/pdf"
    assert run_kwargs["files"][0].filename == "f.pdf"


# === _clean_mention_text ===


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,download_url,authorized",
    [
        ("https://svc/file", None, True),
        ("https://other/file", None, False),
        ("https://svc/file", "https://svc/preauthorized", False),
    ],
)
async def test_attachment_token_only_for_verified_host(url, download_url, authorized):
    import httpx

    cfg = _make_config()
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, content=b"pdf", headers={"Content-Type": "application/pdf"})

    att = {"contentUrl": url, "name": "report.pdf"}
    if download_url:
        att["content"] = {"downloadUrl": download_url}
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with (
        patch("httpx.AsyncClient", return_value=client),
        patch(
            "agno.os.interfaces.msteams.helpers._get_bot_token", new_callable=AsyncMock, return_value="bot-token"
        ) as token,
    ):
        kwargs, skipped = await download_attachments_async(
            ActivityContent(text="hi", file_attachments=[att]), cfg, service_url="https://svc/"
        )
    assert not skipped
    assert kwargs["files"][0].content == b"pdf"
    assert (seen[0].headers.get("Authorization") == "Bearer bot-token") == authorized
    assert token.await_count == int(authorized)
    assert str(seen[0].url) == (download_url or url)


@pytest.mark.asyncio
@pytest.mark.parametrize("with_length", [False, True])
async def test_attachment_size_cap(with_length):
    import httpx

    chunks_read = []

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for data in [b"123", b"456", b"789"]:
                chunks_read.append(data)
                yield data

    headers = {"Content-Type": "application/pdf"}
    if with_length:
        headers["Content-Length"] = "9"
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Body(), headers=headers))
    )
    parsed = ActivityContent(text="still here", file_attachments=[{"name": "report.pdf", "contentUrl": "https://ex/f"}])
    with patch("httpx.AsyncClient", return_value=client):
        kwargs, skipped = await download_attachments_async(parsed, _make_config(), max_file_size=5)
    assert kwargs == {}
    assert skipped == ["report.pdf (too large)"]
    assert parsed.text == "still here"
    assert len(chunks_read) == (0 if with_length else 2)
    assert client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mime,name,field",
    [
        ("application/octet-stream", "photo.png", "images"),
        ("application/octet-stream", "report.pdf", "files"),
        ("application/zip", "archive.zip", None),
        ("application/x-zip-compressed", "archive.zip", None),
        ("application/x-zip", "archive.zip", None),
    ],
)
async def test_attachment_type_resolution(mime, name, field):
    parsed = ActivityContent(text="keep text", file_attachments=[{"name": name, "contentUrl": "https://ex/file"}])
    with patch(
        "agno.os.interfaces.msteams.helpers._download_attachment",
        new_callable=AsyncMock,
        return_value=(b"content", mime),
    ):
        kwargs, skipped = await download_attachments_async(parsed, _make_config())
    assert parsed.text == "keep text"
    if field:
        assert skipped == []
        assert len(kwargs[field]) == 1
        assert kwargs[field][0].mime_type != "application/octet-stream"
    else:
        assert kwargs == {}
        assert skipped == [name]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, None, "invalid-url"])
async def test_failed_download_logs_no_url_or_exception_text(status, caplog):
    import httpx

    url = "https://example.com/report.pdf?tempauth=SECRET123"

    def handle(request):
        if status == "invalid-url":
            raise httpx.InvalidURL(f"Invalid URL: {url}")
        if status:
            return httpx.Response(status)
        raise httpx.ReadError(f"Failed at {url}", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with patch("httpx.AsyncClient", return_value=client):
        kwargs, skipped = await download_attachments_async(
            ActivityContent(text="hi", file_attachments=[{"name": "report.pdf", "contentUrl": url}]), _make_config()
        )
    assert kwargs == {}
    assert skipped == ["report.pdf"]
    assert "report.pdf" in caplog.text
    error_class = "InvalidURL" if status == "invalid-url" else "HTTPStatusError" if status else "ReadError"
    assert error_class in caplog.text
    if status == 403:
        assert "403" in caplog.text
    assert url not in caplog.text
    assert "SECRET123" not in caplog.text


def test_clean_mention_returns_empty_for_empty_input():
    assert _clean_mention_text("") == ""


def test_clean_mention_returns_empty_for_none_input():
    # activity.get("text") can be None if the field is absent
    assert _clean_mention_text(None) == ""  # type: ignore[arg-type]


def test_clean_mention_preserves_other_mentions():
    text = "<at>Bot</at> hi <at>User</at> there"
    assert _clean_mention_text(text) == "@Bot hi @User there"


@pytest.mark.parametrize("mentioned_id,expected", [("bot", "Display"), ("other", "@Bot")])
def test_mention_only_is_a_message(mentioned_id, expected):
    activity = {
        "type": "message",
        "text": " <at>Bot</at> ",
        "recipient": {"id": "bot", "name": "Display"},
        "entities": [{"type": "mention", "text": "<at>Bot</at>", "mentioned": {"id": mentioned_id}}],
    }
    assert extract_activity_content(activity).text == expected


def test_clean_mention_case_insensitive():
    text = "<AT>Bot</AT> hello"
    assert _clean_mention_text(text) == "@Bot hello"


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


# === MSTeamsConfig tenant env override ===


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
        cfg = MSTeamsConfig.init(tenant_id="arg-tenant")
    assert cfg.tenant_id == "arg-tenant"
