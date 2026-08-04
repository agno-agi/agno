"""Unit tests for ScavioTools class."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.tools.scavio import ScavioTools

TEST_API_KEY = os.environ.get("SCAVIO_API_KEY", "test_api_key")


@pytest.fixture
def mock_scavio_client():
    """Create a mock ScavioClient instance."""
    with patch("agno.tools.scavio.ScavioClient") as mock_client_cls:
        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        return mock_client


@pytest.fixture
def scavio_tools(mock_scavio_client):
    """Create a ScavioTools instance with mocked dependencies."""
    with patch.dict("os.environ", {"SCAVIO_API_KEY": TEST_API_KEY}):
        tools = ScavioTools()
        tools.client = mock_scavio_client
        return tools


def _tool_names(tools: ScavioTools) -> list:
    return [tool.__name__ for tool in tools.tools]


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_with_env_var():
    """Test initialization reads the API key from the environment."""
    with patch("agno.tools.scavio.ScavioClient") as mock_client_cls:
        with patch.dict("os.environ", {"SCAVIO_API_KEY": TEST_API_KEY}, clear=True):
            tools = ScavioTools()
            assert tools.api_key == TEST_API_KEY
            assert tools.client is not None
            mock_client_cls.assert_called_once_with(api_key=TEST_API_KEY)


def test_init_with_param():
    """Test initialization with an explicit API key."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="param_api_key")
        assert tools.api_key == "param_api_key"


def test_all_flag_registers_every_tool():
    """all=True should register all 97 provider tools.

    Toolkit keeps `tools` exactly as passed, so the count is the number of
    registrations in __init__. Per provider that is 14 google + 3 amazon +
    2 walmart + 15 youtube + 12 reddit + 11 tiktok + 12 instagram + 11 x +
    9 linkedin + 8 tiktok_shop = 97, one tool for every live billable Scavio
    endpoint except /youtube/metadata, which is a deprecated alias of
    /youtube/video and is reached through youtube_video.
    """
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(all=True)
        assert len(tools.tools) == 97


def test_default_registers_every_provider():
    """By default every provider is enabled."""
    with patch("agno.tools.scavio.ScavioClient"):
        names = _tool_names(ScavioTools())
        assert "google_search" in names
        assert "google_maps_search" in names
        assert "google_trends" in names
        assert "amazon_product" in names
        assert "walmart_product" in names
        assert "youtube_video" in names
        assert "youtube_transcript" in names
        assert "reddit_post" in names
        assert "reddit_subreddit_posts" in names
        assert "tiktok_profile" in names
        assert "instagram_profile" in names
        assert "x_search" in names
        assert "linkedin_person" in names
        assert "tiktok_shop_search" in names


def test_enable_flags_select_subset():
    """Disabling providers removes their tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
            enable_tiktok_shop=False,
        )
        names = _tool_names(tools)
        assert all(name.startswith("google_") for name in names)
        assert len(names) == 14


def test_google_flag_registers_every_vertical():
    """enable_google registers the SERP tool and all thirteen Google verticals."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
            enable_tiktok_shop=False,
        )
        assert _tool_names(tools) == [
            "google_search",
            "google_ai_mode",
            "google_maps_search",
            "google_maps_place",
            "google_maps_reviews",
            "google_shopping",
            "google_shopping_product",
            "google_shopping_stores",
            "google_flights",
            "google_hotels",
            "google_hotels_detail",
            "google_news",
            "google_trends",
            "google_trending",
        ]


def test_youtube_flag_registers_all_youtube_tools():
    """enable_youtube registers fifteen tools and no deprecated metadata alias."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=True,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
            enable_tiktok_shop=False,
        )
        names = _tool_names(tools)
        assert all(name.startswith("youtube_") for name in names)
        assert len(names) == 15
        assert "youtube_metadata" not in names
        for expected in (
            "youtube_shorts",
            "youtube_suggestions",
            "youtube_comment_replies",
            "youtube_related",
            "youtube_channel_search",
            "youtube_channel_videos",
            "youtube_channel_shorts",
            "youtube_channel_community",
            "youtube_channel_resolve",
        ):
            assert expected in names


def test_x_flag_registers_x_tools():
    """enable_x registers exactly the eleven X tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=True,
            enable_linkedin=False,
            enable_tiktok_shop=False,
        )
        names = _tool_names(tools)
        assert all(name.startswith("x_") for name in names)
        assert len(names) == 11


def test_linkedin_flag_registers_linkedin_tools():
    """enable_linkedin registers exactly the nine live LinkedIn tools.

    Was fourteen. The provider retired the datasets behind person_contact,
    company_people, company_jobs, search_people and search_posts, and an agent
    tool that can only fail is worse than an absent one, so they were removed.
    """
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=True,
            enable_tiktok_shop=False,
        )
        names = _tool_names(tools)
        assert all(name.startswith("linkedin_") for name in names)
        assert len(names) == 9


def test_reddit_flag_registers_all_reddit_tools():
    """enable_reddit registers the twelve upgraded Reddit tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=True,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
            enable_tiktok_shop=False,
        )
        names = _tool_names(tools)
        assert all(name.startswith("reddit_") for name in names)
        assert len(names) == 12
        # existing surface preserved
        assert "reddit_search" in names
        assert "reddit_post" in names


def test_tiktok_shop_flag_registers_tiktok_shop_tools():
    """enable_tiktok_shop registers exactly the eight TikTok Shop tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=False,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
            enable_tiktok_shop=True,
        )
        names = _tool_names(tools)
        assert all(name.startswith("tiktok_shop_") for name in names)
        assert len(names) == 8


def test_amazon_flag_registers_amazon_tools():
    """enable_amazon registers exactly the three Amazon tools.

    Was two. amazon_offers was added when Amazon moved to the provider that
    exposes the offer listing.
    """
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=False,
            enable_amazon=True,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
            enable_x=False,
            enable_linkedin=False,
            enable_tiktok_shop=False,
        )
        names = _tool_names(tools)
        assert names == ["amazon_search", "amazon_product", "amazon_offers"]


def test_tool_names_are_unique():
    """Provider-prefixed names must not collide (tiktok/instagram both have search_users)."""
    with patch("agno.tools.scavio.ScavioClient"):
        names = _tool_names(ScavioTools(all=True))
        assert len(names) == len(set(names))


# ============================================================================
# CALL TESTS
# ============================================================================


def test_google_search_returns_json(scavio_tools, mock_scavio_client):
    """google_search returns the SDK response as a JSON string."""
    mock_scavio_client.google.search.return_value = {"organic_results": [{"title": "Result 1"}]}

    result = scavio_tools.google_search("agno framework")

    parsed = json.loads(result)
    assert parsed["organic_results"][0]["title"] == "Result 1"
    mock_scavio_client.google.search.assert_called_once()
    # query is passed positionally; optional params are forwarded as keywords
    call = mock_scavio_client.google.search.call_args
    assert call.args[0] == "agno framework"


def test_google_search_uses_v2_param_names(scavio_tools, mock_scavio_client):
    """Google is the v2 API: gl/hl/start, and start is an offset, not a page.

    The v1 endpoint retired on 2026-08-04 and answers 410, so country_code,
    language, page, search_type and light_request no longer exist anywhere.
    """
    mock_scavio_client.google.search.return_value = {"organic_results": []}

    scavio_tools.google_search("agno", gl="gb", hl="en", start=20, google_domain="google.co.uk")

    call = mock_scavio_client.google.search.call_args
    assert call.kwargs["gl"] == "gb"
    assert call.kwargs["hl"] == "en"
    assert call.kwargs["start"] == 20
    assert call.kwargs["google_domain"] == "google.co.uk"
    for gone in ("country_code", "language", "page", "search_type", "light_request"):
        assert gone not in call.kwargs


def test_google_v1_params_are_not_accepted(scavio_tools):
    """The retired v1 parameter names must not survive as aliases."""
    for gone in ("country_code", "language", "page", "search_type", "light_request"):
        with pytest.raises(TypeError):
            scavio_tools.google_search("agno", **{gone: "x"})


def test_google_verticals_reach_their_own_sdk_methods(scavio_tools, mock_scavio_client):
    """Each vertical calls its own namespace method with the documented params."""
    mock_scavio_client.google.maps_search.return_value = {"local_results": []}
    mock_scavio_client.google.flights.return_value = {"best_flights": []}
    mock_scavio_client.google.trending.return_value = {"trends": []}

    scavio_tools.google_maps_search("coffee", ll="@40.7128,-74.0060,13z", start=20)
    scavio_tools.google_flights("JFK", "LHR", "2026-09-01", type=2)
    scavio_tools.google_trending("US", hours=24)

    maps = mock_scavio_client.google.maps_search.call_args
    assert maps.args[0] == "coffee"
    assert maps.kwargs["ll"] == "@40.7128,-74.0060,13z"
    assert maps.kwargs["start"] == 20

    flights = mock_scavio_client.google.flights.call_args
    assert flights.args == ("JFK", "LHR", "2026-09-01")
    assert flights.kwargs["type"] == 2

    assert mock_scavio_client.google.trending.call_args.args[0] == "US"


def test_youtube_comment_replies_requires_a_reply_cursor(scavio_tools, mock_scavio_client):
    """Replies cannot be fetched from a video id alone: reply_cursor is required."""
    mock_scavio_client.youtube.comment_replies.return_value = {"replies": []}

    scavio_tools.youtube_comment_replies("dQw4w9WgXcQ", "Eg0SC2RRdzR3OVdnY1E")

    call = mock_scavio_client.youtube.comment_replies.call_args
    assert call.args == ("dQw4w9WgXcQ", "Eg0SC2RRdzR3OVdnY1E")
    assert call.kwargs["cursor"] is None

    with pytest.raises(TypeError):
        scavio_tools.youtube_comment_replies("dQw4w9WgXcQ")


def test_youtube_metadata_alias_is_gone(scavio_tools):
    """The deprecated /youtube/metadata alias is not exposed as its own tool."""
    assert not hasattr(scavio_tools, "youtube_metadata")


def test_reddit_search_takes_only_query_and_cursor(scavio_tools, mock_scavio_client):
    """Reddit search has no type and no sort: the API strips both silently.

    A dead control is worse than a missing one - an agent would plan a sort it
    never gets - so they were removed rather than passed through.
    """
    mock_scavio_client.reddit.search.return_value = {"results": [], "has_more": False}

    scavio_tools.reddit_search("serpapi alternative", cursor="c1")

    call = mock_scavio_client.reddit.search.call_args
    assert call.args[0] == "serpapi alternative"
    assert call.kwargs == {"cursor": "c1"}

    for gone in ("type", "sort"):
        with pytest.raises(TypeError):
            scavio_tools.reddit_search("x", **{gone: "y"})


def test_reddit_post_accepts_a_post_id(scavio_tools, mock_scavio_client):
    """reddit_post takes a url or a post id and returns the post alone, no comments."""
    mock_scavio_client.reddit.post.return_value = {"post_id": "t3_1v6ngaf", "title": "Hello"}

    result = scavio_tools.reddit_post(post_id="t3_1v6ngaf")

    assert json.loads(result)["post_id"] == "t3_1v6ngaf"
    call = mock_scavio_client.reddit.post.call_args
    assert call.args[0] is None
    assert call.kwargs["post_id"] == "t3_1v6ngaf"


def test_amazon_product_passes_asin(scavio_tools, mock_scavio_client):
    """amazon_product forwards the ASIN to the SDK."""
    mock_scavio_client.amazon.product.return_value = {"asin": "B000"}

    result = scavio_tools.amazon_product("B000")

    assert json.loads(result)["asin"] == "B000"
    assert mock_scavio_client.amazon.product.call_args.args[0] == "B000"


def test_amazon_product_forwards_country(scavio_tools, mock_scavio_client):
    """Locale is a two-letter marketplace country code, not a domain suffix."""
    mock_scavio_client.amazon.product.return_value = {"asin": "B000"}

    scavio_tools.amazon_product("B000", country="gb")

    assert mock_scavio_client.amazon.product.call_args.kwargs["country"] == "gb"


def test_amazon_search_forwards_country_and_page(scavio_tools, mock_scavio_client):
    """amazon_search passes the query positionally and country/page as keywords."""
    mock_scavio_client.amazon.search.return_value = {"count": 0, "products": []}

    result = scavio_tools.amazon_search("wireless headphones", country="de", page=2)

    assert json.loads(result)["products"] == []
    call = mock_scavio_client.amazon.search.call_args
    assert call.args[0] == "wireless headphones"
    assert call.kwargs["country"] == "de"
    assert call.kwargs["page"] == 2


def test_amazon_search_page_defaults_to_none(scavio_tools, mock_scavio_client):
    """An unset page reaches the SDK as None, which the SDK drops from the body.

    The API rejects an explicit null page, so nothing may put one on the wire.
    The SDK owns that: page is a named parameter there and build_body drops None
    values, so the toolkit just forwards it.
    """
    mock_scavio_client.amazon.search.return_value = {"count": 0, "products": []}

    scavio_tools.amazon_search("wireless headphones")

    assert mock_scavio_client.amazon.search.call_args.kwargs["page"] is None


def test_amazon_offers_forwards_asin_and_country(scavio_tools, mock_scavio_client):
    """amazon_offers passes the ASIN positionally and the country as a keyword."""
    mock_scavio_client.amazon.offers.return_value = {
        "asin": "B000",
        "count": 1,
        "offers": [{"seller_name": "Amazon.com", "is_buy_box_winner": True, "price": 29.99}],
    }

    result = scavio_tools.amazon_offers("B000", country="us")

    parsed = json.loads(result)
    assert parsed["offers"][0]["is_buy_box_winner"] is True
    call = mock_scavio_client.amazon.offers.call_args
    assert call.args[0] == "B000"
    assert call.kwargs["country"] == "us"


def test_amazon_retired_params_are_not_accepted(scavio_tools):
    """The nine retired params, plus the two deprecated aliases, must all be gone.

    Nine have no upstream equivalent at all (sort_by, pages, category_id,
    merchant_id, language, currency, device, zip_code, autoselect_variant); domain
    and start_page still work on the wire but are superseded by country and page.
    sort_by is the one that matters: the marketplace accepts every sort value and
    returns the identical unordered result set. Keeping it in the signature would
    let an agent plan "get the cheapest" as a single call that quietly lies.
    """
    retired = (
        "sort_by",
        "pages",
        "category_id",
        "merchant_id",
        "language",
        "currency",
        "device",
        "zip_code",
        "autoselect_variant",
        "domain",
        "start_page",
    )
    for tool, ref in (
        (scavio_tools.amazon_search, "headphones"),
        (scavio_tools.amazon_product, "B000"),
        (scavio_tools.amazon_offers, "B000"),
    ):
        for gone in retired:
            with pytest.raises(TypeError):
                tool(ref, **{gone: "x"})


def test_error_is_returned_as_json(scavio_tools, mock_scavio_client):
    """Exceptions from the SDK are caught and returned as an error payload."""
    mock_scavio_client.reddit.search.side_effect = Exception("boom")

    result = scavio_tools.reddit_search("test")

    parsed = json.loads(result)
    assert parsed["error"] == "boom"


def test_x_search_forwards_params(scavio_tools, mock_scavio_client):
    """x_search passes the query positionally and options as keywords."""
    mock_scavio_client.x.search.return_value = {"timeline": []}

    result = scavio_tools.x_search("ai agents", search_type="Latest", cursor="c1")

    assert json.loads(result) == {"timeline": []}
    call = mock_scavio_client.x.search.call_args
    assert call.args[0] == "ai agents"
    assert call.kwargs["search_type"] == "Latest"
    assert call.kwargs["cursor"] == "c1"


def test_reddit_subreddit_posts_forwards_params(scavio_tools, mock_scavio_client):
    """reddit_subreddit_posts forwards the subreddit and sort/cursor."""
    mock_scavio_client.reddit.subreddit_posts.return_value = {"posts": []}

    result = scavio_tools.reddit_subreddit_posts("programming", sort="NEW", cursor="c2")

    assert json.loads(result) == {"posts": []}
    call = mock_scavio_client.reddit.subreddit_posts.call_args
    assert call.args[0] == "programming"
    assert call.kwargs["sort"] == "NEW"


def test_linkedin_person_forwards_username(scavio_tools, mock_scavio_client):
    """linkedin_person forwards the username to the SDK as a keyword."""
    mock_scavio_client.linkedin.person.return_value = {"full_name": "Ada Lovelace"}

    result = scavio_tools.linkedin_person("adalovelace")

    assert json.loads(result)["full_name"] == "Ada Lovelace"
    assert mock_scavio_client.linkedin.person.call_args.kwargs["username"] == "adalovelace"


def test_linkedin_person_accepts_a_url(scavio_tools, mock_scavio_client):
    """Every LinkedIn reference also accepts a full LinkedIn URL."""
    mock_scavio_client.linkedin.person.return_value = {"full_name": "Ada Lovelace"}

    scavio_tools.linkedin_person(url="https://www.linkedin.com/in/adalovelace/")

    assert mock_scavio_client.linkedin.person.call_args.kwargs["url"] == "https://www.linkedin.com/in/adalovelace/"


def test_linkedin_person_posts_forwards_type_and_cursor(scavio_tools, mock_scavio_client):
    """The member feed gained a type selector and cursor paging.

    type picks the member's own posts, the posts they commented on, or the posts
    they reacted to. cursor is the previous response's next_cursor, echoed back
    verbatim - it is opaque and the toolkit must not touch it.
    """
    mock_scavio_client.linkedin.person_posts.return_value = {"data": [], "has_more": False}

    scavio_tools.linkedin_person_posts("williamhgates", type="reactions", cursor="eyJzdGFydCI6NTB9")

    call = mock_scavio_client.linkedin.person_posts.call_args
    assert call.kwargs["username"] == "williamhgates"
    assert call.kwargs["type"] == "reactions"
    assert call.kwargs["cursor"] == "eyJzdGFydCI6NTB9"


def test_linkedin_person_posts_defaults_send_no_paging(scavio_tools, mock_scavio_client):
    """Page one asks for no type and no cursor; both reach the SDK as None."""
    mock_scavio_client.linkedin.person_posts.return_value = {"data": []}

    scavio_tools.linkedin_person_posts("williamhgates")

    call = mock_scavio_client.linkedin.person_posts.call_args
    assert call.kwargs["type"] is None
    assert call.kwargs["cursor"] is None


def test_linkedin_company_posts_forwards_cursor(scavio_tools, mock_scavio_client):
    """The company feed paginates on the same opaque cursor."""
    mock_scavio_client.linkedin.company_posts.return_value = {"data": [], "has_more": True}

    scavio_tools.linkedin_company_posts("microsoft", cursor="eyJzdGFydCI6NTB9")

    call = mock_scavio_client.linkedin.company_posts.call_args
    assert call.kwargs["company"] == "microsoft"
    assert call.kwargs["cursor"] == "eyJzdGFydCI6NTB9"


def test_linkedin_search_jobs_forwards_location_and_cursor(scavio_tools, mock_scavio_client):
    """Job search takes the keyword positionally, location and cursor as keywords."""
    mock_scavio_client.linkedin.search_jobs.return_value = {"data": [], "count": 0}

    scavio_tools.linkedin_search_jobs("software engineer", location="United States", cursor="eyJzdGFydCI6MjV9")

    call = mock_scavio_client.linkedin.search_jobs.call_args
    assert call.args[0] == "software engineer"
    assert call.kwargs["location"] == "United States"
    assert call.kwargs["cursor"] == "eyJzdGFydCI6MjV9"


def test_linkedin_post_comments_pages_by_number(scavio_tools, mock_scavio_client):
    """Comments are the one LinkedIn endpoint paged by number rather than cursor.

    Page size varies upstream, so the toolkit must not be given a cursor here and
    must forward the page through unchanged.
    """
    mock_scavio_client.linkedin.post_comments.return_value = {"data": [], "page": 3}

    scavio_tools.linkedin_post_comments("7488618410256523265", page=3)

    call = mock_scavio_client.linkedin.post_comments.call_args
    assert call.kwargs["post_id"] == "7488618410256523265"
    assert call.kwargs["page"] == 3
    assert "cursor" not in call.kwargs


def test_linkedin_retired_tools_are_not_registered(scavio_tools):
    """The five retired endpoints must not appear as agent tools."""
    names = _tool_names(scavio_tools)
    for gone in (
        "linkedin_person_contact",
        "linkedin_company_people",
        "linkedin_company_jobs",
        "linkedin_search_people",
        "linkedin_search_posts",
    ):
        assert gone not in names


class _NotFoundError(Exception):
    """Stand-in for the SDK's NotFoundError, which carries status_code."""

    def __init__(self, message):
        super().__init__(message)
        self.status_code = 404


def test_tiktok_shop_product_forwards_region(scavio_tools, mock_scavio_client):
    """tiktok_shop_product passes the product id positionally and the region as a keyword."""
    mock_scavio_client.tiktok_shop.product.return_value = {"data": {"product_id": "1732293553906094315"}}

    result = scavio_tools.tiktok_shop_product("1732293553906094315", region="GB")

    assert json.loads(result)["data"]["product_id"] == "1732293553906094315"
    call = mock_scavio_client.tiktok_shop.product.call_args
    assert call.args[0] == "1732293553906094315"
    assert call.kwargs["region"] == "GB"


def test_tiktok_shop_product_404_is_a_normal_not_found(scavio_tools, mock_scavio_client):
    """A 404 is a determinate answer here, not a failure the agent should retry."""
    mock_scavio_client.tiktok_shop.product.side_effect = _NotFoundError("Product not found in this region.")

    parsed = json.loads(scavio_tools.tiktok_shop_product("1732293553906094315"))

    assert parsed["not_found"] is True
    assert parsed["data"] is None
    assert "error" not in parsed
    assert "44%" in parsed["guidance"]


def test_tiktok_shop_resolve_404_is_a_normal_not_found(scavio_tools, mock_scavio_client):
    """The other TikTok Shop lookups share the not-found treatment."""
    mock_scavio_client.tiktok_shop.resolve.side_effect = _NotFoundError("Could not resolve this link.")

    parsed = json.loads(scavio_tools.tiktok_shop_resolve("https://vt.tiktok.com/ZT2AHoGsE/"))

    assert parsed["not_found"] is True
    assert parsed["data"] is None


def test_tiktok_shop_product_other_errors_stay_errors(scavio_tools, mock_scavio_client):
    """A non-404 failure is a real failure and must still surface as an error."""
    mock_scavio_client.tiktok_shop.product.side_effect = RuntimeError("boom")

    parsed = json.loads(scavio_tools.tiktok_shop_product("1732293553906094315"))

    assert parsed == {"error": "boom"}


def test_non_shop_endpoints_keep_error_behaviour(scavio_tools, mock_scavio_client):
    """A 404 outside TikTok Shop is untouched: it still comes back as an error."""
    mock_scavio_client.google.search.side_effect = _NotFoundError("nope")

    parsed = json.loads(scavio_tools.google_search("test"))

    assert parsed == {"error": "nope"}


def test_tiktok_shop_product_reviews_forwards_filters(scavio_tools, mock_scavio_client):
    """tiktok_shop_product_reviews forwards paging, sort, and filter options."""
    mock_scavio_client.tiktok_shop.product_reviews.return_value = {"reviews": []}

    result = scavio_tools.tiktok_shop_product_reviews(
        "1732293553906094315",
        page=2,
        page_size=200,
        sort="recent",
        rating=5,
        has_media=True,
    )

    assert json.loads(result) == {"reviews": []}
    call = mock_scavio_client.tiktok_shop.product_reviews.call_args
    assert call.args[0] == "1732293553906094315"
    assert call.kwargs["page"] == 2
    assert call.kwargs["page_size"] == 200
    assert call.kwargs["sort"] == "recent"
    assert call.kwargs["rating"] == 5
    assert call.kwargs["has_media"] is True


def test_tiktok_shop_categories_takes_no_params(scavio_tools, mock_scavio_client):
    """tiktok_shop_categories calls the SDK with no arguments."""
    mock_scavio_client.tiktok_shop.categories.return_value = {"total_categories": 240}

    result = scavio_tools.tiktok_shop_categories()

    assert json.loads(result)["total_categories"] == 240
    call = mock_scavio_client.tiktok_shop.categories.call_args
    assert call.args == ()
    assert call.kwargs == {}
