import json
from os import getenv
from typing import Any, Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from scavio import ScavioClient
except ImportError:
    raise ImportError("`scavio` not installed. Please install using `pip install scavio`")


# The facts every TikTok Shop caller has to know. Repeated verbatim in the tool
# docstrings and returned as guidance on a not-found result, so an agent reading
# only the tool manifest still sees them.
TIKTOK_SHOP_PRODUCT_COVERAGE_NOTE = (
    "Only about 44% of the product ids returned by tiktok_shop_search resolve on "
    "tiktok_shop_product. Upstream has no detail data for the rest, so a not-found "
    "result is a normal outcome rather than an error: skip that product instead of "
    "retrying. Search is a listing source, not the first leg of a reliable "
    "search-then-detail pipeline."
)
TIKTOK_SHOP_PRODUCT_PRICE_NOTE = (
    "tiktok_shop_product does NOT return a price -- upstream masks it on the product "
    "page, so price.current and price.original come back null. Exact prices are "
    "returned by tiktok_shop_search, tiktok_shop_shop_products and "
    "tiktok_shop_category_products; read prices from those."
)
TIKTOK_SHOP_REVIEWS_FALLBACK_NOTE = (
    "tiktok_shop_product_reviews often still answers for an id tiktok_shop_product "
    "cannot resolve: measured on 8 such ids, 8 of 8 returned a successful response "
    "and 7 of 8 carried at least one review. That is a small sample, not a "
    "guarantee, but reviews are worth one call before giving up on a product."
)


class ScavioTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_google: bool = True,
        enable_amazon: bool = True,
        enable_walmart: bool = True,
        enable_youtube: bool = True,
        enable_reddit: bool = True,
        enable_tiktok: bool = True,
        enable_instagram: bool = True,
        enable_x: bool = True,
        enable_linkedin: bool = True,
        enable_tiktok_shop: bool = True,
        enable_threads: bool = False,
        enable_kuaishou: bool = False,
        enable_ebay: bool = False,
        enable_target: bool = False,
        enable_home_depot: bool = False,
        enable_zillow: bool = False,
        enable_booking: bool = False,
        enable_tripadvisor: bool = False,
        enable_indeed: bool = False,
        enable_airbnb: bool = False,
        enable_glassdoor: bool = False,
        enable_yelp: bool = False,
        enable_app_store: bool = False,
        enable_google_play: bool = False,
        enable_sec: bool = False,
        enable_redfin: bool = False,
        enable_companies_house: bool = False,
        enable_g2: bool = False,
        enable_capterra: bool = False,
        enable_google_ads: bool = False,
        enable_meta_ads: bool = False,
        enable_extract: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """Initialize ScavioTools, a unified search toolkit for AI agents.

        Scavio is a single Search API over 31 sources - Google, YouTube, Amazon, Walmart,
        Reddit, TikTok, TikTok Shop, Instagram, X, LinkedIn, Threads, Kuaishou, eBay,
        Target, Home Depot, Zillow, Redfin, Booking.com, Airbnb, TripAdvisor, Yelp,
        Indeed, Glassdoor, the App Store, Google Play, SEC EDGAR, Companies House, G2,
        Capterra, Google Ads Transparency and the Meta Ad Library - plus an extract
        endpoint that reads any URL. The toolkit exposes 189 tools, one per live billable
        endpoint.

        Every provider is gated by an ``enable_*`` flag, because 189 tool definitions is
        far more than any one agent should be shown. The ten providers the toolkit
        already shipped stay on by default, so upgrading does not change an existing
        agent's manifest; the twenty-one added here, and ``extract``, are opt-in. Pass
        ``all=True`` to register every tool, or the Toolkit-level ``include_tools`` /
        ``exclude_tools`` to pick individual ones.

        Credits are charged per call and are not uniform. Most endpoints are 1 credit,
        but YouTube transcripts are 8, LinkedIn job detail is 30, most Instagram calls
        are 10, G2 is 5, and Kuaishou runs from 1 to 40 depending on the endpoint. Four
        surfaces are priced by the request body rather than by the route: Walmart (by
        ``domain``), Threads (by whether you address a user by id or by handle), Kuaishou
        (per endpoint) and extract (by ``mode``). Each tool docstring states its own cost.

        Args:
            api_key: Scavio API key. If not provided, the ``SCAVIO_API_KEY`` env var is used.
            enable_google: Register the 14 Google tools: web search, AI Mode, Maps, Shopping,
                Flights, Hotels, News and Trends. Defaults to True.
            enable_amazon: Register the 4 Amazon tools: search, product, offer listing and the
                free marketplace-options lookup. Defaults to True.
            enable_walmart: Register the 7 Walmart tools: search, product, reviews, category,
                offers, seller and seller catalog. Defaults to True.
            enable_youtube: Register the 15 YouTube tools: search, Shorts, suggestions, video,
                comments, transcript, related, channel and streams. Defaults to True.
            enable_reddit: Register the 12 Reddit tools: search, post, subreddit, user, popular
                and trending. Defaults to True.
            enable_tiktok: Register the 11 TikTok tools. Defaults to True.
            enable_instagram: Register the 12 Instagram tools. Defaults to True.
            enable_x: Register the 11 X tools: search, tweet, user and trending. Defaults to True.
            enable_linkedin: Register the 9 LinkedIn tools: person, company, search, job and post.
                Defaults to True.
            enable_tiktok_shop: Register the 8 TikTok Shop tools: search, product, review,
                category, shop and URL resolution. Defaults to True.
            enable_threads: Register the 6 Threads tools: profile, posts, replies, post, post
                comments and user search. Defaults to False.
            enable_kuaishou: Register the 14 Kuaishou tools: profile, posts, live, video,
                comments, batch, search and leaderboards. Defaults to False.
            enable_ebay: Register the 3 eBay tools: search (live or sold listings), listing detail
                and seller profile. Defaults to False.
            enable_target: Register the 4 Target tools: search, category, product and reviews.
                Defaults to False.
            enable_home_depot: Register the 3 Home Depot tools: search, product and reviews.
                Defaults to False.
            enable_zillow: Register the 3 Zillow tools: listing search, property detail and agent
                reviews. Defaults to False.
            enable_booking: Register the 3 Booking.com tools: property search, property detail and
                guest reviews. Defaults to False.
            enable_tripadvisor: Register the 4 TripAdvisor tools: location lookup, search, location
                detail and reviews. Defaults to False.
            enable_indeed: Register the 4 Indeed tools: job search, job detail, employer profile
                and employer reviews. Defaults to False.
            enable_airbnb: Register the 3 Airbnb tools: stay search, listing detail and reviews.
                Defaults to False.
            enable_glassdoor: Register the 4 Glassdoor tools: company lookup, employer profile,
                reviews and salaries. Defaults to False.
            enable_yelp: Register the 3 Yelp tools: business search, business detail and reviews.
                Defaults to False.
            enable_app_store: Register the 3 Apple App Store tools: search, app detail and reviews.
                Defaults to False.
            enable_google_play: Register the 3 Google Play tools: search, app detail and reviews.
                Defaults to False.
            enable_sec: Register the 6 SEC EDGAR tools: CIK lookup, filer profile, filings, XBRL
                concept, XBRL fact index and full-text search. Defaults to False.
            enable_redfin: Register the 3 Redfin tools: listing search, property detail and market
                stats. Defaults to False.
            enable_companies_house: Register the 4 UK Companies House tools: search, company,
                officers and filing history. Defaults to False.
            enable_g2: Register the 3 G2 tools: product search, product profile and reviews.
                Defaults to False.
            enable_capterra: Register the 3 Capterra tools: product search, product profile and
                reviews. Defaults to False.
            enable_google_ads: Register the 3 Google Ads Transparency tools: advertiser lookup, ad
                search and creative detail. Defaults to False.
            enable_meta_ads: Register the 3 Meta Ad Library tools: keyword search, advertiser ads
                and ad detail. Defaults to False.
            enable_extract: Register ``extract_url``, which reads any URL as HTML, Markdown or
                plain text. Defaults to False.
            all: Register every available tool, ignoring the individual flags. Defaults to False.
            **kwargs: Additional arguments passed to Toolkit.
        """
        self.api_key = api_key or getenv("SCAVIO_API_KEY")
        if not self.api_key:
            log_error("SCAVIO_API_KEY not provided")

        self.client: ScavioClient = ScavioClient(api_key=self.api_key)

        tools: List[Any] = []

        if all or enable_google:
            tools.append(self.google_search)
            tools.append(self.google_ai_mode)
            tools.append(self.google_maps_search)
            tools.append(self.google_maps_place)
            tools.append(self.google_maps_reviews)
            tools.append(self.google_shopping)
            tools.append(self.google_shopping_product)
            tools.append(self.google_shopping_stores)
            tools.append(self.google_flights)
            tools.append(self.google_hotels)
            tools.append(self.google_hotels_detail)
            tools.append(self.google_news)
            tools.append(self.google_trends)
            tools.append(self.google_trending)
        if all or enable_amazon:
            tools.append(self.amazon_search)
            tools.append(self.amazon_product)
            tools.append(self.amazon_offers)
            tools.append(self.amazon_options)
        if all or enable_walmart:
            tools.append(self.walmart_search)
            tools.append(self.walmart_product)
            tools.append(self.walmart_reviews)
            tools.append(self.walmart_category)
            tools.append(self.walmart_offers)
            tools.append(self.walmart_seller)
            tools.append(self.walmart_seller_products)
        if all or enable_youtube:
            tools.append(self.youtube_search)
            tools.append(self.youtube_shorts)
            tools.append(self.youtube_suggestions)
            tools.append(self.youtube_video)
            tools.append(self.youtube_comments)
            tools.append(self.youtube_comment_replies)
            tools.append(self.youtube_transcript)
            tools.append(self.youtube_related)
            tools.append(self.youtube_channel_search)
            tools.append(self.youtube_channel)
            tools.append(self.youtube_channel_videos)
            tools.append(self.youtube_channel_shorts)
            tools.append(self.youtube_channel_community)
            tools.append(self.youtube_channel_resolve)
            tools.append(self.youtube_streams)
        if all or enable_reddit:
            tools.append(self.reddit_search)
            tools.append(self.reddit_search_suggestions)
            tools.append(self.reddit_post)
            tools.append(self.reddit_post_comments)
            tools.append(self.reddit_comment_replies)
            tools.append(self.reddit_subreddit)
            tools.append(self.reddit_subreddit_posts)
            tools.append(self.reddit_user)
            tools.append(self.reddit_user_posts)
            tools.append(self.reddit_user_comments)
            tools.append(self.reddit_popular)
            tools.append(self.reddit_trending)
        if all or enable_tiktok:
            tools.append(self.tiktok_profile)
            tools.append(self.tiktok_user_posts)
            tools.append(self.tiktok_video)
            tools.append(self.tiktok_video_comments)
            tools.append(self.tiktok_comment_replies)
            tools.append(self.tiktok_search_videos)
            tools.append(self.tiktok_search_users)
            tools.append(self.tiktok_hashtag)
            tools.append(self.tiktok_hashtag_videos)
            tools.append(self.tiktok_user_followers)
            tools.append(self.tiktok_user_followings)
        if all or enable_instagram:
            tools.append(self.instagram_profile)
            tools.append(self.instagram_user_posts)
            tools.append(self.instagram_user_reels)
            tools.append(self.instagram_user_tagged)
            tools.append(self.instagram_user_stories)
            tools.append(self.instagram_post)
            tools.append(self.instagram_post_comments)
            tools.append(self.instagram_comment_replies)
            tools.append(self.instagram_search_users)
            tools.append(self.instagram_search_hashtags)
            tools.append(self.instagram_user_followers)
            tools.append(self.instagram_user_followings)
        if all or enable_x:
            tools.append(self.x_search)
            tools.append(self.x_tweet)
            tools.append(self.x_tweet_comments)
            tools.append(self.x_tweet_retweeters)
            tools.append(self.x_user)
            tools.append(self.x_user_tweets)
            tools.append(self.x_user_replies)
            tools.append(self.x_user_media)
            tools.append(self.x_user_followers)
            tools.append(self.x_user_followings)
            tools.append(self.x_trending)
        if all or enable_linkedin:
            tools.append(self.linkedin_person)
            tools.append(self.linkedin_person_about)
            tools.append(self.linkedin_person_posts)
            tools.append(self.linkedin_company)
            tools.append(self.linkedin_company_posts)
            tools.append(self.linkedin_search_jobs)
            tools.append(self.linkedin_job)
            tools.append(self.linkedin_post)
            tools.append(self.linkedin_post_comments)
        if all or enable_tiktok_shop:
            tools.append(self.tiktok_shop_search)
            tools.append(self.tiktok_shop_search_suggestions)
            tools.append(self.tiktok_shop_product)
            tools.append(self.tiktok_shop_product_reviews)
            tools.append(self.tiktok_shop_categories)
            tools.append(self.tiktok_shop_category_products)
            tools.append(self.tiktok_shop_shop_products)
            tools.append(self.tiktok_shop_resolve)
        if all or enable_threads:
            tools.append(self.threads_profile)
            tools.append(self.threads_user_posts)
            tools.append(self.threads_user_replies)
            tools.append(self.threads_post)
            tools.append(self.threads_post_comments)
            tools.append(self.threads_search_users)
        if all or enable_kuaishou:
            tools.append(self.kuaishou_profile)
            tools.append(self.kuaishou_user_posts)
            tools.append(self.kuaishou_user_live)
            tools.append(self.kuaishou_user_resolve)
            tools.append(self.kuaishou_video)
            tools.append(self.kuaishou_video_comments)
            tools.append(self.kuaishou_comment_replies)
            tools.append(self.kuaishou_videos_batch)
            tools.append(self.kuaishou_search)
            tools.append(self.kuaishou_search_videos)
            tools.append(self.kuaishou_search_users)
            tools.append(self.kuaishou_search_live)
            tools.append(self.kuaishou_tag_feed)
            tools.append(self.kuaishou_trending)
        if all or enable_ebay:
            tools.append(self.ebay_search)
            tools.append(self.ebay_product)
            tools.append(self.ebay_seller)
        if all or enable_target:
            tools.append(self.target_search)
            tools.append(self.target_category)
            tools.append(self.target_product)
            tools.append(self.target_reviews)
        if all or enable_home_depot:
            tools.append(self.home_depot_search)
            tools.append(self.home_depot_product)
            tools.append(self.home_depot_reviews)
        if all or enable_zillow:
            tools.append(self.zillow_search)
            tools.append(self.zillow_property)
            tools.append(self.zillow_agent_reviews)
        if all or enable_booking:
            tools.append(self.booking_search)
            tools.append(self.booking_hotel)
            tools.append(self.booking_reviews)
        if all or enable_tripadvisor:
            tools.append(self.tripadvisor_locations)
            tools.append(self.tripadvisor_search)
            tools.append(self.tripadvisor_location)
            tools.append(self.tripadvisor_reviews)
        if all or enable_indeed:
            tools.append(self.indeed_search)
            tools.append(self.indeed_job)
            tools.append(self.indeed_company)
            tools.append(self.indeed_company_reviews)
        if all or enable_airbnb:
            tools.append(self.airbnb_search)
            tools.append(self.airbnb_listing)
            tools.append(self.airbnb_reviews)
        if all or enable_glassdoor:
            tools.append(self.glassdoor_companies)
            tools.append(self.glassdoor_company)
            tools.append(self.glassdoor_reviews)
            tools.append(self.glassdoor_salaries)
        if all or enable_yelp:
            tools.append(self.yelp_search)
            tools.append(self.yelp_business)
            tools.append(self.yelp_reviews)
        if all or enable_app_store:
            tools.append(self.app_store_search)
            tools.append(self.app_store_app)
            tools.append(self.app_store_reviews)
        if all or enable_google_play:
            tools.append(self.google_play_search)
            tools.append(self.google_play_app)
            tools.append(self.google_play_reviews)
        if all or enable_sec:
            tools.append(self.sec_lookup)
            tools.append(self.sec_company)
            tools.append(self.sec_filings)
            tools.append(self.sec_concept)
            tools.append(self.sec_facts)
            tools.append(self.sec_search)
        if all or enable_redfin:
            tools.append(self.redfin_search)
            tools.append(self.redfin_property)
            tools.append(self.redfin_market)
        if all or enable_companies_house:
            tools.append(self.companies_house_search)
            tools.append(self.companies_house_company)
            tools.append(self.companies_house_officers)
            tools.append(self.companies_house_filing_history)
        if all or enable_g2:
            tools.append(self.g2_search)
            tools.append(self.g2_product)
            tools.append(self.g2_reviews)
        if all or enable_capterra:
            tools.append(self.capterra_search)
            tools.append(self.capterra_product)
            tools.append(self.capterra_reviews)
        if all or enable_google_ads:
            tools.append(self.google_ads_advertisers)
            tools.append(self.google_ads_search)
            tools.append(self.google_ads_creative)
        if all or enable_meta_ads:
            tools.append(self.meta_ads_search)
            tools.append(self.meta_ads_advertiser)
            tools.append(self.meta_ads_ad)
        if all or enable_extract:
            tools.append(self.extract_url)

        super().__init__(name="scavio", tools=tools, **kwargs)

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        """Run a Scavio SDK call and return its JSON response as a string."""
        try:
            return json.dumps(fn(*args, **kwargs))
        except Exception as e:
            log_error(f"Scavio request failed: {e}")
            return json.dumps({"error": str(e)})

    @staticmethod
    def _is_not_found(err: Exception) -> bool:
        """Report whether ``err`` is an HTTP 404 from the Scavio API.

        The SDK raises ``NotFoundError`` with ``status_code`` set, so this reads
        the attribute rather than importing the exception class.
        """
        return getattr(err, "status_code", None) == 404

    def _call_shop(
        self,
        fn: Callable[..., Any],
        *args: Any,
        guidance: str = "",
        **kwargs: Any,
    ) -> str:
        """Run a TikTok Shop call, turning a 404 into a structured not-found result.

        TikTok Shop is the one product area where a 404 is a routine answer rather
        than a failure: the provider replied and there is genuinely no record. If
        that came back as ``{"error": ...}`` the agent would log a failure and
        retry a permanent condition, so the shop lookups return
        ``{"data": None, "not_found": True, ...}`` instead. Real failures (400,
        401, 402, 429, 5xx, transport errors) still go through ``_call``'s error
        path, and no other Scavio endpoint is affected.
        """
        try:
            return json.dumps(fn(*args, **kwargs))
        except Exception as e:
            if self._is_not_found(e):
                return json.dumps(
                    {
                        "data": None,
                        "not_found": True,
                        "reason": str(e),
                        "guidance": guidance,
                    }
                )
            log_error(f"Scavio request failed: {e}")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------ Google
    #
    # These fourteen tools run on the Google v2 API. The v1 endpoint they were
    # originally written against was retired on 2026-08-04 and now answers HTTP
    # 410, so its parameter names went with it: localization is `gl`/`hl`, paging
    # is a result offset (`start`), and there is no `light_request`,
    # `country_code`, `language`, `search_type` or `page` anywhere. Results carry
    # `organic_results[].link` and `.snippet`, not v1's `results[].url`/`.content`.
    # Every Google tool costs 1 credit.

    def google_search(
        self,
        query: str,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        start: Optional[int] = None,
        google_domain: Optional[str] = None,
        device: Optional[str] = None,
        location: Optional[str] = None,
        safe: Optional[str] = None,
        time_period: Optional[str] = None,
        nfpr: Optional[bool] = None,
    ) -> str:
        """Search Google for real-time organic web results.

        Args:
            query (str): The search query.
            gl (Optional[str]): Two-letter country code for the search, e.g. "us", "gb".
            hl (Optional[str]): UI language code, e.g. "en", "de".
            start (Optional[int]): Result offset, NOT a page number: 0 is page 1, 10 is page 2,
                20 is page 3, up to 990.
            google_domain (Optional[str]): Regional Google domain, e.g. "google.co.uk".
            device (Optional[str]): "desktop" or "mobile".
            location (Optional[str]): Canonical location name to search from, e.g. "Austin, Texas".
            safe (Optional[str]): "active" to turn SafeSearch on. No other value exists.
            time_period (Optional[str]): "last_hour", "last_day", "last_week", "last_month" or
                "last_year".
            nfpr (Optional[bool]): Disable auto-correction / spelling suggestions when True.

        Returns:
            str: JSON string with an ``organic_results`` list (each item has ``title``, ``link``
            and ``snippet``), plus ``top_stories``, ``related_questions``, ``related_searches``,
            ``knowledge_graph`` and ``ai_overview`` when Google returns them. Costs 1 credit.
        """
        return self._call(
            self.client.google.search,
            query,
            gl=gl,
            hl=hl,
            start=start,
            google_domain=google_domain,
            device=device,
            location=location,
            safe=safe,
            time_period=time_period,
            nfpr=nfpr,
        )

    def google_ai_mode(
        self,
        query: str,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        google_domain: Optional[str] = None,
        device: Optional[str] = None,
        location: Optional[str] = None,
    ) -> str:
        """Ask Google AI Mode and get its generated answer with the sources it cited.

        Use this when a question wants a synthesized answer rather than a ranked list of
        links; use google_search when you want the links themselves.

        Args:
            query (str): The question or prompt.
            gl (Optional[str]): Two-letter country code for the search, e.g. "us".
            hl (Optional[str]): UI language code, e.g. "en".
            google_domain (Optional[str]): Regional Google domain, e.g. "google.co.uk".
            device (Optional[str]): "desktop" or "mobile".
            location (Optional[str]): Canonical location name to search from.

        Returns:
            str: JSON string with ``text_blocks`` (the answer), ``references`` (the cited
            sources) and ``shopping_results`` when the question is commercial.
            Costs 1 credit.
        """
        return self._call(
            self.client.google.ai_mode,
            query,
            gl=gl,
            hl=hl,
            google_domain=google_domain,
            device=device,
            location=location,
        )

    def google_maps_search(
        self,
        query: str,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        ll: Optional[str] = None,
        start: Optional[int] = None,
        google_domain: Optional[str] = None,
    ) -> str:
        """Find local businesses on Google Maps.

        Maps localizes by map centre, not by country: pass ``ll`` when you know the area you
        want. If you only pass ``gl``, a major city in that country is used as the centre.

        Args:
            query (str): What to look for, e.g. "coffee shops" or "plumber".
            gl (Optional[str]): Two-letter country code, e.g. "us". Only sets a default map centre.
            hl (Optional[str]): UI language code, e.g. "en".
            ll (Optional[str]): Map centre as "@lat,lng,zoomz", e.g. "@40.7128,-74.0060,13z".
                This is what actually decides where results come from.
            start (Optional[int]): Result offset. Must be a multiple of 20 (0, 20, 40, ...).
            google_domain (Optional[str]): Regional Google domain.

        Returns:
            str: JSON string with a ``local_results`` list; each place carries a ``place_id``
            and a ``data_id`` for google_maps_place and google_maps_reviews. Costs 1 credit.
        """
        return self._call(
            self.client.google.maps_search,
            query,
            gl=gl,
            hl=hl,
            ll=ll,
            start=start,
            google_domain=google_domain,
        )

    def google_maps_place(
        self,
        place_id: Optional[str] = None,
        data_cid: Optional[str] = None,
    ) -> str:
        """Get the full Google Maps listing for one place.

        Args:
            place_id (Optional[str]): The place id from google_maps_search, e.g. "ChIJ...".
            data_cid (Optional[str]): The numeric CID, as an alternative to place_id.
                Provide one of the two.

        Returns:
            str: JSON string with ``place_results``: address, phone, website, hours, rating,
            review count, categories and coordinates. Costs 1 credit.
        """
        return self._call(self.client.google.maps_place, place_id=place_id, data_cid=data_cid)

    def google_maps_reviews(
        self,
        data_id: Optional[str] = None,
        place_id: Optional[str] = None,
        num: Optional[int] = None,
        next_page_token: Optional[str] = None,
        sort_by: Optional[str] = None,
        hl: Optional[str] = None,
        gl: Optional[str] = None,
    ) -> str:
        """Read the Google Maps reviews for a place.

        Args:
            data_id (Optional[str]): The place's data id, form "0xHEX:0xHEX".
            place_id (Optional[str]): The place id, as an alternative to data_id. Provide one.
            num (Optional[int]): Reviews per call, 1 to 20.
            next_page_token (Optional[str]): Cursor from a previous response, to read more.
            sort_by (Optional[str]): "relevance", "newest", "highest_rating" or "lowest_rating".
            hl (Optional[str]): UI language code.
            gl (Optional[str]): Two-letter country code.

        Returns:
            str: JSON string with ``reviews``, ``place_info``, ``topics`` and ``pagination``.
            There is no keyword filter on reviews - fetch and filter the text yourself.
            Costs 1 credit per call, so 20 reviews at a time.
        """
        return self._call(
            self.client.google.maps_reviews,
            data_id=data_id,
            place_id=place_id,
            num=num,
            next_page_token=next_page_token,
            sort_by=sort_by,
            hl=hl,
            gl=gl,
        )

    def google_shopping(
        self,
        query: str,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        start: Optional[int] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        sort_by: Optional[int] = None,
        free_shipping: Optional[bool] = None,
        on_sale: Optional[bool] = None,
        google_domain: Optional[str] = None,
        location: Optional[str] = None,
    ) -> str:
        """Search Google Shopping for products and prices across retailers.

        Args:
            query (str): The product search query.
            gl (Optional[str]): Two-letter country code, e.g. "us".
            hl (Optional[str]): UI language code.
            start (Optional[int]): Result offset; follow ``pagination.next`` from the response.
            min_price (Optional[int]): Lowest price to include.
            max_price (Optional[int]): Highest price to include.
            sort_by (Optional[int]): 0 relevance, 1 price ascending, 2 price descending.
                A number here, unlike google_shopping_product where it is a string.
            free_shipping (Optional[bool]): Only offers with free shipping.
            on_sale (Optional[bool]): Only discounted offers.
            google_domain (Optional[str]): Regional Google domain.
            location (Optional[str]): Canonical location name to price from.

        Returns:
            str: JSON string with ``shopping_results`` (title, price, seller, rating,
            ``catalog_id``), plus ``filters`` and ``pagination``. Pass a ``catalog_id`` to
            google_shopping_product for the full listing. Costs 1 credit.
        """
        return self._call(
            self.client.google.shopping,
            query,
            gl=gl,
            hl=hl,
            start=start,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
            free_shipping=free_shipping,
            on_sale=on_sale,
            google_domain=google_domain,
            location=location,
        )

    def google_shopping_product(
        self,
        catalog_id: Optional[str] = None,
        query: Optional[str] = None,
        product_id: Optional[str] = None,
        page_token: Optional[str] = None,
        device: Optional[str] = None,
        sort_by: Optional[str] = None,
        load_all_stores: Optional[bool] = None,
        more_stores: Optional[bool] = None,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        google_domain: Optional[str] = None,
    ) -> str:
        """Get one Google Shopping product with the stores selling it.

        Provide ``catalog_id`` together with ``query`` (the catalog id alone is rejected), or a
        ``product_id``, or a ``page_token`` taken from a previous response.

        Args:
            catalog_id (Optional[str]): Durable catalog id from google_shopping. Requires query.
            query (Optional[str]): The product query. Mandatory whenever catalog_id is set.
            product_id (Optional[str]): A product id, as an alternative to catalog_id.
            page_token (Optional[str]): An immersive product page token from a prior response.
            device (Optional[str]): "desktop", "mobile" or "tablet". The only Google tool that
                accepts "tablet".
            sort_by (Optional[str]): Store sort: "base_price", "total_price", "promotion" or
                "seller_rating". A string here, unlike google_shopping where it is a number.
            load_all_stores (Optional[bool]): Ask for every store rather than the first few.
            more_stores (Optional[bool]): Fetch additional stores.
            gl (Optional[str]): Two-letter country code.
            hl (Optional[str]): UI language code.
            google_domain (Optional[str]): Regional Google domain.

        Returns:
            str: JSON string with ``product_results``: specs, images, ratings and
            ``product_results.stores`` with per-seller prices. Paginate the store list with
            google_shopping_stores. Costs 1 credit.
        """
        return self._call(
            self.client.google.shopping_product,
            catalog_id=catalog_id,
            query=query,
            product_id=product_id,
            page_token=page_token,
            device=device,
            sort_by=sort_by,
            load_all_stores=load_all_stores,
            more_stores=more_stores,
            gl=gl,
            hl=hl,
            google_domain=google_domain,
        )

    def google_shopping_stores(self, catalog_id: str, next_page_token: str) -> str:
        """Get the next page of stores for a Google Shopping product.

        Args:
            catalog_id (str): The same catalog_id used on the google_shopping_product call.
            next_page_token (str): The continuation token from that response.

        Returns:
            str: JSON string with more ``product_results.stores``. Costs 1 credit.
        """
        return self._call(self.client.google.shopping_stores, catalog_id, next_page_token)

    def google_flights(
        self,
        departure_id: str,
        arrival_id: str,
        outbound_date: str,
        return_date: Optional[str] = None,
        type: Optional[int] = None,
        adults: Optional[int] = None,
        children: Optional[int] = None,
        infants_in_seat: Optional[int] = None,
        infants_on_lap: Optional[int] = None,
        travel_class: Optional[int] = None,
        stops: Optional[int] = None,
        sort_by: Optional[int] = None,
        include_airlines: Optional[str] = None,
        exclude_airlines: Optional[str] = None,
        currency: Optional[str] = None,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
    ) -> str:
        """Search Google Flights for fares between two airports.

        Args:
            departure_id (str): Origin IATA code, e.g. "JFK". Comma-separate several airports.
            arrival_id (str): Destination IATA code, e.g. "LHR".
            outbound_date (str): Departure date as "YYYY-MM-DD".
            return_date (Optional[str]): Return date as "YYYY-MM-DD". Required when type is 1.
            type (Optional[int]): 1 round trip, 2 one way, 3 multi-city.
            adults (Optional[int]): Adult passengers, 1 to 9.
            children (Optional[int]): Child passengers, 0 to 9.
            infants_in_seat (Optional[int]): Infants occupying a seat, 0 to 4.
            infants_on_lap (Optional[int]): Lap infants, 0 to 4.
            travel_class (Optional[int]): 1 economy, 2 premium economy, 3 business, 4 first.
            stops (Optional[int]): 0 any, 1 nonstop only, 2 one stop or fewer, 3 two or fewer.
            sort_by (Optional[int]): 1 top, 2 price, 3 departure, 4 arrival, 5 duration,
                6 emissions.
            include_airlines (Optional[str]): Comma-separated airline or alliance codes to keep.
            exclude_airlines (Optional[str]): Comma-separated airline or alliance codes to drop.
            currency (Optional[str]): Three-letter currency code, e.g. "USD".
            gl (Optional[str]): Two-letter country code.
            hl (Optional[str]): UI language code.

        Returns:
            str: JSON string with ``best_flights`` and ``other_flights``: legs, airlines,
            durations, layovers, emissions and prices. Costs 1 credit.
        """
        return self._call(
            self.client.google.flights,
            departure_id,
            arrival_id,
            outbound_date,
            return_date=return_date,
            type=type,
            adults=adults,
            children=children,
            infants_in_seat=infants_in_seat,
            infants_on_lap=infants_on_lap,
            travel_class=travel_class,
            stops=stops,
            sort_by=sort_by,
            include_airlines=include_airlines,
            exclude_airlines=exclude_airlines,
            currency=currency,
            gl=gl,
            hl=hl,
        )

    def google_hotels(
        self,
        query: str,
        check_in_date: str,
        check_out_date: str,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        currency: Optional[str] = None,
        sort_by: Optional[int] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        rating: Optional[int] = None,
        hotel_class: Optional[str] = None,
        amenities: Optional[str] = None,
        property_types: Optional[str] = None,
        free_cancellation: Optional[bool] = None,
        eco_certified: Optional[bool] = None,
        special_offers: Optional[bool] = None,
        next_page_token: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> str:
        """Search Google Hotels for stays and nightly rates.

        Args:
            query (str): Where to stay, in the form "<City> hotels", e.g. "Barcelona hotels".
            check_in_date (str): Check-in date as "YYYY-MM-DD".
            check_out_date (str): Check-out date as "YYYY-MM-DD".
            gl (Optional[str]): Two-letter country code.
            hl (Optional[str]): UI language code.
            currency (Optional[str]): Three-letter currency code, e.g. "USD".
            sort_by (Optional[int]): 3 lowest price, 8 highest rating, 13 most reviewed.
            min_price (Optional[int]): Lowest nightly price.
            max_price (Optional[int]): Highest nightly price.
            rating (Optional[int]): 7 for 3.5+, 8 for 4.0+, 9 for 4.5+.
            hotel_class (Optional[str]): Comma-separated star ratings, e.g. "4,5".
            amenities (Optional[str]): Comma-separated amenity ids.
            property_types (Optional[str]): Comma-separated property-type ids ("12" is
                vacation rentals).
            free_cancellation (Optional[bool]): Only properties with free cancellation.
            eco_certified (Optional[bool]): Only eco-certified properties.
            special_offers (Optional[bool]): Only properties with a special offer.
            next_page_token (Optional[str]): Cursor from a previous response.
            limit (Optional[int]): Properties to return, 1 to 20.

        Returns:
            str: JSON string with ``properties``: name, rate, rating, amenities, coordinates and
            a ``detail_token`` to pass to google_hotels_detail. Costs 1 credit.
        """
        return self._call(
            self.client.google.hotels,
            query,
            check_in_date,
            check_out_date,
            gl=gl,
            hl=hl,
            currency=currency,
            sort_by=sort_by,
            min_price=min_price,
            max_price=max_price,
            rating=rating,
            hotel_class=hotel_class,
            amenities=amenities,
            property_types=property_types,
            free_cancellation=free_cancellation,
            eco_certified=eco_certified,
            special_offers=special_offers,
            next_page_token=next_page_token,
            limit=limit,
        )

    def google_hotels_detail(
        self,
        detail_token: str,
        check_in_date: str,
        check_out_date: str,
        currency: Optional[str] = None,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
    ) -> str:
        """Get one hotel's details and the sites booking it.

        Args:
            detail_token (str): The ``detail_token`` of a property returned by google_hotels.
            check_in_date (str): Check-in date as "YYYY-MM-DD". Must be sent again: the token
                alone does not carry the dates.
            check_out_date (str): Check-out date as "YYYY-MM-DD".
            currency (Optional[str]): Three-letter currency code.
            gl (Optional[str]): Two-letter country code.
            hl (Optional[str]): UI language code.

        Returns:
            str: JSON string with ``property`` and ``property.booking_sources``: each site's
            price for the same stay. Costs 1 credit.
        """
        return self._call(
            self.client.google.hotels_detail,
            detail_token,
            check_in_date,
            check_out_date,
            currency=currency,
            gl=gl,
            hl=hl,
        )

    def google_news(
        self,
        query: Optional[str] = None,
        topic_token: Optional[str] = None,
        section_token: Optional[str] = None,
        story_token: Optional[str] = None,
        publication_token: Optional[str] = None,
        kgmid: Optional[str] = None,
        hl: Optional[str] = None,
        gl: Optional[str] = None,
        so: Optional[int] = None,
    ) -> str:
        """Read Google News: a keyword search, a topic, a story or a publication.

        Set EXACTLY ONE of query, topic_token, section_token, story_token, publication_token
        or kgmid. Sending two is rejected outright rather than one winning.

        Args:
            query (Optional[str]): Keyword search.
            topic_token (Optional[str]): Browse a topic, from a previous response.
            section_token (Optional[str]): Browse a section of a topic.
            story_token (Optional[str]): Full coverage of one story.
            publication_token (Optional[str]): Browse one publication.
            kgmid (Optional[str]): Knowledge Graph entity id, e.g. "/m/02_286".
            hl (Optional[str]): UI language code.
            gl (Optional[str]): Two-letter country code.
            so (Optional[int]): 0 relevance, 1 date. Only valid alongside query or kgmid.

        Returns:
            str: JSON string with ``news_results``: headline, source, timestamp, link and the
            tokens for drilling further. Costs 1 credit.
        """
        return self._call(
            self.client.google.news,
            query=query,
            topic_token=topic_token,
            section_token=section_token,
            story_token=story_token,
            publication_token=publication_token,
            kgmid=kgmid,
            hl=hl,
            gl=gl,
            so=so,
        )

    def google_trends(
        self,
        query: str,
        geo: Optional[str] = None,
        hl: Optional[str] = None,
        date: Optional[str] = None,
        tz: Optional[str] = None,
        data_type: Optional[str] = None,
        cat: Optional[str] = None,
        gprop: Optional[str] = None,
        region: Optional[str] = None,
    ) -> str:
        """Get Google Trends interest over time and by region for a search term.

        Args:
            query (str): The term to measure. Comma-separate up to five terms to compare them.
            geo (Optional[str]): Location code, UPPERCASE: "US", "GB", "US-CA". Omit for
                worldwide. This tool uses geo, not gl.
            hl (Optional[str]): UI language code.
            date (Optional[str]): Time range as free text, e.g. "today 12-m", "now 7-d" or
                "2024-01-01 2024-12-31".
            tz (Optional[str]): Timezone offset in minutes, as a string.
            data_type (Optional[str]): "TIMESERIES", "GEO_MAP", "GEO_MAP_0", "RELATED_QUERIES"
                or "RELATED_TOPICS". UPPERCASE.
            cat (Optional[str]): Category id as a string, e.g. "71".
            gprop (Optional[str]): Restrict to a Google property: "images", "news", "youtube"
                or "froogle". Omit for web search.
            region (Optional[str]): Resolution for GEO_MAP data: "COUNTRY", "REGION", "DMA"
                or "CITY".

        Returns:
            str: JSON string with ``interest_over_time.timeline_data`` and
            ``interest_by_region``. Values are relative interest (0-100), never absolute search
            volumes. Costs 1 credit.
        """
        return self._call(
            self.client.google.trends,
            query,
            geo=geo,
            hl=hl,
            date=date,
            tz=tz,
            data_type=data_type,
            cat=cat,
            gprop=gprop,
            region=region,
        )

    def google_trending(
        self,
        geo: str,
        hl: Optional[str] = None,
        hours: Optional[int] = None,
        cat: Optional[int] = None,
        sort: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        """List what is trending on Google right now in one country.

        Args:
            geo (str): Country code, e.g. "US". Required - this tool has no query field.
            hl (Optional[str]): UI language code.
            hours (Optional[int]): Trending window in hours: 4, 24, 48 or 168.
            cat (Optional[int]): Category id as a number, 0 to 20; 0 is all categories.
            sort (Optional[str]): "relevance", "search_volume", "recency" or "title". The field
                is sort here, not sort_by.
            status (Optional[str]): "all" or "active".

        Returns:
            str: JSON string with ``trends``: the trending term, its volume band, when it
            started and related news. Costs 1 credit.
        """
        return self._call(
            self.client.google.trending,
            geo,
            hl=hl,
            hours=hours,
            cat=cat,
            sort=sort,
            status=status,
        )

    # ------------------------------------------------------------------ Amazon

    def amazon_search(
        self,
        query: str,
        country: Optional[str] = None,
        page: Optional[int] = None,
    ) -> str:
        """Search an Amazon marketplace for products matching a query.

        There is NO sort option. The marketplace ignores every sort value and always
        returns its default relevance ranking, so results are unordered with respect
        to price, rating and date: to answer "the cheapest" or "the best rated",
        fetch the results and sort them yourself. There is also no category, merchant
        or price-range filter; the ``filters`` list in the response carries the
        marketplace's own refinement URLs for reference only and cannot be sent back
        as a parameter.

        Args:
            query (str): The product search query, e.g. "wireless noise cancelling headphones".
            country (Optional[str]): Marketplace country code, ISO 3166-1 alpha-2, lowercase.
                Defaults to "us". Valid: us, ae, au, be, br, ca, cn, de, eg, es, fr, gb, in,
                it, jp, mx, nl, pl, sa, se, sg, tr. Note the UK is "gb". An unrecognised code
                falls back to "us" instead of failing, so a typo silently returns US results.
            page (Optional[int]): Results page, 1-based. One page per call, 1 credit each;
                there is no multi-page fetch.

        Returns:
            str: JSON string with ``query``, ``page``, ``total_results``, ``count``,
            ``products``, ``filters`` and ``related_searches``. Each product has ``asin``,
            ``title``, ``url``, ``image``, ``price`` (number) with ``currency``, ``rating``,
            ``reviews_count``, ``is_sponsored``, ``position``, ``badge``, ``sales_volume``
            and ``delivery`` {is_free, date, fastest_date}. ``reviews_count`` is derived
            from Amazon's rounded display value, so anything above 1000 is approximate (a
            page showing "1.3K" returns 1300); ``position`` is Amazon's grid slot index
            including ad and carousel slots, so it starts above 1 and has gaps.
            Costs 1 credit per page.
        """
        return self._call(self.client.amazon.search, query, country=country, page=page)

    def amazon_product(
        self,
        asin: str,
        country: Optional[str] = None,
    ) -> str:
        """Get the full product page for a single Amazon product by ASIN.

        ``price`` is the current buy-box price and ``other_sellers_count`` only counts
        the rest, so call ``amazon_offers`` when you need the competing sellers and
        their prices. ``reviews`` carries review metadata only (id, author, date,
        verified_purchase): there is no review text and no per-review rating anywhere
        in the response.

        Args:
            asin (str): The Amazon Standard Identification Number - the 10-character
                product id, e.g. "B09V3KXJPB". Extract it from the product URL (/dp/ASIN).
            country (Optional[str]): Marketplace country code, ISO 3166-1 alpha-2, lowercase.
                Defaults to "us". Valid: us, ae, au, be, br, ca, cn, de, eg, es, fr, gb, in,
                it, jp, mx, nl, pl, sa, se, sg, tr. Note the UK is "gb".

        Returns:
            str: JSON string with ``title``, ``brand``, ``url``, ``description``,
            ``features``, ``price``, ``list_price``, ``currency``, ``rating``,
            ``reviews_count``, ``is_prime``, ``has_buy_box``, ``availability`` (free text
            such as "In Stock", marketplace- and language-specific), ``max_quantity``,
            ``sold_by``, ``other_sellers_count``, ``sales_volume``,
            ``climate_pledge_friendly``, ``image``, ``images``, ``videos``,
            ``best_sellers_rank``, ``categories``, ``specifications``, ``variants`` and
            ``shipping`` {is_prime, zipcode, options}. Costs 1 credit.
        """
        return self._call(self.client.amazon.product, asin, country=country)

    def amazon_offers(
        self,
        asin: str,
        country: Optional[str] = None,
    ) -> str:
        """List every seller currently offering an Amazon product, by ASIN.

        Use it to find the cheapest seller for a known ASIN, to check who holds the buy
        box, to compare new against used pricing, or to see whether a third-party seller
        undercuts Amazon. This returns the FIRST page of the offer list only:
        ``has_more_pages`` may be true and there is no way to request the next page. An
        ASIN sold only by Amazon returns an empty ``offers`` list plus an explanatory
        ``note``, which is a normal answer rather than an error.

        Args:
            asin (str): The Amazon Standard Identification Number - the 10-character
                product id, e.g. "B09V3KXJPB". Extract it from the product URL (/dp/ASIN).
            country (Optional[str]): Marketplace country code, ISO 3166-1 alpha-2, lowercase.
                Defaults to "us". Valid: us, ae, au, be, br, ca, cn, de, eg, es, fr, gb, in,
                it, jp, mx, nl, pl, sa, se, sg, tr. Note the UK is "gb".

        Returns:
            str: JSON string with ``asin``, ``title``, ``image``, ``rating``,
            ``reviews_count``, ``note``, ``count``, ``total_offers``, ``has_more_pages``,
            ``page`` and ``offers``. Each offer has ``condition`` ("New", "Used - Like
            New", ...), ``seller_id``, ``seller_name``, ``ships_from``,
            ``is_fulfilled_by_amazon``, ``is_buy_box_winner``, ``is_prime``,
            ``is_national_prime``, ``price`` with ``currency``, ``list_price``,
            ``shipping_price``, ``discount_percentage``, ``discount_amount``,
            ``quantity``, ``delivery`` {min_hours, max_hours, date, is_free} and
            ``prime_delivery`` {date, order_deadline}. Costs 1 credit.
        """
        return self._call(self.client.amazon.offers, asin, country=country)

    def amazon_options(self) -> str:
        """List the Amazon marketplaces this API supports.

        Supported Amazon marketplaces, as 'domains' and 'countries'. 'languages' and 'currencies' remain in the
        payload but are always empty: neither is a request param any more. No API key required.

        Returns:
            str: JSON string of the API response. Free: it is a static reference list served straight from a constant,
            so it is not billed and needs no API key.
        """
        return self._call(self.client.amazon.options)

    # ----------------------------------------------------------------- Walmart
    #
    # Walmart is BODY-PRICED: search and category cost 1 credit on domain 'com' or
    # 'ca' and 2 on 'com.mx'. The other five take no domain and are always 1. The
    # seller tools are keyed by the numeric `seller_catalog_id` that a product,
    # search or offers row carries, NOT by the GUID `seller_id`, which 404s.

    def walmart_search(
        self,
        query: str,
        domain: Optional[str] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        fulfillment_speed: Optional[str] = None,
        fulfillment_type: Optional[str] = None,
    ) -> str:
        """Search Walmart for products matching a query.

        Search Walmart and get structured product rows (products, products_count and the store the results were priced
        against).

        Args:
            query (str): Product search query (1-500 characters).
            domain (Optional[str]): Marketplace: 'com' (US, default, 1 credit), 'ca' (1 credit), 'com.mx' (2
                credits). Sets the currency and product URLs of the response.
            page (Optional[int]): Results page, 1-based (integer >= 1). One page per call.
            sort_by (Optional[str]): Result sort order. Defaults to 'best_match'. One of: "best_match",
                "price_low", "price_high", "best_seller", "rating_high", "new".
            min_price (Optional[float]): Minimum price filter in the marketplace's own currency; decimals allowed
                (e.g. 19.99).
            max_price (Optional[float]): Maximum price filter in the marketplace's own currency; decimals allowed
                (e.g. 199.5).
            fulfillment_speed (Optional[str]): Only items deliverable today, or by tomorrow. '2_days' and
                'anytime' are not accepted - for anytime, omit this parameter.
            fulfillment_type (Optional[str]): Set to 'in_store' to return only items available for in-store
                pickup.

        Returns:
            str: JSON string of the API response. Costs 1 credit on domain 'com' or 'ca' and 2 credits on 'com.mx' -
            the price is a function of the request body, not a constant for the route.
        """
        return self._call(
            self.client.walmart.search,
            query,
            domain=domain,
            page=page,
            sort_by=sort_by,
            min_price=min_price,
            max_price=max_price,
            fulfillment_speed=fulfillment_speed,
            fulfillment_type=fulfillment_type,
        )

    def walmart_product(self, product_id: str) -> str:
        """Get full details for a single Walmart product.

        Full detail for a single Walmart product: price, rating, images, specifications, availability and seller. US
        marketplace only - walmart.ca product pages could not be fetched at all, so this endpoint takes no domain.

        Args:
            product_id (str): Walmart item id (usItemId), e.g. '13544111159'.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Walmart is body-priced through `domain`, but this
            endpoint takes no domain, so it is always 1.
        """
        return self._call(
            self.client.walmart.product,
            product_id,
        )

    def walmart_reviews(
        self,
        product_id: str,
        page: Optional[int] = None,
        sort: Optional[str] = None,
    ) -> str:
        """Get customer reviews for a Walmart product.

        Customer reviews for a Walmart product with ratings, text, author, date and the rating breakdown. 10 reviews
        per page; paginate with page.

        Args:
            product_id (str): Walmart item id (usItemId), e.g. '13544111159'.
            page (Optional[int]): Reviews page, 1-based (integer >= 1). 10 reviews per page.
            sort (Optional[str]): Review sort order. Omit for Walmart's own default ordering. One of: "relevancy",
                "submission-desc", "submission-asc", "rating-desc", "rating-asc", "helpful-desc".

        Returns:
            str: JSON string of the API response. Costs 1 credit. Walmart is body-priced through `domain`, but this
            endpoint takes no domain, so it is always 1.
        """
        return self._call(
            self.client.walmart.reviews,
            product_id,
            page=page,
            sort=sort,
        )

    def walmart_category(
        self,
        category_id: str,
        domain: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        sort_by: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        fulfillment_speed: Optional[str] = None,
    ) -> str:
        """List the products in a Walmart category.

        Products within a Walmart category, in the same product shape as search.

        Args:
            category_id (str): Walmart category id: either a leaf id ('1095191') or the full underscore-joined
                path ('3944_133251_1095191'). Both are accepted.
            domain (Optional[str]): Marketplace: 'com' (US, default, 1 credit), 'ca' (1 credit), 'com.mx' (2
                credits). Sets the currency and product URLs of the response.
            page (Optional[int]): Results page, 1-based (integer >= 1). One page per call.
            limit (Optional[int]): Trim the returned products to at most this many (integer >= 1). Applied after
                fetching, so it does not reduce the credit cost of the call.
            sort_by (Optional[str]): Result sort order. Defaults to 'best_match'. One of: "best_match",
                "price_low", "price_high", "best_seller", "rating_high", "new".
            min_price (Optional[float]): Minimum price filter in the marketplace's own currency; decimals allowed
                (e.g. 19.99).
            max_price (Optional[float]): Maximum price filter in the marketplace's own currency; decimals allowed
                (e.g. 199.5).
            fulfillment_speed (Optional[str]): Only items deliverable today, or by tomorrow. '2_days' and
                'anytime' are not accepted - for anytime, omit this parameter.

        Returns:
            str: JSON string of the API response. Costs 1 credit on domain 'com' or 'ca' and 2 credits on 'com.mx' -
            the price is a function of the request body, not a constant for the route.
        """
        return self._call(
            self.client.walmart.category,
            category_id,
            domain=domain,
            page=page,
            limit=limit,
            sort_by=sort_by,
            min_price=min_price,
            max_price=max_price,
            fulfillment_speed=fulfillment_speed,
        )

    def walmart_offers(self, product_id: str) -> str:
        """Get the buy-box offer for a Walmart product.

        The buy-box offer for a Walmart product: price, seller, condition and buy-box flag. BUY-BOX SELLER ONLY - this
        is not the full offer list, and there is no way to page through the other sellers.

        Args:
            product_id (str): Walmart item id (usItemId), e.g. '2979510112'.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Walmart is body-priced through `domain`, but this
            endpoint takes no domain, so it is always 1.
        """
        return self._call(
            self.client.walmart.offers,
            product_id,
        )

    def walmart_seller(self, seller_id: str) -> str:
        """Get a Walmart marketplace seller's storefront.

        Marketplace seller storefront: name, rating, review count, Pro Seller badge and business details.

        Args:
            seller_id (str): Numeric Walmart catalog seller id, as returned in `seller_catalog_id` on a product,
                search or offers response (e.g. '101480084'). The GUID `seller_id` is not accepted here - it 404s.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Walmart is body-priced through `domain`, but this
            endpoint takes no domain, so it is always 1.
        """
        return self._call(
            self.client.walmart.seller,
            seller_id,
        )

    def walmart_seller_products(self, seller_id: str) -> str:
        """List a Walmart marketplace seller's catalog.

        Roughly the first 40 items are server-rendered and returned; total_count reports the seller's real catalog
        size. There is no pagination - the rest of the catalog is not reachable.

        Args:
            seller_id (str): Numeric Walmart catalog seller id, as returned in `seller_catalog_id` on a product,
                search or offers response (e.g. '101480084'). The GUID `seller_id` 404s.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Walmart is body-priced through `domain`, but this
            endpoint takes no domain, so it is always 1.
        """
        return self._call(
            self.client.walmart.seller_products,
            seller_id,
        )

    # ----------------------------------------------------------------- YouTube
    #
    # Credit cost is not uniform here: search and Shorts search are 2, transcript
    # is 8, streams is 3, and the other eleven are 1. Each docstring states its
    # own so an agent can weigh a call before making it. Every id field accepts a
    # full URL as well as a bare id, and channel fields also accept an @handle.
    # /youtube/metadata is a deprecated alias of /youtube/video and is not
    # registered as a separate tool - use youtube_video.

    def youtube_search(
        self,
        query: str,
        upload_date: Optional[str] = None,
        type: Optional[str] = None,
        duration: Optional[str] = None,
        sort_by: Optional[str] = None,
        features: Optional[List[str]] = None,
        cursor: Optional[str] = None,
        hd: Optional[bool] = None,
        subtitles: Optional[bool] = None,
        creative_commons: Optional[bool] = None,
        live: Optional[bool] = None,
    ) -> str:
        """Search YouTube for videos, channels, or playlists matching a query.

        Args:
            query (str): The search query.
            upload_date (Optional[str]): "last_hour", "today", "this_week", "this_month" or "this_year".
            type (Optional[str]): Result type filter: "video", "channel", "playlist" or "movie".
            duration (Optional[str]): "short" (under 4 min), "medium" (4-20 min) or "long" (over 20 min).
            sort_by (Optional[str]): "relevance", "date", "view_count" or "rating".
            features (Optional[List[str]]): Feature filters. Any of "hd", "4k", "subtitles",
                "creative_commons", "live", "360", "3d", "hdr", "vr180".
            cursor (Optional[str]): Pagination cursor from a previous response's next_cursor.
            hd (Optional[bool]): Restrict to HD videos when True.
            subtitles (Optional[bool]): Restrict to videos with subtitles when True.
            creative_commons (Optional[bool]): Restrict to Creative Commons videos when True.
            live (Optional[bool]): Restrict to live videos when True.

        Returns:
            str: JSON string with ``results`` (videos), ``shorts``, ``channels``, ``playlists``,
            ``next_cursor`` and ``has_more``. Costs 2 credits, the joint most expensive YouTube
            search call - prefer one well-formed query over several narrow ones.
        """
        return self._call(
            self.client.youtube.search,
            query,
            upload_date=upload_date,
            type=type,
            duration=duration,
            sort_by=sort_by,
            features=features,
            cursor=cursor,
            hd=hd,
            subtitles=subtitles,
            creative_commons=creative_commons,
            live=live,
        )

    def youtube_shorts(
        self,
        query: str,
        sort_by: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Search YouTube Shorts for a query.

        Args:
            query (str): The search query.
            sort_by (Optional[str]): "relevance", "date", "view_count" or "rating".
            cursor (Optional[str]): Pagination cursor from a previous response's next_cursor.

        Returns:
            str: JSON string with ``results``, ``next_cursor`` and ``has_more``. Costs 2 credits.
        """
        return self._call(self.client.youtube.shorts, query, sort_by=sort_by, cursor=cursor)

    def youtube_suggestions(
        self,
        query: str,
        language: Optional[str] = None,
        region: Optional[str] = None,
    ) -> str:
        """Get YouTube autocomplete suggestions for a partial query.

        Cheap way to discover what people actually type before spending 2 credits on a search.

        Args:
            query (str): The partial search query.
            language (Optional[str]): Language code, e.g. "en".
            region (Optional[str]): Region code, e.g. "US". The only geo filter in the YouTube tools.

        Returns:
            str: JSON string with ``suggestions`` and ``total_count``. Costs 1 credit.
        """
        return self._call(self.client.youtube.suggestions, query, language=language, region=region)

    def youtube_video(self, video_id: str) -> str:
        """Get full metadata for a single YouTube video.

        Args:
            video_id (str): The YouTube video id or any watch/shorts/youtu.be URL.

        Returns:
            str: JSON string with ``title``, ``author``, ``channel_id``, ``published_at``,
            ``description``, ``length_seconds``, ``view_count``, ``keywords``, ``thumbnail``,
            ``chapters`` and ``captions`` (the caption tracks, not the text - use
            youtube_transcript for that). Costs 1 credit.
        """
        return self._call(self.client.youtube.video, video_id)

    def youtube_comments(self, video_id: str, cursor: Optional[str] = None) -> str:
        """List the top-level comments on a YouTube video.

        Args:
            video_id (str): The YouTube video id or watch URL.
            cursor (Optional[str]): Pagination cursor from a previous response's next_cursor.

        Returns:
            str: JSON string with ``comments``, ``next_cursor`` and ``has_more``. Each comment
            carries a ``reply_cursor``; that is the value youtube_comment_replies needs.
            Costs 1 credit.
        """
        return self._call(self.client.youtube.comments, video_id, cursor=cursor)

    def youtube_comment_replies(
        self,
        video_id: str,
        reply_cursor: str,
        cursor: Optional[str] = None,
    ) -> str:
        """List the replies to one YouTube comment.

        Args:
            video_id (str): The YouTube video id or watch URL.
            reply_cursor (str): The ``reply_cursor`` of the comment, from youtube_comments.
                Required - this tool cannot be called from a video id alone.
            cursor (Optional[str]): Cursor for page 2 onward. It overrides reply_cursor for
                that call, so only pass it when continuing an earlier reply page.

        Returns:
            str: JSON string with ``replies``, ``next_cursor`` and ``has_more``. Costs 1 credit.
        """
        return self._call(self.client.youtube.comment_replies, video_id, reply_cursor, cursor=cursor)

    def youtube_transcript(self, video_id: str, language: Optional[str] = None, format: Optional[str] = None) -> str:
        """Get the transcript or timed subtitles for a YouTube video.

        Args:
            video_id (str): The YouTube video id or watch URL.
            language (Optional[str]): Caption language code; defaults to "en".
            format (Optional[str]): "text" for a plain transcript or "srt" for timed subtitles.

        Returns:
            str: JSON string with ``video_id``, ``language_code``, ``language_name``, ``format``
            and ``content`` (the whole transcript as one string). Costs 8 credits - the most
            expensive YouTube tool by a wide margin, so check youtube_video's ``captions`` list
            first and only pull a transcript you are going to read.
        """
        return self._call(self.client.youtube.transcript, video_id, language=language, format=format)

    def youtube_related(self, video_id: str, cursor: Optional[str] = None) -> str:
        """List videos YouTube considers related to a given video.

        Args:
            video_id (str): The YouTube video id or watch URL.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string with ``results`` and ``total_count``. This endpoint returns no
            next_cursor, so there is nothing to page with after the first call. Costs 1 credit.
        """
        return self._call(self.client.youtube.related, video_id, cursor=cursor)

    def youtube_channel_search(self, query: str, cursor: Optional[str] = None) -> str:
        """Search YouTube for channels by name.

        Args:
            query (str): The channel search query, e.g. "mrbeast".
            cursor (Optional[str]): Pagination cursor from a previous response's next_cursor.

        Returns:
            str: JSON string with ``results`` (channel id, name, handle, subscriber count,
            description, verified), ``next_cursor``, ``has_more`` and ``total_count``.
            Costs 1 credit.
        """
        return self._call(self.client.youtube.channel_search, query, cursor=cursor)

    def youtube_channel(self, channel_id: str) -> str:
        """Get details for a YouTube channel.

        Args:
            channel_id (str): The channel id ("UC..."), an @handle, or a channel URL.

        Returns:
            str: JSON string with ``title``, ``description``, ``handle``, ``subscriber_count``,
            ``video_count``, ``view_count``, ``country``, ``creation_date``, ``verified``,
            ``avatar``, ``banner`` and ``links``. Costs 1 credit.
        """
        return self._call(self.client.youtube.channel, channel_id)

    def youtube_channel_videos(self, channel_id: str, cursor: Optional[str] = None) -> str:
        """List the videos uploaded by a YouTube channel.

        Args:
            channel_id (str): The channel id, an @handle, or a channel URL.
            cursor (Optional[str]): Pagination cursor from a previous response's next_cursor.

        Returns:
            str: JSON string with ``channel_id``, ``results`` (video id, title, url, thumbnail,
            duration, view count, published time, is_live), ``next_cursor`` and ``has_more``.
            Costs 1 credit.
        """
        return self._call(self.client.youtube.channel_videos, channel_id, cursor=cursor)

    def youtube_channel_shorts(self, channel_id: str, cursor: Optional[str] = None) -> str:
        """List the Shorts posted by a YouTube channel.

        Args:
            channel_id (str): The channel id, an @handle, or a channel URL.
            cursor (Optional[str]): Pagination cursor from a previous response's next_cursor.

        Returns:
            str: JSON string with ``channel_id``, ``results``, ``next_cursor``, ``has_more`` and
            ``total_count``. Shorts entries carry no view count: the source field holds promo
            text rather than a number, so it is dropped instead of guessed. Costs 1 credit.
        """
        return self._call(self.client.youtube.channel_shorts, channel_id, cursor=cursor)

    def youtube_channel_community(self, channel_id: str, cursor: Optional[str] = None) -> str:
        """List a YouTube channel's community posts.

        Args:
            channel_id (str): The channel id, an @handle, or a channel URL.
            cursor (Optional[str]): Pagination cursor from a previous response's next_cursor.

        Returns:
            str: JSON string with ``channel_id``, ``posts`` (text, published time, vote and
            comment counts, attachments), ``next_cursor`` and ``has_more``. Costs 1 credit.
        """
        return self._call(self.client.youtube.channel_community, channel_id, cursor=cursor)

    def youtube_channel_resolve(self, channel: str) -> str:
        """Resolve a YouTube @handle or channel URL to a channel id.

        The other channel tools accept a handle directly, so this is only needed when you want
        the id itself.

        Args:
            channel (str): An @handle, a bare channel name, or a channel URL.

        Returns:
            str: JSON string with ``channel_id`` and ``channel_url``. Costs 1 credit.
        """
        return self._call(self.client.youtube.channel_resolve, channel)

    def youtube_streams(self, video_id: str) -> str:
        """Get playable and downloadable stream formats for a YouTube video.

        Args:
            video_id (str): The YouTube video id or watch URL.

        Returns:
            str: JSON string with ``formats``, ``adaptive_formats``, ``available_qualities`` and
            ``expires_in_seconds``. The stream URLs are time-limited, so use them promptly.
            Costs 3 credits.
        """
        return self._call(self.client.youtube.streams, video_id)

    # ------------------------------------------------------------------ Reddit

    def reddit_search(self, query: str, cursor: Optional[str] = None) -> str:
        """Search Reddit posts.

        Search takes a query and a cursor and nothing else. There is no type selector and no
        sort order: this searches posts only, in Reddit's own relevance order. To sort or to
        browse a community, use reddit_subreddit_posts, which does have a sort.

        Args:
            query (str): The search query.
            cursor (Optional[str]): Pagination cursor - the ``next_cursor`` of a previous response.

        Returns:
            str: JSON string with ``results`` (post id, title, text, url, subreddit, author,
            score, upvote ratio, comment count, created_at, flags and media), plus
            ``next_cursor`` and ``has_more``. The list key is ``results``, not ``posts``.
            Costs 1 credit.
        """
        return self._call(self.client.reddit.search, query, cursor=cursor)

    def reddit_search_suggestions(self, query: str) -> str:
        """Get Reddit autocomplete search suggestions for a query.

        Args:
            query (str): The partial search query to complete.

        Returns:
            str: JSON string with a ``suggestions`` list. Costs 1 credit.
        """
        return self._call(self.client.reddit.search_suggestions, query)

    def reddit_post(self, url: Optional[str] = None, post_id: Optional[str] = None) -> str:
        """Fetch a single Reddit post.

        This returns the post only. It does NOT include comments - call
        reddit_post_comments with the same post id for those.

        Args:
            url (Optional[str]): The full URL of the Reddit post.
            post_id (Optional[str]): The post fullname (``t3_...``) or bare id, as an
                alternative to url. Provide one of the two.

        Returns:
            str: JSON string of one flat post object: ``post_id``, ``title``, ``text``, ``url``,
            ``subreddit``, ``author``, ``score``, ``upvote_ratio``, ``num_comments``,
            ``created_at``, ``is_nsfw``, ``is_video``, ``thumbnail`` and ``media``.
            Costs 1 credit.
        """
        return self._call(self.client.reddit.post, url, post_id=post_id)

    def reddit_post_comments(
        self,
        post_id: str,
        sort: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the top-level comments on a Reddit post.

        Args:
            post_id (str): The post fullname (``t3_...``) or bare post id.
            sort (Optional[str]): Comment sort order: "HOT", "NEW", "TOP", "BEST", or "CONTROVERSIAL" (default "TOP").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the comments. Costs 1 credit.
        """
        return self._call(self.client.reddit.post_comments, post_id, sort=sort, cursor=cursor)

    def reddit_comment_replies(
        self,
        post_id: str,
        cursor: str,
        sort: Optional[str] = None,
    ) -> str:
        """List the replies to a specific Reddit comment.

        Args:
            post_id (str): The post fullname (``t3_...``) the comment belongs to.
            cursor (str): The ``reply_cursor`` of the comment (from reddit_post_comments).
            sort (Optional[str]): Sort order: "HOT", "NEW", "TOP", "BEST", or "CONTROVERSIAL" (default "TOP").

        Returns:
            str: JSON string of the replies. Costs 1 credit.
        """
        return self._call(self.client.reddit.comment_replies, post_id, cursor=cursor, sort=sort)

    def reddit_subreddit(self, subreddit: str) -> str:
        """Get metadata for a subreddit.

        Args:
            subreddit (str): The subreddit name (without "r/").

        Returns:
            str: JSON string of the subreddit info. Costs 1 credit.
        """
        return self._call(self.client.reddit.subreddit, subreddit)

    def reddit_subreddit_posts(
        self,
        subreddit: str,
        sort: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the posts in a subreddit's feed.

        Args:
            subreddit (str): The subreddit name (without "r/").
            sort (Optional[str]): Feed sort order: "BEST", "HOT", "NEW", "TOP", "CONTROVERSIAL", or "RISING" (default "HOT").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the subreddit's posts. Costs 1 credit.
        """
        return self._call(self.client.reddit.subreddit_posts, subreddit, sort=sort, cursor=cursor)

    def reddit_user(self, username: str) -> str:
        """Get a redditor's profile.

        Args:
            username (str): The Reddit username (without "u/").

        Returns:
            str: JSON string of the user's profile. Costs 1 credit.
        """
        return self._call(self.client.reddit.user, username)

    def reddit_user_posts(
        self,
        username: str,
        sort: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the posts submitted by a redditor.

        Args:
            username (str): The Reddit username (without "u/").
            sort (Optional[str]): Sort order: "HOT", "NEW", "TOP", "BEST", or "CONTROVERSIAL" (default "NEW").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's posts. Costs 1 credit.
        """
        return self._call(self.client.reddit.user_posts, username, sort=sort, cursor=cursor)

    def reddit_user_comments(
        self,
        username: str,
        sort: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the comments made by a redditor.

        Args:
            username (str): The Reddit username (without "u/").
            sort (Optional[str]): Sort order: "HOT", "NEW", "TOP", "BEST", or "CONTROVERSIAL" (default "NEW").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's comments. Costs 1 credit.
        """
        return self._call(self.client.reddit.user_comments, username, sort=sort, cursor=cursor)

    def reddit_popular(self, cursor: Optional[str] = None) -> str:
        """Get the site-wide Reddit popular feed.

        Args:
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the popular posts. Costs 1 credit.
        """
        return self._call(self.client.reddit.popular, cursor=cursor)

    def reddit_trending(self) -> str:
        """Get the current trending Reddit search queries.

        Returns:
            str: JSON string with a ``trending`` list. Costs 1 credit.
        """
        return self._call(self.client.reddit.trending)

    # ------------------------------------------------------------------ TikTok
    #
    # All eleven TikTok tools cost 1 credit. Two identity rules run through the
    # family: tiktok_profile is the only tool that accepts a username, so the
    # user-level tools need a sec_user_id fetched from it first; and
    # tiktok_hashtag_videos needs a hashtag_id from tiktok_hashtag, not the name.
    # Cursors are strings ("0" is the first page), never numbers.

    def tiktok_profile(self, username: Optional[str] = None, sec_user_id: Optional[str] = None) -> str:
        """Get a TikTok user profile.

        This is the only TikTok tool that takes a username. Its response carries the
        ``sec_user_id`` that tiktok_user_posts, tiktok_user_followers and
        tiktok_user_followings require, so start here when all you have is a handle.

        Args:
            username (Optional[str]): The TikTok username (without "@").
            sec_user_id (Optional[str]): The TikTok secUid. Provide this or username.

        Returns:
            str: JSON string of the profile, under a ``user`` key. Costs 1 credit.
        """
        return self._call(self.client.tiktok.profile, username=username, sec_user_id=sec_user_id)

    def tiktok_user_posts(
        self,
        sec_user_id: str,
        cursor: Optional[str] = None,
        count: Optional[int] = None,
        sort_type: Optional[str] = None,
    ) -> str:
        """List the videos posted by a TikTok user.

        Args:
            sec_user_id (str): The TikTok secUid of the user, from tiktok_profile. A username
                is not accepted here.
            cursor (Optional[str]): Pagination cursor as a string; "0" is the first page.
            count (Optional[int]): Posts per page, 1 to 30. Defaults to 20.
            sort_type (Optional[str]): "0" for latest or "1" for popular, as strings.

        Returns:
            str: JSON string with ``aweme_list``, ``max_cursor`` and ``has_more``.
            Costs 1 credit.
        """
        return self._call(self.client.tiktok.user_posts, sec_user_id, cursor=cursor, count=count, sort_type=sort_type)

    def tiktok_video(self, video_id: str) -> str:
        """Get details for a single TikTok video.

        Args:
            video_id (str): The TikTok video id.

        Returns:
            str: JSON string with the video under ``aweme_detail``. Costs 1 credit.
        """
        return self._call(self.client.tiktok.video, video_id)

    def tiktok_video_comments(self, video_id: str, cursor: Optional[str] = None, count: Optional[int] = None) -> str:
        """List the comments on a TikTok video.

        Args:
            video_id (str): The TikTok video id.
            cursor (Optional[str]): Pagination cursor as a string; "0" is the first page.
            count (Optional[int]): Comments per page, 1 to 50. Defaults to 20.

        Returns:
            str: JSON string with ``comments``, ``cursor``, ``has_more`` and ``total``.
            Costs 1 credit.
        """
        return self._call(self.client.tiktok.video_comments, video_id, cursor=cursor, count=count)

    def tiktok_comment_replies(
        self, video_id: str, comment_id: str, cursor: Optional[str] = None, count: Optional[int] = None
    ) -> str:
        """List the replies to a TikTok comment.

        Args:
            video_id (str): The TikTok video id the comment belongs to.
            comment_id (str): The comment id to fetch replies for.
            cursor (Optional[str]): Pagination cursor as a string; "0" is the first page.
            count (Optional[int]): Replies per page, 1 to 50. Defaults to 20.

        Returns:
            str: JSON string with ``comments``, ``cursor`` and ``has_more``. Costs 1 credit.
        """
        return self._call(self.client.tiktok.comment_replies, video_id, comment_id, cursor=cursor, count=count)

    def tiktok_search_videos(
        self,
        keyword: str,
        cursor: Optional[str] = None,
        count: Optional[int] = None,
        sort_type: Optional[str] = None,
        publish_time: Optional[str] = None,
    ) -> str:
        """Search TikTok for videos matching a keyword.

        Args:
            keyword (str): The search keyword. TikTok's search field is keyword, not query.
            cursor (Optional[str]): Pagination offset as a string; "0" is the first page.
            count (Optional[int]): Videos per page, 1 to 30. Defaults to 20.
            sort_type (Optional[str]): "0" for relevance or "1" for most likes, as strings.
            publish_time (Optional[str]): Age filter in days as a string: "0" all time, "1",
                "7", "30", "90" or "180".

        Returns:
            str: JSON string with ``aweme_list``, ``cursor`` and ``has_more``. Costs 1 credit.
        """
        return self._call(
            self.client.tiktok.search_videos,
            keyword,
            cursor=cursor,
            count=count,
            sort_type=sort_type,
            publish_time=publish_time,
        )

    def tiktok_search_users(self, keyword: str, cursor: Optional[str] = None, count: Optional[int] = None) -> str:
        """Search TikTok for users matching a keyword.

        Args:
            keyword (str): The search keyword.
            cursor (Optional[str]): Pagination offset as a string; "0" is the first page.
            count (Optional[int]): Users per page, 1 to 30. Defaults to 20.

        Returns:
            str: JSON string with ``user_list``, ``cursor`` and ``has_more``. Each user carries
            the ``sec_user_id`` the user-level tools need. Costs 1 credit.
        """
        return self._call(self.client.tiktok.search_users, keyword, cursor=cursor, count=count)

    def tiktok_hashtag(self, hashtag_name: Optional[str] = None, hashtag_id: Optional[str] = None) -> str:
        """Get information about a TikTok hashtag.

        Args:
            hashtag_name (Optional[str]): The hashtag name (without "#").
            hashtag_id (Optional[str]): The hashtag id. Provide this or hashtag_name.

        Returns:
            str: JSON string with the hashtag under ``challengeInfo``, including the id that
            tiktok_hashtag_videos requires. Costs 1 credit.
        """
        return self._call(self.client.tiktok.hashtag, hashtag_name=hashtag_name, hashtag_id=hashtag_id)

    def tiktok_hashtag_videos(self, hashtag_id: str, cursor: Optional[str] = None, count: Optional[int] = None) -> str:
        """List videos for a TikTok hashtag.

        Args:
            hashtag_id (str): The hashtag id from tiktok_hashtag. The hashtag NAME is not
                accepted here.
            cursor (Optional[str]): Pagination cursor as a string; "0" is the first page.
            count (Optional[int]): Videos per page, 1 to 30. Defaults to 20.

        Returns:
            str: JSON string with ``aweme_list``, ``cursor`` and ``has_more``. Costs 1 credit.
        """
        return self._call(self.client.tiktok.hashtag_videos, hashtag_id, cursor=cursor, count=count)

    def tiktok_user_followers(
        self,
        sec_user_id: str,
        count: Optional[int] = None,
        page_token: Optional[str] = None,
        min_time: Optional[int] = None,
    ) -> str:
        """List the followers of a TikTok user.

        Args:
            sec_user_id (str): The TikTok secUid of the user, from tiktok_profile.
            count (Optional[int]): Followers per page, 1 to 20. Defaults to 20.
            page_token (Optional[str]): ``next_page_token`` from a previous response. Follower
                lists page on page_token and min_time, not on a cursor.
            min_time (Optional[int]): ``min_time`` from a previous response, as a number.

        Returns:
            str: JSON string with ``followers``, ``has_more``, ``next_page_token`` and
            ``min_time``. Costs 1 credit.
        """
        return self._call(
            self.client.tiktok.user_followers, sec_user_id, count=count, page_token=page_token, min_time=min_time
        )

    def tiktok_user_followings(
        self,
        sec_user_id: str,
        count: Optional[int] = None,
        page_token: Optional[str] = None,
        min_time: Optional[int] = None,
    ) -> str:
        """List the accounts a TikTok user follows.

        Args:
            sec_user_id (str): The TikTok secUid of the user, from tiktok_profile.
            count (Optional[int]): Accounts per page, 1 to 20. Defaults to 20.
            page_token (Optional[str]): ``next_page_token`` from a previous response.
            min_time (Optional[int]): ``min_time`` from a previous response, as a number.

        Returns:
            str: JSON string with ``followings``, ``has_more`` and ``next_page_token``.
            Costs 1 credit.
        """
        return self._call(
            self.client.tiktok.user_followings, sec_user_id, count=count, page_token=page_token, min_time=min_time
        )

    # --------------------------------------------------------------- Instagram
    #
    # Instagram is the expensive family and its cost is per tool, never a flat
    # rate: instagram_user_posts is 2, instagram_post and
    # instagram_comment_replies are 8, and the other nine are 10. Each docstring
    # states its own. A profile-then-posts pass is therefore 12 credits, and a
    # follower crawl is 10 per page - plan the cheap call first.

    def instagram_profile(self, username: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """Get an Instagram user profile.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user id. Provide this or username; when both
                are given, user_id wins.

        Returns:
            str: JSON string of the profile inlined at the top level: ``username``,
            ``full_name``, ``biography``, ``follower_count``, ``following_count``,
            ``is_private``, ``is_verified``, ``profile_pic_url`` and the numeric ``pk`` you can
            reuse as user_id. Costs 10 credits.
        """
        return self._call(self.client.instagram.profile, username=username, user_id=user_id)

    def instagram_user_posts(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the posts of an Instagram user.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user id. Provide this or username.
            count (Optional[int]): Posts per page, 1 to 50. Defaults to 12.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's timeline posts. Costs 2 credits - by far the
            cheapest Instagram tool, so prefer it over reels or tagged when either would do.
        """
        return self._call(
            self.client.instagram.user_posts, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def instagram_user_reels(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the reels of an Instagram user.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user id. Provide this or username.
            count (Optional[int]): Reels per page, 1 to 50. Defaults to 12.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string with the reels under ``items``, plus ``next_max_id``.
            Costs 10 credits.
        """
        return self._call(
            self.client.instagram.user_reels, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def instagram_user_tagged(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List posts an Instagram user is tagged in.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user id. Provide this or username.
            count (Optional[int]): Posts per page, 1 to 50. Defaults to 12.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string with the tagged posts under ``items``, plus ``next_max_id``.
            Costs 10 credits.
        """
        return self._call(
            self.client.instagram.user_tagged, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def instagram_user_stories(self, username: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """Get the active stories of an Instagram user.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user id. Provide this or username.

        Returns:
            str: JSON string with the currently active stories under ``items``. Stories are not
            paginated. Costs 10 credits.
        """
        return self._call(self.client.instagram.user_stories, username=username, user_id=user_id)

    def instagram_post(
        self,
        url: Optional[str] = None,
        media_id: Optional[str] = None,
        shortcode: Optional[str] = None,
    ) -> str:
        """Get a single Instagram post.

        Args:
            url (Optional[str]): The full URL of the post.
            media_id (Optional[str]): The post media id. Highest precedence of the three, and
                the value instagram_comment_replies needs.
            shortcode (Optional[str]): The post shortcode from the URL. Provide one of url,
                media_id or shortcode.

        Returns:
            str: JSON string with the post at ``items[0]``. Video URLs live in
            ``video_versions[].url`` and covers in ``image_versions2.candidates``; there is no
            video_url or thumbnail_url field. ``media_type`` is 1 image, 2 video, 8 carousel.
            Costs 8 credits.
        """
        return self._call(self.client.instagram.post, url=url, media_id=media_id, shortcode=shortcode)

    def instagram_post_comments(
        self,
        shortcode: Optional[str] = None,
        url: Optional[str] = None,
        cursor: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> str:
        """List the comments on an Instagram post.

        Args:
            shortcode (Optional[str]): The post shortcode.
            url (Optional[str]): The full URL of the post. Provide shortcode or url; a media_id
                is NOT accepted here, unlike instagram_post.
            cursor (Optional[str]): Pagination cursor from a previous response.
            sort_order (Optional[str]): "popular" (default) or "newest".

        Returns:
            str: JSON string with ``comments``, ``comment_count``, ``has_more_comments`` and
            ``next_min_id``. Costs 10 credits.
        """
        return self._call(
            self.client.instagram.post_comments, shortcode=shortcode, url=url, cursor=cursor, sort_order=sort_order
        )

    def instagram_comment_replies(self, media_id: str, comment_id: str, cursor: Optional[str] = None) -> str:
        """List the replies to an Instagram comment.

        Args:
            media_id (str): The post media id. Required, and instagram_post_comments does not
                return one - resolve it with instagram_post first.
            comment_id (str): The comment id to fetch replies for.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string with ``child_comments`` and ``next_min_child_id``. Costs 8 credits.
        """
        return self._call(self.client.instagram.comment_replies, media_id, comment_id, cursor=cursor)

    def instagram_search_users(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Instagram for users matching a keyword.

        Args:
            keyword (str): The search keyword. Instagram's search field is keyword, not query.
            cursor (Optional[str]): Rank token from a previous response.

        Returns:
            str: JSON string with ``users`` and ``rank_token``. Page size is not controllable.
            Costs 10 credits.
        """
        return self._call(self.client.instagram.search_users, keyword, cursor=cursor)

    def instagram_search_hashtags(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Instagram for hashtags matching a keyword.

        Args:
            keyword (str): The search keyword (without "#").
            cursor (Optional[str]): Rank token from a previous response.

        Returns:
            str: JSON string with ``hashtags`` and ``rank_token``. Costs 10 credits.
        """
        return self._call(self.client.instagram.search_hashtags, keyword, cursor=cursor)

    def instagram_user_followers(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the followers of an Instagram user.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user id. Provide this or username.
            count (Optional[int]): Followers per page, 1 to 100. Defaults to 12.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string with ``users`` and ``has_more``. Costs 10 credits PER PAGE, so a
            full follower crawl is expensive - raise count rather than paging more often.
        """
        return self._call(
            self.client.instagram.user_followers, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def instagram_user_followings(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the accounts an Instagram user follows.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user id. Provide this or username.
            count (Optional[int]): Accounts per page, 1 to 100. Defaults to 12.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string with ``users``, ``next_max_id`` and ``has_more``. Costs 10 credits
            per page.
        """
        return self._call(
            self.client.instagram.user_followings, username=username, user_id=user_id, count=count, cursor=cursor
        )

    # ----------------------------------------------------------------- X

    def x_search(
        self,
        query: str,
        search_type: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Search X for tweets and people.

        Args:
            query (str): The search query.
            search_type (Optional[str]): Result category: "Top", "Latest", "People", "Photos", or "Videos" (default "Top").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of search results. Costs 1 credit.
        """
        return self._call(self.client.x.search, query, search_type=search_type, cursor=cursor)

    def x_tweet(self, tweet_id: str) -> str:
        """Get full details for a single tweet.

        Args:
            tweet_id (str): The tweet id.

        Returns:
            str: JSON string of the tweet details. Costs 1 credit.
        """
        return self._call(self.client.x.tweet, tweet_id)

    def x_tweet_comments(
        self,
        tweet_id: str,
        rank: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List the replies to a tweet.

        Args:
            tweet_id (str): The tweet id.
            rank (Optional[str]): "top" (ranked) or "latest" (chronological); default "top".
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the replies. Costs 1 credit.
        """
        return self._call(self.client.x.tweet_comments, tweet_id, rank=rank, cursor=cursor)

    def x_tweet_retweeters(self, tweet_id: str, cursor: Optional[str] = None) -> str:
        """List the users who retweeted a tweet.

        Args:
            tweet_id (str): The tweet id.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the retweeters. Costs 1 credit.
        """
        return self._call(self.client.x.tweet_retweeters, tweet_id, cursor=cursor)

    def x_user(self, screen_name: str) -> str:
        """Get profile details for a X user.

        Args:
            screen_name (str): The X handle (without "@").

        Returns:
            str: JSON string of the user's profile. Costs 1 credit.
        """
        return self._call(self.client.x.user, screen_name)

    def x_user_tweets(self, screen_name: str, cursor: Optional[str] = None) -> str:
        """List a user's tweets.

        Args:
            screen_name (str): The X handle (without "@").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's tweets. Costs 1 credit.
        """
        return self._call(self.client.x.user_tweets, screen_name, cursor=cursor)

    def x_user_replies(self, screen_name: str, cursor: Optional[str] = None) -> str:
        """List a user's tweets and replies.

        Args:
            screen_name (str): The X handle (without "@").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's tweets and replies. Costs 1 credit.
        """
        return self._call(self.client.x.user_replies, screen_name, cursor=cursor)

    def x_user_media(self, screen_name: str, cursor: Optional[str] = None) -> str:
        """List a user's media tweets.

        Args:
            screen_name (str): The X handle (without "@").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's media tweets. Costs 1 credit.
        """
        return self._call(self.client.x.user_media, screen_name, cursor=cursor)

    def x_user_followers(self, screen_name: str, cursor: Optional[str] = None) -> str:
        """List a user's followers.

        Args:
            screen_name (str): The X handle (without "@").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's followers. Costs 1 credit.
        """
        return self._call(self.client.x.user_followers, screen_name, cursor=cursor)

    def x_user_followings(self, screen_name: str, cursor: Optional[str] = None) -> str:
        """List the accounts a user follows.

        Args:
            screen_name (str): The X handle (without "@").
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the accounts the user follows. Costs 1 credit.
        """
        return self._call(self.client.x.user_followings, screen_name, cursor=cursor)

    def x_trending(self, country: Optional[str] = None) -> str:
        """Get the trending topics for a country.

        Args:
            country (Optional[str]): Country name (default "UnitedStates").

        Returns:
            str: JSON string of the trending topics. Costs 1 credit.
        """
        return self._call(self.client.x.trending, country=country)

    # ---------------------------------------------------------------- LinkedIn
    #
    # The provider retired the linkedin/web/* namespace these were built on. The
    # nine tools below run on web_v2: every reference is a vanity handle, slug or
    # id (a full LinkedIn URL also works). Credit cost is not uniform - the reads
    # are 1, the paginated lists are 10 per page, job detail is 30, and each
    # docstring states its own so an agent can weigh it. The five tools
    # with no upstream left - person_contact, company_people, company_jobs,
    # search_people, search_posts - were removed rather than left registered: an
    # agent tool that can only fail burns turns and invites retries.

    def linkedin_person(self, username: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get the full profile for a LinkedIn member.

        Args:
            username (Optional[str]): The public identifier (vanity handle), e.g. "williamhgates".
            url (Optional[str]): A full LinkedIn profile URL, as an alternative to username.

        Returns:
            str: JSON string with name, headline, about, location, avatar, follower and connection
                counts, current company, work experience, education, honours and bio links.
                Costs 1 credit.
        """
        return self._call(self.client.linkedin.person, username=username, url=url)

    def linkedin_person_about(self, username: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get the about/overview sections of a LinkedIn member's profile.

        Args:
            username (Optional[str]): The public identifier (vanity handle).
            url (Optional[str]): A full LinkedIn profile URL, as an alternative to username.

        Returns:
            str: JSON string with the about text, headline, experience, education, honours and
                bio links. Costs 1 credit.
        """
        return self._call(self.client.linkedin.person_about, username=username, url=url)

    def linkedin_person_posts(
        self,
        username: Optional[str] = None,
        url: Optional[str] = None,
        type: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List a LinkedIn member's posts, or the posts they commented on or reacted to.

        Args:
            username (Optional[str]): The public identifier (vanity handle).
            url (Optional[str]): A full LinkedIn profile URL, as an alternative to username.
            type (Optional[str]): Which feed - "posts" (default), "comments" or "reactions".
            cursor (Optional[str]): next_cursor from a previous response, to fetch the next page.

        Returns:
            str: JSON string of 50 posts per page, each with text, url, reaction breakdown,
                comment and repost counts, images and the author, plus next_cursor and has_more.
                Costs 10 credits per page.
        """
        return self._call(self.client.linkedin.person_posts, username=username, url=url, type=type, cursor=cursor)

    def linkedin_company(self, company: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get a LinkedIn company profile.

        Args:
            company (Optional[str]): The company universal name (slug), e.g. "microsoft".
            url (Optional[str]): A full LinkedIn company URL, as an alternative to company.

        Returns:
            str: JSON string with name, about, website, industries, specialties, size, employee and
                follower counts, headquarters, office locations, a small sample of featured
                employees, and similar and affiliated companies. Costs 1 credit.
        """
        return self._call(self.client.linkedin.company, company=company, url=url)

    def linkedin_company_posts(
        self, company: Optional[str] = None, url: Optional[str] = None, cursor: Optional[str] = None
    ) -> str:
        """List a LinkedIn company's recent posts.

        Args:
            company (Optional[str]): The company universal name (slug).
            url (Optional[str]): A full LinkedIn company URL, as an alternative to company.
            cursor (Optional[str]): next_cursor from a previous response, to fetch the next page.

        Returns:
            str: JSON string of 50 posts per page in the same shape as member posts, plus
                next_cursor and has_more. Costs 10 credits per page.
        """
        return self._call(self.client.linkedin.company_posts, company=company, url=url, cursor=cursor)

    def linkedin_search_jobs(self, search: str, location: Optional[str] = None, cursor: Optional[str] = None) -> str:
        """Search LinkedIn for jobs by keyword.

        Args:
            search (str): The job search keyword, e.g. "software engineer".
            location (Optional[str]): A geographic filter, e.g. "United States". Omit to search
                everywhere.
            cursor (Optional[str]): next_cursor from a previous response, to fetch the next page.

        Returns:
            str: JSON string of 25 jobs per page with title, company, location, posted time,
                workplace type and salary, plus next_cursor. The provider rotates its result set,
                so pages overlap slightly and repeating a search returns different listings -
                dedupe by job id. Pass a company name as the search term to approximate a
                per-company listing. Costs 10 credits per page.
        """
        return self._call(self.client.linkedin.search_jobs, search, location=location, cursor=cursor)

    def linkedin_job(self, job_id: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get full details for a single LinkedIn job listing.

        Args:
            job_id (Optional[str]): The job listing id, e.g. "4415427228".
            url (Optional[str]): A full LinkedIn job URL, as an alternative to job_id.

        Returns:
            str: JSON string with title, description, location, employment type, experience level,
                benefits, skills, applicant and view counts, salary and the hiring company.
                Costs 30 credits - the most expensive LinkedIn tool, so prefer the fields
                already returned by linkedin_search_jobs when they are enough. A listing with
                no detail record upstream returns an unbilled 404.
        """
        return self._call(self.client.linkedin.job, job_id=job_id, url=url)

    def linkedin_post(self, post_id: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get full details for a single LinkedIn post.

        Args:
            post_id (Optional[str]): The post id or activity urn, e.g. "7488618410256523265".
            url (Optional[str]): A full LinkedIn post URL, as an alternative to post_id.

        Returns:
            str: JSON string with the body text, url, timestamp, hashtags, images, video and
                document metadata, like and comment counts, tagged entities, top visible comments
                and the author. Costs 1 credit.
        """
        return self._call(self.client.linkedin.post, post_id=post_id, url=url)

    def linkedin_post_comments(
        self, post_id: Optional[str] = None, url: Optional[str] = None, page: Optional[int] = None
    ) -> str:
        """Get the comments on a LinkedIn post.

        Args:
            post_id (Optional[str]): The post id or activity urn.
            url (Optional[str]): A full LinkedIn post URL, as an alternative to post_id.
            page (Optional[int]): 1-based page number. Defaults to 1. Page size varies, so keep
                incrementing until a page returns no comments.

        Returns:
            str: JSON string of comments with text, permalink, timestamp, the commenter and any
                nested replies, plus the total and a has_more flag. Costs 10 credits per page.
        """
        return self._call(self.client.linkedin.post_comments, post_id=post_id, url=url, page=page)

    # ------------------------------------------------------------- TikTok Shop

    def tiktok_shop_search(self, search: str, cursor: Optional[str] = None) -> str:
        """Search TikTok Shop products by keyword (US catalog).

        Returns up to 30 products per page with exact prices, ratings, and shop details.
        Product ids returned here are not guaranteed to resolve on tiktok_shop_product:
        only about 44% do, so treat this as a listing source rather than the first leg of
        a search-then-detail pipeline.

        Args:
            search (str): The product search keyword (1-200 characters).
            cursor (Optional[str]): Opaque cursor from a previous response's next_cursor.

        Returns:
            str: JSON string of matching products. Paginate with next_cursor and dedupe by
            product_id across pages. Costs 1 credit.
        """
        return self._call(self.client.tiktok_shop.search, search, cursor=cursor)

    def tiktok_shop_search_suggestions(self, search: str, region: Optional[str] = None) -> str:
        """Get keyword autocomplete and expansion for a partial TikTok Shop query.

        Args:
            search (str): The partial search keyword (1-100 characters).
            region (Optional[str]): Marketplace region: "US", "GB", "SG", "MY", "PH", "TH", "VN", or "ID". Defaults to "US".

        Returns:
            str: JSON string of suggested keywords. Suggestions are not guaranteed prefix
            matches: a misspelling returns typo corrections, and results can include brand
            and shop names. Costs 1 credit.
        """
        return self._call(self.client.tiktok_shop.search_suggestions, search, region=region)

    def tiktok_shop_product(self, product_id: str, region: Optional[str] = None) -> str:
        """Get full detail for a single TikTok Shop product.

        Returns description, images, variants with stock, shipping, shop profile, category
        path, and top reviews. This tool does NOT return a price: TikTok masks it on the
        product page. Exact prices come from tiktok_shop_search, tiktok_shop_shop_products,
        and tiktok_shop_category_products.

        It also resolves only about 44% of the product ids returned by tiktok_shop_search,
        because TikTok has no detail data for the rest. Those ids answer HTTP 404, which is
        a normal outcome rather than an error: this tool converts that into
        {"data": null, "not_found": true, "reason": ..., "guidance": ...}, so skip the
        product instead of retrying it. If you still need something for an id that does not
        resolve, try tiktok_shop_product_reviews: measured on 8 such ids, 8 of 8 returned a
        successful response and 7 of 8 carried at least one review. That is a measured
        sample, not a guarantee.

        Args:
            product_id (str): The TikTok Shop product id (6-25 digits).
            region (Optional[str]): Marketplace region: "US", "GB", "SG", "MY", "PH", "TH", "VN", or "ID". Defaults to "US".

        Returns:
            str: JSON string of the product detail, without a price, or a structured
            not-found result. Costs 1 credit.
        """
        return self._call_shop(
            self.client.tiktok_shop.product,
            product_id,
            region=region,
            guidance=(
                TIKTOK_SHOP_PRODUCT_COVERAGE_NOTE
                + " "
                + TIKTOK_SHOP_PRODUCT_PRICE_NOTE
                + " "
                + TIKTOK_SHOP_REVIEWS_FALLBACK_NOTE
            ),
        )

    def tiktok_shop_product_reviews(
        self,
        product_id: str,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        sort: Optional[str] = None,
        rating: Optional[int] = None,
        has_media: Optional[bool] = None,
        verified_only: Optional[bool] = None,
        region: Optional[str] = None,
    ) -> str:
        """List the reviews on a TikTok Shop product, up to 200 per call.

        This is also the fallback when tiktok_shop_product cannot resolve an id: measured
        on 8 ids that returned a not-found from detail, 8 of 8 returned a successful
        response here and 7 of 8 carried at least one review. A measured sample, not a
        guarantee, but it is worth one call before dropping the product.

        Args:
            product_id (str): The TikTok Shop product id (6-25 digits).
            page (Optional[int]): 1-based page number (1-500). Defaults to 1.
            page_size (Optional[int]): Reviews per page (1-200). Defaults to 20.
            sort (Optional[str]): "relevant" returns text-complete, image-heavy reviews; "recent" is fresher but far more text-sparse. Defaults to "relevant".
            rating (Optional[int]): Only reviews with this star rating (1-5).
            has_media (Optional[bool]): Only reviews carrying a photo or video.
            verified_only (Optional[bool]): Only verified purchases. Ignored when has_media is True, because TikTok allows one filter at a time.
            region (Optional[str]): Marketplace region: "US", "GB", "SG", "MY", "PH", "TH", "VN", or "ID". Defaults to "US".

        Returns:
            str: JSON string of reviews with text, images, a star histogram, and
            verified-purchase flags. total_reviews drifts between calls and must not be used
            to compute a page count: page with has_more instead. Costs 1 credit.
        """
        return self._call(
            self.client.tiktok_shop.product_reviews,
            product_id,
            page=page,
            page_size=page_size,
            sort=sort,
            rating=rating,
            has_media=has_media,
            verified_only=verified_only,
            region=region,
        )

    def tiktok_shop_categories(self) -> str:
        """Get the global TikTok Shop category tree.

        Takes no parameters. 28 top-level categories, 240 nodes, two levels deep. Category
        ids are identical in every region and names are always English.

        Returns:
            str: JSON string of the category tree. Costs 1 credit.
        """
        return self._call(self.client.tiktok_shop.categories)

    def tiktok_shop_category_products(
        self,
        category_id: str,
        cursor: Optional[str] = None,
        region: Optional[str] = None,
    ) -> str:
        """List the products under a TikTok Shop category id, with exact prices.

        Args:
            category_id (str): A category id from tiktok_shop_categories; level 1 or 2 both work.
            cursor (Optional[str]): Opaque cursor from a previous response's next_cursor.
            region (Optional[str]): Marketplace region. Category listings are served for "US" and "GB" only. Defaults to "US".

        Returns:
            str: JSON string of products in the category, or a structured not-found result
            when the category id returns nothing. Page size is inconsistent (15 to 20),
            so always paginate with next_cursor. Listings are shallow: has_more turning false
            after a few pages is the end of the listing, not an error. Costs 1 credit.
        """
        return self._call_shop(
            self.client.tiktok_shop.category_products,
            category_id,
            cursor=cursor,
            region=region,
            guidance=(
                "Check the category_id against tiktok_shop_categories. Category listings are served for US and GB only."
            ),
        )

    def tiktok_shop_shop_products(
        self,
        shop_id: str,
        cursor: Optional[str] = None,
        region: Optional[str] = None,
    ) -> str:
        """List a TikTok Shop seller's product catalog, 30 per page, with exact prices.

        Args:
            shop_id (str): The TikTok Shop seller id (also called seller_id elsewhere on TikTok).
            cursor (Optional[str]): Opaque cursor from a previous response's next_cursor.
            region (Optional[str]): Marketplace region: "US", "GB", "SG", "MY", "PH", "TH", "VN", or "ID". Defaults to "US".

        Returns:
            str: JSON string of the shop's products, or a structured not-found result when
            the shop id returns nothing. Shop follower count, location, and shop-level
            rating are not available here; use tiktok_shop_product for the full shop
            profile. Costs 1 credit.
        """
        return self._call_shop(
            self.client.tiktok_shop.shop_products,
            shop_id,
            cursor=cursor,
            region=region,
            guidance=("Check the shop_id, or resolve a storefront URL with tiktok_shop_resolve first."),
        )

    def tiktok_shop_resolve(self, url: str) -> str:
        """Resolve a TikTok Shop URL or share link to a product id or shop id.

        Accepts canonical product and store pages, tiktok.com/view links, affiliate share
        links, and vt.tiktok.com short links.

        Args:
            url (str): The TikTok Shop URL or share link.

        Returns:
            str: JSON string with the resolved product_id or shop_id, ready to pass to the
            other TikTok Shop tools, or a structured not-found result for a dead link.
            Costs 1 credit.
        """
        return self._call_shop(
            self.client.tiktok_shop.resolve,
            url,
            guidance=(
                "The link may have expired or may not point to a product or shop. Try the "
                "canonical shop.tiktok.com URL instead."
            ),
        )

    # ----------------------------------------------------------------- Threads
    #
    # Threads is BODY-PRICED: every user-addressed call is 2 credits by user_id and 4 by username, because the
    # upstream handle lookup is down and a handle has to be resolved through people search first. Pass user_id
    # whenever you have one. The post-keyed calls have no username form and are always 2.

    def threads_profile(self, user_id: Optional[str] = None, username: Optional[str] = None) -> str:
        """Get a Threads user's profile.

        Provide user_id or username.

        Args:
            user_id (Optional[str]): Numeric Threads user id, e.g. '63625256886'. The cheap path: 2 credits.
            username (Optional[str]): Threads handle without the @ (1-60 characters). Costs 2 extra credits (4
                total): the upstream handle lookup is down, so the handle is resolved through people search first.
                Pass user_id instead to avoid that.

        Returns:
            str: JSON string of the API response. Costs 2 credits addressed by user_id and 4 credits addressed by
            username - the price is a function of the request body, not a constant for the route.
        """
        return self._call(
            self.client.threads.profile,
            user_id=user_id,
            username=username,
        )

    def threads_user_posts(
        self,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List a Threads user's posts.

        A user's Threads posts, cursor-paginated via next_cursor.

        Provide user_id or username.

        Args:
            user_id (Optional[str]): Numeric Threads user id, e.g. '63625256886'. The cheap path: 2 credits.
            username (Optional[str]): Threads handle without the @ (1-60 characters). Costs 2 extra credits (4
                total) because the handle has to be resolved through people search first.
            cursor (Optional[str]): Pagination cursor from a prior response's next_cursor. Omit for the first
                page.

        Returns:
            str: JSON string of the API response. Costs 2 credits addressed by user_id and 4 credits addressed by
            username - the price is a function of the request body, not a constant for the route.
        """
        return self._call(
            self.client.threads.user_posts,
            user_id=user_id,
            username=username,
            cursor=cursor,
        )

    def threads_user_replies(
        self,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List a Threads user's replies.

        A user's Threads replies, cursor-paginated via next_cursor.

        Provide user_id or username.

        Args:
            user_id (Optional[str]): Numeric Threads user id, e.g. '63625256886'. The cheap path: 2 credits.
            username (Optional[str]): Threads handle without the @ (1-60 characters). Costs 2 extra credits (4
                total) because the handle has to be resolved through people search first.
            cursor (Optional[str]): Pagination cursor from a prior response's next_cursor. Omit for the first
                page.

        Returns:
            str: JSON string of the API response. Costs 2 credits addressed by user_id and 4 credits addressed by
            username - the price is a function of the request body, not a constant for the route.
        """
        return self._call(
            self.client.threads.user_replies,
            user_id=user_id,
            username=username,
            cursor=cursor,
        )

    def threads_post(self, post_id: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get a single Threads post.

        A single Threads post, addressed by post_id or by its threads.net URL.

        Provide post_id or url.

        Args:
            post_id (Optional[str]): Threads post id, e.g. '3349029093483693129'.
            url (Optional[str]): Full threads.net post URL (e.g. 'https://www.threads.net/@natgeo/post/C8xY'), as
                an alternative to post_id.

        Returns:
            str: JSON string of the API response. Costs 2 credits. Threads is body-priced by identifier, but this
            endpoint has no username form, so it is always 2.
        """
        return self._call(
            self.client.threads.post,
            post_id=post_id,
            url=url,
        )

    def threads_post_comments(self, post_id: str, cursor: Optional[str] = None) -> str:
        """List the replies to a Threads post.

        Replies to a Threads post, cursor-paginated via next_cursor. Post-keyed only: there is no username form, so
        this endpoint always costs 2 credits.

        Args:
            post_id (str): Threads post id, e.g. '3349029093483693129'.
            cursor (Optional[str]): Pagination cursor from a prior response's next_cursor. Omit for the first
                page.

        Returns:
            str: JSON string of the API response. Costs 2 credits. Threads is body-priced by identifier, but this
            endpoint has no username form, so it is always 2.
        """
        return self._call(
            self.client.threads.post_comments,
            post_id,
            cursor=cursor,
        )

    def threads_search_users(self, query: str) -> str:
        """Search Threads profiles by name or handle.

        This is the only search Threads exposes - there is no post or content search - and it returns a single
        unpaginated page.

        Args:
            query (str): Name or handle to search for (1-200 characters).

        Returns:
            str: JSON string of the API response. Costs 2 credits. Threads is body-priced by identifier, but this
            endpoint has no username form, so it is always 2.
        """
        return self._call(
            self.client.threads.search_users,
            query,
        )

    # ---------------------------------------------------------------- Kuaishou
    #
    # Kuaishou is priced PER ENDPOINT, not per platform: 1, 2, 10 or 40 credits depending on the call. videos_batch is
    # 40 and search is 10 per page, so read the cost in each docstring before looping. Kwai international (kwai.com)
    # is a different product and is not served.

    def kuaishou_profile(self, user_id: str) -> str:
        """Get a Kuaishou user's profile.

        Args:
            user_id (str): Kuaishou user id (non-empty); get one from user_resolve or search_users.

        Returns:
            str: JSON string of the API response. Costs 10 credits. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.profile,
            user_id,
        )

    def kuaishou_user_posts(self, user_id: str, cursor: Optional[str] = None) -> str:
        """List a Kuaishou user's top posts.

        A Kuaishou user's top posts, cursor-paginated via next_cursor.

        Args:
            user_id (str): Kuaishou user id (non-empty); get one from user_resolve or search_users.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.user_posts,
            user_id,
            cursor=cursor,
        )

    def kuaishou_user_live(self, user_id: str) -> str:
        """Check whether a Kuaishou user is live right now.

        A Kuaishou user's current live-stream status. Not paginated.

        Args:
            user_id (str): Kuaishou user id (non-empty); get one from user_resolve or search_users.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.user_live,
            user_id,
        )

    def kuaishou_user_resolve(self, share_link: str) -> str:
        """Turn a Kuaishou share link into a user id.

        Only kuaishou.com and v.kuaishou.com links are accepted; Kwai international (kwai.com) is not served upstream.

        Args:
            share_link (str): A kuaishou.com or v.kuaishou.com URL; kwai.com links are rejected.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.user_resolve,
            share_link,
        )

    def kuaishou_video(self, photo_id: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get a single Kuaishou video.

        A single Kuaishou video by photo id or URL. Provide photo_id or url.

        Args:
            photo_id (Optional[str]): Kuaishou photo (video) id, non-empty.
            url (Optional[str]): Full kuaishou.com video URL, as an alternative to photo_id.

        Returns:
            str: JSON string of the API response. Costs 2 credits. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.video,
            photo_id=photo_id,
            url=url,
        )

    def kuaishou_video_comments(self, photo_id: str, cursor: Optional[str] = None) -> str:
        """List the comments on a Kuaishou video.

        Comments on a Kuaishou video, cursor-paginated via next_cursor.

        Args:
            photo_id (str): Kuaishou photo (video) id, non-empty.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.video_comments,
            photo_id,
            cursor=cursor,
        )

    def kuaishou_comment_replies(
        self,
        photo_id: str,
        root_comment_id: str,
        cursor: Optional[str] = None,
        count: Optional[int] = None,
    ) -> str:
        """List the replies under a Kuaishou comment.

        Replies under a root comment on a Kuaishou video, cursor-paginated via next_cursor; count sizes the page
        (1-50).

        Args:
            photo_id (str): Kuaishou photo (video) id, non-empty.
            root_comment_id (str): Id of the top-level comment whose replies you want, from video_comments.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.
            count (Optional[int]): Replies per page, 1-50. Omit to use the upstream default.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.comment_replies,
            photo_id,
            root_comment_id,
            cursor=cursor,
            count=count,
        )

    def kuaishou_videos_batch(self, photo_ids: List[str]) -> str:
        """Fetch up to 20 Kuaishou videos in one call.

        Several Kuaishou videos in one call, hard-capped at 20 photo ids.

        Args:
            photo_ids (List[str]): Kuaishou photo (video) ids, 1-20 per call; more than 20 is rejected.

        Returns:
            str: JSON string of the API response. Costs 40 credits. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.videos_batch,
            photo_ids,
        )

    def kuaishou_search(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Kuaishou across all result types.

        Mixed-result search across Kuaishou, cursor-paginated via next_cursor.

        Args:
            keyword (str): Search keyword, 1-200 characters.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.

        Returns:
            str: JSON string of the API response. Costs 10 credits. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.search,
            keyword,
            cursor=cursor,
        )

    def kuaishou_search_videos(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Kuaishou videos.

        Kuaishou video search results, cursor-paginated via next_cursor.

        Args:
            keyword (str): Search keyword, 1-200 characters.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.

        Returns:
            str: JSON string of the API response. Costs 10 credits. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.search_videos,
            keyword,
            cursor=cursor,
        )

    def kuaishou_search_users(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Kuaishou users.

        Kuaishou user search results, cursor-paginated via next_cursor.

        Args:
            keyword (str): Search keyword, 1-200 characters.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.

        Returns:
            str: JSON string of the API response. Costs 10 credits. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.search_users,
            keyword,
            cursor=cursor,
        )

    def kuaishou_search_live(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Kuaishou live streams.

        Kuaishou live-stream search results, cursor-paginated via next_cursor.

        Args:
            keyword (str): Search keyword, 1-200 characters.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.

        Returns:
            str: JSON string of the API response. Costs 10 credits. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.search_live,
            keyword,
            cursor=cursor,
        )

    def kuaishou_tag_feed(self, tag: str, cursor: Optional[str] = None) -> str:
        """List the posts under a Kuaishou hashtag.

        Posts under a Kuaishou hashtag, cursor-paginated via next_cursor.

        Args:
            tag (str): Hashtag text without the leading '#', 1-200 characters.
            cursor (Optional[str]): Opaque next_cursor from a prior response; omit for the first page.

        Returns:
            str: JSON string of the API response. Costs 1 credit. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.tag_feed,
            tag,
            cursor=cursor,
        )

    def kuaishou_trending(self, board: Optional[str] = None) -> str:
        """Get a Kuaishou leaderboard.

        Kuaishou hot / live / shopping / brand / music leaderboards. One board per call, not paginated.

        Args:
            board (Optional[str]): Leaderboard to return; defaults to 'hot' when omitted. One of: "hot", "live",
                "shopping", "brand", "music".

        Returns:
            str: JSON string of the API response. Costs 1 credit. Kuaishou is priced PER ENDPOINT (1, 2, 10 or 40),
            never per platform.
        """
        return self._call(
            self.client.kuaishou.trending,
            board=board,
        )

    # -------------------------------------------------------------------- eBay

    def ebay_search(
        self,
        query: Optional[str] = None,
        seller: Optional[str] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        condition: Optional[str] = None,
        buying_format: Optional[str] = None,
        free_shipping: Optional[bool] = None,
        sold: Optional[bool] = None,
        category_id: Optional[str] = None,
        per_page: Optional[int] = None,
    ) -> str:
        """Search live or SOLD eBay listings.

        Search live or SOLD eBay listings: price, condition, bids, shipping, seller, feedback. Provide query or
        seller; per_page accepts only 60, 120 or 240.

        Args:
            query (Optional[str]): Keyword to search (1-500 characters). Optional: a seller-only search pages that
                seller's whole catalogue.
            seller (Optional[str]): Restrict results to one seller's listings (1-64 characters), as in
                ebay.com/usr/<name>. Can be sent with no query.
            page (Optional[int]): Results page, 1-based.
            sort_by (Optional[str]): Result sort order. Defaults to 'best_match'. eBay's 'Distance: nearest first'
                is deliberately unsupported (it ranks against our proxy exit, not the caller). One of: "best_match",
                "ending_soonest", "newly_listed", "price_low", "price_high".
            min_price (Optional[float]): Minimum price, inclusive. Must be 0 or greater.
            max_price (Optional[float]): Maximum price, inclusive. Must be 0 or greater.
            condition (Optional[str]): Item condition filter. 'refurbished' is eBay's parent condition, not one of
                its three graded tiers. One of: "new", "open_box", "refurbished", "used", "for_parts".
            buying_format (Optional[str]): Listing format: auction, fixed price (buy_it_now), or fixed price
                accepting offers (best_offer).
            free_shipping (Optional[bool]): Only listings with free shipping.
            sold (Optional[bool]): Search completed listings that actually SOLD, for price research. eBay
                publishes no headline count on this view, so total_results is null.
            category_id (Optional[str]): eBay category id; must be numeric (e.g. '112529'). An unrecognised id
                returns the UNFILTERED set under a 200.
            per_page (Optional[int]): Listings per page: 60, 120 or 240 only. Defaults to 60; eBay silently falls
                back to 60 for anything else.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.ebay.search,
            query=query,
            seller=seller,
            page=page,
            sort_by=sort_by,
            min_price=min_price,
            max_price=max_price,
            condition=condition,
            buying_format=buying_format,
            free_shipping=free_shipping,
            sold=sold,
            category_id=category_id,
            per_page=per_page,
        )

    def ebay_product(self, item_id: str) -> str:
        """Get one eBay listing in full.

        One eBay listing in full: price, condition, images, item specifics, shipping, returns, auction state, seller.

        Args:
            item_id (str): eBay item number (e.g. '168591664725'), or a full ebay.com/itm/... listing URL;
                tracking parameters on a pasted URL are discarded.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.ebay.product,
            item_id,
        )

    def ebay_seller(self, seller: str) -> str:
        """Get an eBay seller's profile card.

        eBay seller profile card: store name, feedback score and %, items sold, followers, location, categories.
        Profile only: page a catalogue with ebay_search(seller=...).

        Args:
            seller (str): eBay username as it appears in ebay.com/usr/<name> (1-64 characters), which is what
                seller_name on a search or product result returns.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.ebay.seller,
            seller,
        )

    # ------------------------------------------------------------------ Target

    def target_search(
        self,
        keyword: str,
        page: Optional[int] = None,
        count: Optional[int] = None,
        sort: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> str:
        """Search Target.com.

        Search Target.com, the US retailer: prices, ratings, badges and promotions. Up to 28 results per page;
        rendered upstream, so expect around 9 seconds.

        Args:
            keyword (str): Search keyword (1-500 characters).
            page (Optional[int]): Results page, 1-based.
            count (Optional[int]): Results per page, 1-28. Defaults to 24; Target rejects anything above 28
                outright.
            sort (Optional[str]): Result sort order. Defaults to 'relevance'. One of: "relevance", "featured",
                "price_low", "price_high", "rating_high", "best_seller", "newest".
            store_id (Optional[str]): Numeric Target store id whose prices and availability the response reflects.
                Defaults to '3991', the store target.com uses with no store context.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.target.search,
            keyword,
            page=page,
            count=count,
            sort=sort,
            store_id=store_id,
        )

    def target_category(
        self,
        category_id: str,
        page: Optional[int] = None,
        count: Optional[int] = None,
        sort: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> str:
        """List the products in a Target category.

        Products in a Target category, same shape as search plus the category breadcrumb. Up to 28 per page; the
        slowest Target endpoint at around 37 seconds.

        Args:
            category_id (str): Target category id: the segment after 'N-' in a target.com /c/ URL
                (target.com/c/apple/-/N-5xtg6 -> '5xtg6').
            page (Optional[int]): Results page, 1-based.
            count (Optional[int]): Results per page, 1-28. Defaults to 24; Target rejects anything above 28
                outright.
            sort (Optional[str]): Result sort order. Defaults to 'relevance'. One of: "relevance", "featured",
                "price_low", "price_high", "rating_high", "best_seller", "newest".
            store_id (Optional[str]): Numeric Target store id whose prices and availability the response reflects.
                Defaults to '3991'.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.target.category,
            category_id,
            page=page,
            count=count,
            sort=sort,
            store_id=store_id,
        )

    def target_product(self, tcin: str, store_id: Optional[str] = None) -> str:
        """Get a Target product by TCIN.

        Target product details by TCIN: price, rating, images, specifications, variants, return policy, fulfillment.
        seller_id/seller_name are null for stock sold by Target.

        Args:
            tcin (str): Target catalog id (tcin, e.g. '1010453160'). A colour/size child tcin is answered by its
                variation parent, with the child present in 'variants'.
            store_id (Optional[str]): Numeric Target store id whose prices and availability the response reflects.
                Defaults to '3991'.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.target.product,
            tcin,
            store_id=store_id,
        )

    def target_reviews(
        self,
        tcin: str,
        limit: Optional[int] = None,
        store_id: Optional[str] = None,
    ) -> str:
        """Get the reviews for a Target product.

        Target reviews with the rating breakdown, per-attribute averages and guest photos. 8 review bodies maximum and
        no paging; expect around 40 seconds.

        Args:
            tcin (str): Target catalog id (tcin, e.g. '1010453160').
            limit (Optional[int]): Trim the returned reviews to at most this many (1 or greater). Target publishes
                8 anonymously and offers no paging, so this only trims.
            store_id (Optional[str]): Numeric Target store id whose prices and availability the response reflects.
                Defaults to '3991'.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.target.reviews,
            tcin,
            limit=limit,
            store_id=store_id,
        )

    # -------------------------------------------------------------- Home Depot

    def home_depot_search(
        self,
        query: str,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
    ) -> str:
        """Search Home Depot.

        Search Home Depot: price and promotions, brand and model, ratings, badges, per-store pickup/delivery. Page
        size is fixed at 12 and cannot be changed.

        Args:
            query (str): Search keyword (1-500 characters).
            page (Optional[int]): Results page, 1-based. Home Depot serves 12 products per page and offers no way
                to change that, so paging is the only way to read further.
            sort_by (Optional[str]): Result sort order. Defaults to 'best_match'. Closed enum: Home Depot answers
                an unknown sort with an empty page that is still billed. 'Newest' is absent - it is rejected on
                keyword search. One of: "best_match", "top_sellers", "top_rated", "price_low", "price_high".
            min_price (Optional[float]): Minimum price, inclusive. Must be 0 or greater.
            max_price (Optional[float]): Maximum price, inclusive. Must be 0 or greater.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.home_depot.search,
            query,
            page=page,
            sort_by=sort_by,
            min_price=min_price,
            max_price=max_price,
        )

    def home_depot_product(self, item_id: str) -> str:
        """Get a Home Depot item in full.

        Full Home Depot item detail: pricing, images and videos, spec table, dimensions, bullets, documents, return
        policy. Carries a 10-review preview only.

        Args:
            item_id (str): Home Depot item id (e.g. '325479354'), or a full homedepot.com/p/... product URL;
                tracking parameters on a pasted URL are discarded.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.home_depot.product,
            item_id,
        )

    def home_depot_reviews(self, item_id: str, page: Optional[int] = None) -> str:
        """Get a page of Home Depot reviews.

        One page of full Home Depot review bodies, the rating distribution, per-attribute ratings, photos and seller
        responses. 30 reviews per page.

        Args:
            item_id (str): Home Depot item id (e.g. '325479354'), or a full homedepot.com/p/... product URL;
                tracking parameters on a pasted URL are discarded.
            page (Optional[int]): Reviews page, 1-based. 30 reviews per page; 'total_pages' in the response is the
                last one that exists, and asking past it is a 404.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.home_depot.reviews,
            item_id,
            page=page,
        )

    # ------------------------------------------------------------------ Zillow

    def zillow_search(
        self,
        location: str,
        listing_status: Optional[str] = None,
        page: Optional[int] = None,
        sort: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        beds_min: Optional[int] = None,
        beds_max: Optional[int] = None,
        baths_min: Optional[float] = None,
        baths_max: Optional[float] = None,
        sqft_min: Optional[int] = None,
        sqft_max: Optional[int] = None,
        lot_size_min: Optional[int] = None,
        lot_size_max: Optional[int] = None,
        year_built_min: Optional[int] = None,
        year_built_max: Optional[int] = None,
        max_hoa: Optional[float] = None,
        home_type: Optional[str] = None,
        days_on_zillow: Optional[str] = None,
        keywords: Optional[str] = None,
        has_pool: Optional[bool] = None,
        has_garage: Optional[bool] = None,
        has_air_conditioning: Optional[bool] = None,
        is_waterfront: Optional[bool] = None,
        has_basement: Optional[bool] = None,
        is_new_construction: Optional[bool] = None,
        has_open_house: Optional[bool] = None,
        price_reduced: Optional[bool] = None,
        is_3d_tour: Optional[bool] = None,
    ) -> str:
        """Search Zillow listings in a region.

        Zillow listings in a region: price, beds, baths, living area, Zestimate, coordinates, images, days on market.
        A bare ZIP works alone but cannot be combined with a filter or a sort.

        Args:
            location (str): Region to search (1-200 characters): a Zillow slug ('austin-tx'), a human form
                ('Austin, TX'), a ZIP, or a pasted zillow.com search URL. A ZIP works alone but cannot be combined
                with a filter or sort; an unresolvable region is a 404.
            listing_status (Optional[str]): Which listings to return. Defaults to 'for_sale'. One of: "for_sale",
                "for_rent", "sold".
            page (Optional[int]): Results page, 1-based.
            sort (Optional[str]): Result sort order. Sorts that rank against a signed-in profile
                (saved/featured/personalised) are unsupported - we are never signed in. One of: "relevance",
                "recommended", "newest", "price_low", "price_high", "payment_low", "payment_high", "beds", "baths",
                "sqft", "lot_size", "zestimate_low", "zestimate_high", "recent_change".
            min_price (Optional[float]): Minimum price, inclusive (0 or greater). On listing_status='for_rent'
                this is MONTHLY RENT - Zillow files rent under its payment filter.
            max_price (Optional[float]): Maximum price, inclusive (0 or greater). On listing_status='for_rent'
                this is MONTHLY RENT.
            beds_min (Optional[int]): Minimum bedrooms; whole number, 0 or greater.
            beds_max (Optional[int]): Maximum bedrooms; whole number, 0 or greater.
            baths_min (Optional[float]): Minimum bathrooms, 0 or greater. Half-baths are allowed (1.5).
            baths_max (Optional[float]): Maximum bathrooms, 0 or greater. Half-baths are allowed (1.5).
            sqft_min (Optional[int]): Minimum living area in square feet; whole number, 0 or greater.
            sqft_max (Optional[int]): Maximum living area in square feet; whole number, 0 or greater.
            lot_size_min (Optional[int]): Minimum lot size in square feet; whole number, 0 or greater.
            lot_size_max (Optional[int]): Maximum lot size in square feet; whole number, 0 or greater.
            year_built_min (Optional[int]): Earliest year built; whole number, 0 or greater.
            year_built_max (Optional[int]): Latest year built; whole number, 0 or greater.
            max_hoa (Optional[float]): Maximum monthly HOA fee in dollars, 0 or greater.
            home_type (Optional[str]): Property type filter. One of: "houses", "townhomes", "multi_family",
                "condos", "apartments", "manufactured", "lots_land".
            days_on_zillow (Optional[str]): Listed - or, with listing_status='sold', sold - within the last N
                days. Closed enum: an unrecognised value returns the UNFILTERED set under a 200. One of: "1", "7",
                "14", "30", "90", "6m", "12m", "24m", "36m".
            keywords (Optional[str]): Free-text match against the listing description (1-200 characters).
            has_pool (Optional[bool]): Only listings with a pool.
            has_garage (Optional[bool]): Only listings with a garage.
            has_air_conditioning (Optional[bool]): Only listings with air conditioning.
            is_waterfront (Optional[bool]): Only waterfront listings.
            has_basement (Optional[bool]): Only listings with a basement.
            is_new_construction (Optional[bool]): Only new-construction listings.
            has_open_house (Optional[bool]): Only listings with an upcoming open house.
            price_reduced (Optional[bool]): Only listings whose price was reduced.
            is_3d_tour (Optional[bool]): Only listings with a 3D tour.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.zillow.search,
            location,
            listing_status=listing_status,
            page=page,
            sort=sort,
            min_price=min_price,
            max_price=max_price,
            beds_min=beds_min,
            beds_max=beds_max,
            baths_min=baths_min,
            baths_max=baths_max,
            sqft_min=sqft_min,
            sqft_max=sqft_max,
            lot_size_min=lot_size_min,
            lot_size_max=lot_size_max,
            year_built_min=year_built_min,
            year_built_max=year_built_max,
            max_hoa=max_hoa,
            home_type=home_type,
            days_on_zillow=days_on_zillow,
            keywords=keywords,
            has_pool=has_pool,
            has_garage=has_garage,
            has_air_conditioning=has_air_conditioning,
            is_waterfront=is_waterfront,
            has_basement=has_basement,
            is_new_construction=is_new_construction,
            has_open_house=has_open_house,
            price_reduced=price_reduced,
            is_3d_tour=is_3d_tour,
        )

    def zillow_property(self, zpid: str) -> str:
        """Get a Zillow listing in full.

        Full Zillow listing: price and price history, Zestimate, tax history, RESO facts, rooms, schools, open houses,
        photos. Rental buildings return floor plans instead.

        Args:
            zpid (str): Zillow property id (e.g. '29414894'), a full /homedetails/ URL, or a rental building URL
                (zillow.com/apartments/...). The building form is required for buildings: they have no zpid a caller
                can see.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.zillow.property,
            zpid,
        )

    def zillow_agent_reviews(self, screen_name: str) -> str:
        """Get a Zillow AGENT's profile and reviews.

        A Zillow AGENT's profile and reviews: rating, bodies with sub-ratings, specialties, licenses, service areas,
        sales counts. Zillow server-renders the first five.

        Args:
            screen_name (str): Zillow agent profile screen name as it appears in zillow.com/profile/<name>/ (1-200
                characters, may contain spaces), or a full profile URL.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.zillow.agent_reviews,
            screen_name,
        )

    # ------------------------------------------------------------- Booking.com

    def booking_search(
        self,
        destination: Optional[str] = None,
        dest_id: Optional[str] = None,
        dest_type: Optional[str] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        stars: Optional[List[int]] = None,
        min_review_score: Optional[str] = None,
        property_type: Optional[str] = None,
        free_cancellation: Optional[bool] = None,
        no_prepayment: Optional[bool] = None,
        breakfast_included: Optional[bool] = None,
        checkin: Optional[str] = None,
        checkout: Optional[str] = None,
        adults: Optional[int] = None,
        children_ages: Optional[List[int]] = None,
        rooms: Optional[int] = None,
        currency: Optional[str] = None,
    ) -> str:
        """Search Booking.com properties for a destination and stay.

        Booking.com properties for a destination and stay: live nightly price, review score, star rating, location,
        room type, deal badges. 25 properties per page. Provide destination or dest_id.

        Args:
            destination (Optional[str]): Destination to search, e.g. 'Paris' (1-200 characters). Required unless
                dest_id is given.
            dest_id (Optional[str]): Numeric Booking.com destination id, as an alternative to destination.
            dest_type (Optional[str]): What dest_id refers to. Requires dest_id and is rejected without it,
                because Booking silently ignores a lone dest_type. One of: "city", "region", "country", "district",
                "landmark", "airport", "hotel".
            page (Optional[int]): Results page, 1-based. 25 properties per page, 1 credit each.
            sort_by (Optional[str]): Result sort order (default 'popularity'). One of: "popularity", "price_low",
                "price_high", "stars_high", "stars_low", "stars_and_price", "distance", "review_score".
            min_price (Optional[float]): Minimum price PER NIGHT in `currency`, >= 0. Must not exceed max_price.
            max_price (Optional[float]): Maximum price PER NIGHT in `currency`, >= 0.
            stars (Optional[List[int]]): Star ratings to include, each 1-5, 1-5 values, OR'd together (e.g. [4,
                5]).
            min_review_score (Optional[str]): Minimum guest review score. Only '6', '7', '8' and '9' exist
                upstream; any other threshold is silently dropped.
            property_type (Optional[str]): Accommodation type by name. One of: apartments, hostels, hotels,
                motels, resorts, bed_and_breakfasts, villas, campgrounds, vacation_homes, lodges, homestays.
            free_cancellation (Optional[bool]): Only properties offering free cancellation.
            no_prepayment (Optional[bool]): Only properties that take no prepayment.
            breakfast_included (Optional[bool]): Only rates that include breakfast.
            checkin (Optional[str]): Check-in date, YYYY-MM-DD. Must be sent together with checkout: a lone
                checkin is ignored and Booking prices a default range of its own.
            checkout (Optional[str]): Check-out date, YYYY-MM-DD. Must be later than checkin and sent together
                with it.
            adults (Optional[int]): Adult guests, >= 1 (default 2).
            children_ages (Optional[List[int]]): AGES of accompanying children, each 0-17, max 10 entries. Ages,
                not a count.
            rooms (Optional[int]): Rooms required, >= 1 (default 1).
            currency (Optional[str]): ISO 4217 currency for prices, 3 letters (default 'USD'). Without it Booking
                prices off the proxy exit and identical requests disagree.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.booking.search,
            destination=destination,
            dest_id=dest_id,
            dest_type=dest_type,
            page=page,
            sort_by=sort_by,
            min_price=min_price,
            max_price=max_price,
            stars=stars,
            min_review_score=min_review_score,
            property_type=property_type,
            free_cancellation=free_cancellation,
            no_prepayment=no_prepayment,
            breakfast_included=breakfast_included,
            checkin=checkin,
            checkout=checkout,
            adults=adults,
            children_ages=children_ages,
            rooms=rooms,
            currency=currency,
        )

    def booking_hotel(
        self,
        hotel: str,
        country_code: Optional[str] = None,
        checkin: Optional[str] = None,
        checkout: Optional[str] = None,
        adults: Optional[int] = None,
        children_ages: Optional[List[int]] = None,
        rooms: Optional[int] = None,
        currency: Optional[str] = None,
    ) -> str:
        """Get one Booking.com property in full.

        One Booking.com property in full: rooms and rate plans, facilities, house rules, check-in windows, policies,
        images, location and review scores, priced for the stay asked for. Chaining the `url` a search row returns is
        cheaper than a bare slug.

        Args:
            hotel (str): Booking.com property URL or the bare page slug (1-500 characters); query params are
                discarded.
            country_code (Optional[str]): Two-letter country code for the property page (default 'us'). Only
                consulted for a bare slug, where a wrong one is a real, BILLED 404.
            checkin (Optional[str]): Check-in date, YYYY-MM-DD. Must be sent together with checkout; omitting both
                prices a two-night range Booking chose, echoed back in the response.
            checkout (Optional[str]): Check-out date, YYYY-MM-DD. Must be later than checkin and sent together
                with it.
            adults (Optional[int]): Adult guests, >= 1 (default 2).
            children_ages (Optional[List[int]]): AGES of accompanying children, each 0-17, max 10 entries. Ages,
                not a count.
            rooms (Optional[int]): Rooms required, >= 1 (default 1).
            currency (Optional[str]): ISO 4217 currency for prices, 3 letters (default 'USD'). Without it Booking
                prices off the proxy exit and identical requests disagree.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.booking.hotel,
            hotel,
            country_code=country_code,
            checkin=checkin,
            checkout=checkout,
            adults=adults,
            children_ages=children_ages,
            rooms=rooms,
            currency=currency,
        )

    def booking_reviews(
        self,
        hotel: str,
        country_code: Optional[str] = None,
        checkin: Optional[str] = None,
        checkout: Optional[str] = None,
        adults: Optional[int] = None,
        children_ages: Optional[List[int]] = None,
        rooms: Optional[int] = None,
        currency: Optional[str] = None,
    ) -> str:
        """Get Booking.com guest reviews for a property.

        Booking.com guest reviews for a property with the score breakdown by category and Booking's own
        praise/complaint summary. No page param: total_count is the whole review history, count is what this response
        holds.

        Args:
            hotel (str): Booking.com property URL or the bare page slug (1-500 characters); query params are
                discarded.
            country_code (Optional[str]): Two-letter country code for the property page (default 'us'). Only
                consulted for a bare slug, where a wrong one is a real, BILLED 404.
            checkin (Optional[str]): Check-in date, YYYY-MM-DD. Must be sent together with checkout; it prices the
                stay the review page is rendered for.
            checkout (Optional[str]): Check-out date, YYYY-MM-DD. Must be later than checkin and sent together
                with it.
            adults (Optional[int]): Adult guests, >= 1 (default 2).
            children_ages (Optional[List[int]]): AGES of accompanying children, each 0-17, max 10 entries. Ages,
                not a count.
            rooms (Optional[int]): Rooms required, >= 1 (default 1).
            currency (Optional[str]): ISO 4217 currency for prices, 3 letters (default 'USD').

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.booking.reviews,
            hotel,
            country_code=country_code,
            checkin=checkin,
            checkout=checkout,
            adults=adults,
            children_ages=children_ages,
            rooms=rooms,
            currency=currency,
        )

    # ------------------------------------------------------------- TripAdvisor
    #
    # TripAdvisor is LOOKUP-FIRST: every other call is keyed by the geo_id / location_id pair that
    # tripadvisor_locations returns, so start there rather than guessing an id.

    def tripadvisor_locations(self, query: str, limit: Optional[int] = None) -> str:
        """Resolve a place or business name to TripAdvisor ids.

        START HERE: resolve a place or business NAME to the TripAdvisor geo_id / location_id pair every other
        TripAdvisor endpoint is keyed by. Up to 20 rows.

        Args:
            query (str): Place or business name to resolve (1-120 characters).
            limit (Optional[int]): Rows to return, 1-20 (default 12). Sizes the response only; there is no paging
                here.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.tripadvisor.locations,
            query,
            limit=limit,
        )

    def tripadvisor_search(
        self,
        geo_id: Optional[str] = None,
        category: Optional[str] = None,
        page: Optional[int] = None,
        url: Optional[str] = None,
    ) -> str:
        """List restaurants, hotels or attractions in a TripAdvisor geo.

        Restaurants, hotels or attractions in a TripAdvisor geo, TripAdvisor-ranked: rating, review count, price band,
        address, coordinates, phone, hours, Travelers' Choice badge; each row carries the location_id + geo_id pair.
        30 locations per page. Provide geo_id or url.

        Args:
            geo_id (Optional[str]): TripAdvisor geo id (1-500 characters): 30196, g30196, or a URL carrying one.
                Required unless url is given.
            category (Optional[str]): Listing family to search (default 'restaurants'). One of: "restaurants",
                "hotels", "attractions".
            page (Optional[int]): Results page, 1-based. 30 locations per page; a page beyond the last is a 404,
                not an empty result.
            url (Optional[str]): Full tripadvisor.com listing URL (1-500 characters), as an alternative to geo_id;
                country sites are accepted.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.tripadvisor.search,
            geo_id=geo_id,
            category=category,
            page=page,
            url=url,
        )

    def tripadvisor_location(
        self,
        location_id: Optional[str] = None,
        geo_id: Optional[str] = None,
        category: Optional[str] = None,
        url: Optional[str] = None,
    ) -> str:
        """Get one TripAdvisor location in full.

        One TripAdvisor location in full: rating, review histogram and per-aspect sub-ratings, city ranking, price
        band, cuisines, amenities, address, coordinates, contact, photos, and the FIRST PAGE OF REVIEWS. Provide
        location_id or url.

        Args:
            location_id (Optional[str]): TripAdvisor location id (1-500 characters): 1899234, d1899234, or a full
                _Review URL. Required unless url is given.
            geo_id (Optional[str]): Geo the location sits in; required when location_id is a bare d-id.
            category (Optional[str]): Location family (default 'restaurants'); match the location's own type. One
                of: "restaurants", "hotels", "attractions".
            url (Optional[str]): Full tripadvisor.com _Review URL (1-500 characters), as an alternative to
                location_id.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.tripadvisor.location,
            location_id=location_id,
            geo_id=geo_id,
            category=category,
            url=url,
        )

    def tripadvisor_reviews(
        self,
        location_id: Optional[str] = None,
        geo_id: Optional[str] = None,
        category: Optional[str] = None,
        url: Optional[str] = None,
        page: Optional[int] = None,
    ) -> str:
        """Get a page of TripAdvisor reviews.

        A page of TripAdvisor reviews: rating, trip date and type, reviewer home town and contribution count,
        management response. Page 1 already rides along in tripadvisor_location(), so use this to page PAST it;
        consecutive pages can repeat one review at the boundary, so de-duplicate on review_id. Provide location_id or
        url.

        Args:
            location_id (Optional[str]): TripAdvisor location id (1-500 characters): 1899234, d1899234, or a full
                _Review URL. Required unless url is given.
            geo_id (Optional[str]): Geo the location sits in; required when location_id is a bare d-id.
            category (Optional[str]): Location family (default 'restaurants'). It sets the page size, so it must
                match the location's own type on any page past the first. One of: "restaurants", "hotels",
                "attractions".
            url (Optional[str]): Full tripadvisor.com _Review URL (1-500 characters), as an alternative to
                location_id.
            page (Optional[int]): Reviews page, 1-based. 15 per page for restaurants, 10 for hotels and
                attractions; past the last page is a 404.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.tripadvisor.reviews,
            location_id=location_id,
            geo_id=geo_id,
            category=category,
            url=url,
            page=page,
        )

    # ------------------------------------------------------------------ Indeed

    def indeed_search(
        self,
        query: Optional[str] = None,
        location: Optional[str] = None,
        page: Optional[int] = None,
        radius: Optional[int] = None,
        max_age_days: Optional[int] = None,
        job_type: Optional[str] = None,
        min_salary: Optional[float] = None,
        remote: Optional[bool] = None,
    ) -> str:
        """Search Indeed job postings.

        Indeed job postings: title, employer, rating, location, salary range, job type, benefits, posting age, apply
        route. 10 postings per page. Provide query or location - a location-only search (every posting in a metro) is
        valid.

        Args:
            query (Optional[str]): Job title, keywords or employer (1-500 characters). Required unless location is
                given.
            location (Optional[str]): City and state, postal code, state, country, or 'Remote' (1-200 characters).
                Valid on its own with no query.
            page (Optional[int]): Results page, 1-based. 10 postings per page, 1 call each.
            radius (Optional[int]): Search radius in miles around location. Closed set: Indeed IGNORES any other
                value and returns the unfiltered set. Upstream default 50. One of: 0, 5, 10, 15, 25, 35, 50, 100.
            max_age_days (Optional[int]): Maximum posting age in days. Closed set: Indeed IGNORES any other value
                and returns postings of every age. One of: 1, 3, 7, 14.
            job_type (Optional[str]): Employment type filter. One of: "full_time", "part_time", "contract",
                "temporary", "internship".
            min_salary (Optional[float]): Minimum annual salary, >= 0. Filters on INDEED'S OWN ESTIMATE for the
                role, not a posted figure, so postings publishing no salary still match.
            remote (Optional[bool]): Remote postings only.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.indeed.search,
            query=query,
            location=location,
            page=page,
            radius=radius,
            max_age_days=max_age_days,
            job_type=job_type,
            min_salary=min_salary,
            remote=remote,
        )

    def indeed_job(self, job_id: str) -> str:
        """Get one Indeed posting in full.

        One Indeed posting in full: description text and HTML, structured salary, employment types, benefits, geocoded
        address, employer rating, applicant count, original ATS link. An unknown job key is a real 404 that is still
        billed.

        Args:
            job_id (str): 16-hex Indeed job key, or any indeed.com URL carrying jk= (/viewjob, /rc/clk,
                /pagead/clk).

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.indeed.job,
            job_id,
        )

    def indeed_company(self, company: str) -> str:
        """Get an Indeed employer profile.

        Indeed employer profile: description, industry, HQ, size, revenue, CEO approval, overall and per-category
        ratings, reported salaries, open roles, locations. An unknown slug is a real 404 that is still billed.

        Args:
            company (str): indeed.com/cmp/<slug> slug or a full profile URL (1-200 characters); slugs are untidy,
                e.g. 'Tata-Consultancy-Services-(tcs)'.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.indeed.company,
            company,
        )

    def indeed_company_reviews(self, company: str, page: Optional[int] = None) -> str:
        """Get a page of Indeed employee reviews.

        Indeed employee reviews, 20 per page, with per-category ratings, pros/cons, reviewer job title and location,
        plus aggregated sentiment and topic/location/job-title breakdowns.

        Args:
            company (str): indeed.com/cmp/<slug> slug or a full profile URL (1-200 characters).
            page (Optional[int]): Reviews page, 1-based. 20 reviews per page.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.indeed.company_reviews,
            company,
            page=page,
        )

    # ------------------------------------------------------------------ Airbnb

    def airbnb_search(
        self,
        location: str,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        adults: Optional[int] = None,
        children: Optional[int] = None,
        infants: Optional[int] = None,
        pets: Optional[int] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        room_type: Optional[str] = None,
        min_bedrooms: Optional[int] = None,
        min_beds: Optional[int] = None,
        min_bathrooms: Optional[int] = None,
        superhost: Optional[bool] = None,
        instant_book: Optional[bool] = None,
        guest_favorite: Optional[bool] = None,
        free_cancellation: Optional[bool] = None,
        amenities: Optional[str] = None,
        currency: Optional[str] = None,
        page: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Search Airbnb stays.

        Airbnb stays: stay-total and per-night price with the full discount ledger, rating and review count,
        bedrooms/beds/baths, coordinates, badges, images, dates_are_defaulted. 18 listings per page; page and cursor
        are mutually exclusive.

        Args:
            location (str): City, region, ZIP, or a pasted airbnb.com/s/ URL (1-200 characters). An unresolvable
                location is a 404.
            check_in (Optional[str]): Check-in date, YYYY-MM-DD. Must be sent with check_out; omitting both
                defaults to +30 days and flags dates_are_defaulted in the response.
            check_out (Optional[str]): Check-out date, YYYY-MM-DD. Must be later than check_in; defaults to
                check_in plus 5 nights when omitted.
            adults (Optional[int]): Adult guests, >= 1.
            children (Optional[int]): Children aged 2-12, >= 0.
            infants (Optional[int]): Infants under 2, >= 0.
            pets (Optional[int]): Pets, >= 0.
            min_price (Optional[float]): Minimum price for the WHOLE STAY in `currency`, not per night, >= 0. Must
                not exceed max_price.
            max_price (Optional[float]): Maximum price for the WHOLE STAY in `currency`, not per night, >= 0.
            room_type (Optional[str]): Room type. Validated before the scrape, because an unrecognised value
                returns the UNFILTERED set under a 200. One of: "entire_home", "private_room", "shared_room",
                "hotel_room".
            min_bedrooms (Optional[int]): Minimum bedrooms, >= 0.
            min_beds (Optional[int]): Minimum beds, >= 0.
            min_bathrooms (Optional[int]): Minimum bathrooms, >= 0.
            superhost (Optional[bool]): Superhost listings only.
            instant_book (Optional[bool]): Instant Book listings only.
            guest_favorite (Optional[bool]): Guest Favorite listings only.
            free_cancellation (Optional[bool]): Listings with free cancellation only.
            amenities (Optional[str]): Comma-separated amenities (1-200 characters): wifi, air_conditioning, pool,
                kitchen, free_parking, washer, self_check_in, tv, or raw numeric Airbnb amenity ids. An unrecognised
                NAME is rejected before the scrape.
            currency (Optional[str]): ISO 4217 currency for prices, 3 letters (default 'USD'). Without it Airbnb
                prices off the proxy exit and identical requests disagree.
            page (Optional[int]): Results page, 1-based. 18 listings per page. Cannot be combined with cursor.
            cursor (Optional[str]): next_cursor from a previous response (1-500 characters); wins over page, so
                sending both is rejected.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.airbnb.search,
            location,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
            infants=infants,
            pets=pets,
            min_price=min_price,
            max_price=max_price,
            room_type=room_type,
            min_bedrooms=min_bedrooms,
            min_beds=min_beds,
            min_bathrooms=min_bathrooms,
            superhost=superhost,
            instant_book=instant_book,
            guest_favorite=guest_favorite,
            free_cancellation=free_cancellation,
            amenities=amenities,
            currency=currency,
            page=page,
            cursor=cursor,
        )

    def airbnb_listing(
        self,
        listing_id: str,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        adults: Optional[int] = None,
        children: Optional[int] = None,
        infants: Optional[int] = None,
        pets: Optional[int] = None,
        currency: Optional[str] = None,
    ) -> str:
        """Get one Airbnb listing in full.

        One Airbnb listing in full: description, property/room type, capacity and room counts, the complete grouped
        amenity list (including what the place does NOT have), host profile and stats, house rules, cancellation
        policy, sleeping arrangements, photo tour and the RATING BREAKDOWN. Carries NO nightly price - prices are
        search-only.

        Args:
            listing_id (str): Airbnb listing id or a full /rooms/ URL (1-500 characters); query params are
                discarded, since they carry someone else's dates.
            check_in (Optional[str]): Check-in date, YYYY-MM-DD. Must be sent with check_out. Does not produce a
                price: the room page has no nightly rate.
            check_out (Optional[str]): Check-out date, YYYY-MM-DD. Must be later than check_in and sent together
                with it.
            adults (Optional[int]): Adult guests, >= 1.
            children (Optional[int]): Children aged 2-12, >= 0.
            infants (Optional[int]): Infants under 2, >= 0.
            pets (Optional[int]): Pets, >= 0.
            currency (Optional[str]): ISO 4217 currency, 3 letters (default 'USD').

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.airbnb.listing,
            listing_id,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            children=children,
            infants=infants,
            pets=pets,
            currency=currency,
        )

    def airbnb_reviews(
        self,
        listing_id: str,
        currency: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> str:
        """Get Airbnb review bodies for a listing.

        Airbnb review BODIES with per-review rating, date and reviewer name/photo/location, limit/offset paged at up
        to 50 per call. `count` is the listing's TOTAL review count, `returned` is how many this page holds. The
        rating breakdown lives on airbnb_listing(), not here.

        Args:
            listing_id (str): Airbnb listing id or a full /rooms/ URL (1-500 characters).
            currency (Optional[str]): ISO 4217 currency, 3 letters (default 'USD').
            limit (Optional[int]): Reviews to return, 1-50 (default 30). Upstream returns a fixed 7 when no
                explicit limit is sent.
            offset (Optional[int]): Reviews to skip before this page, >= 0 (default 0).

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.airbnb.reviews,
            listing_id,
            currency=currency,
            limit=limit,
            offset=offset,
        )

    # --------------------------------------------------------------- Glassdoor
    #
    # Glassdoor is LOOKUP-FIRST: glassdoor_companies resolves a company name to the employer_id the other three are
    # keyed by.

    def glassdoor_companies(self, query: str) -> str:
        """Resolve a company name to a Glassdoor employer_id.

        START HERE. Resolve a company NAME to the employer_id every other Glassdoor method is keyed by, ranked by
        Glassdoor and de-duplicated.

        Args:
            query (str): Company name to resolve (1-120 characters).

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.glassdoor.companies,
            query,
        )

    def glassdoor_company(
        self,
        employer_id: Optional[str] = None,
        company: Optional[str] = None,
        url: Optional[str] = None,
    ) -> str:
        """Get a Glassdoor employer profile.

        Glassdoor employer profile: description, mission, industry, sector, HQ, size and revenue bands, stock symbol,
        year founded, overall and per-category ratings, star distribution, CEO approval, awards, FAQ and the five
        server-rendered reviews. Also returns reviews_url and salaries_url, which glassdoor_reviews() and
        glassdoor_salaries() accept as url to save a fetch. Provide employer_id or url.

        Args:
            employer_id (Optional[str]): Glassdoor employer id (1-50 characters) in any form Glassdoor writes it:
                '1699', 'E1699' or 'IE1699'. Must be a STRING - a JSON number is rejected.
            company (Optional[str]): Employer name as it appears in a Glassdoor slug (1-200 characters). COSMETIC:
                the profile resolves on employer_id alone, it is ignored entirely when url is set, and it does not
                satisfy the employer_id-or-url requirement.
            url (Optional[str]): Any glassdoor.com employer URL (1-500 characters): /Overview/, /Reviews/ or
                /Salary/. A non-glassdoor.com host is rejected.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.glassdoor.company,
            employer_id=employer_id,
            company=company,
            url=url,
        )

    def glassdoor_reviews(
        self,
        employer_id: Optional[str] = None,
        company: Optional[str] = None,
        url: Optional[str] = None,
        category: Optional[str] = None,
        employment_status: Optional[str] = None,
    ) -> str:
        """Get Glassdoor reviews and rating statistics.

        Up to THREE full Glassdoor reviews - the cap is Glassdoor's login wall - with per-axis scores, pros, cons,
        advice, job title, location, employment status and employer response, plus complete rating statistics, star
        distribution, aggregate pro/con highlight terms and per-job-title review counts. There is no page param: move
        the window with category and employment_status. Provide employer_id or url.

        Args:
            employer_id (Optional[str]): Glassdoor employer id (1-50 characters): '1699', 'E1699' or 'IE1699'.
                Must be a STRING - a JSON number is rejected. Addressing by id costs two upstream fetches; the
                customer price is unchanged.
            company (Optional[str]): Employer name as it appears in a Glassdoor slug (1-200 characters). COSMETIC:
                ignored when url is set, and it does not satisfy the employer_id-or-url requirement.
            url (Optional[str]): Any glassdoor.com employer URL (1-500 characters). Pass back reviews_url from
                glassdoor_company() to skip the resolve fetch. A non-glassdoor.com host is rejected.
            category (Optional[str]): Restrict to reviews Glassdoor files under one topic. Closed enum: Glassdoor
                IGNORES an unknown value and serves the unfiltered set under a 200. Read filtered_review_count on the
                response to see how many match. One of: "career_development", "compensation", "culture",
                "diversity_and_inclusion", "management", "work_life_balance".
            employment_status (Optional[str]): Restrict to one kind of employment. Closed enum for the same reason
                as category; FREELANCE is deliberately absent because it was never confirmed to change the result set.
                One of: "full_time", "part_time", "contract", "intern".

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.glassdoor.reviews,
            employer_id=employer_id,
            company=company,
            url=url,
            category=category,
            employment_status=employment_status,
        )

    def glassdoor_salaries(
        self,
        employer_id: Optional[str] = None,
        company: Optional[str] = None,
        url: Optional[str] = None,
        page: Optional[int] = None,
    ) -> str:
        """Get Glassdoor salary estimates by job title.

        Glassdoor salaries by job title, 10 titles per page: base-pay and total-pay percentiles P10-P90 with medians
        called out, sample counts, currency, pay period and last-reported date. The figures are Glassdoor's ESTIMATES
        for the title, not individual reported salaries. Provide employer_id or url.

        Args:
            employer_id (Optional[str]): Glassdoor employer id (1-50 characters): '1699', 'E1699' or 'IE1699'.
                Must be a STRING - a JSON number is rejected. Addressing by id costs two upstream fetches; the
                customer price is unchanged.
            company (Optional[str]): Employer name as it appears in a Glassdoor slug (1-200 characters). COSMETIC:
                ignored when url is set, and it does not satisfy the employer_id-or-url requirement.
            url (Optional[str]): Any glassdoor.com employer URL (1-500 characters). Pass back salaries_url from
                glassdoor_company() to skip the resolve fetch. A non-glassdoor.com host is rejected.
            page (Optional[int]): Results page, 1-based. Ten job titles per page; page_count on the response is
                how many pages exist.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.glassdoor.salaries,
            employer_id=employer_id,
            company=company,
            url=url,
            page=page,
        )

    # -------------------------------------------------------------------- Yelp

    def yelp_search(
        self,
        term: Optional[str] = None,
        location: Optional[str] = None,
        page: Optional[int] = None,
        sort: Optional[str] = None,
        price: Optional[List[int]] = None,
        open_now: Optional[bool] = None,
        attributes: Optional[List[str]] = None,
        url: Optional[str] = None,
    ) -> str:
        """Search Yelp businesses.

        Businesses in Yelp's ranked order: rating, review count, price band, categories, address, contact rails,
        hours, photos and a review snippet; every row carries both business_id and alias. Yelp fixes the page size at
        10. Provide term and location, or url.

        Args:
            term (Optional[str]): What to look for (1-200 characters): a category ('plumbers'), a dish, or a
                business name. Required together with location unless url is given.
            location (Optional[str]): Where to look (1-200 characters): city and region, a full address, or a
                postcode. Effectively required - Yelp geolocates a location-less search off the proxy exit, so the
                same request answers about a different metro run to run.
            page (Optional[int]): Results page, 1-based. Yelp fixes the page size at 10.
            sort (Optional[str]): Result ordering (upstream default 'recommended'). Closed enum: Yelp IGNORES an
                unrecognised sortby and serves default ranking under a 200, billing a premium scrape for a sort that
                never ran. One of: "recommended", "rating", "review_count".
            price (Optional[List[int]]): Price bands to include, 1 ($) to 4 ($$$$); 1-4 values, combined freely -
                [1, 2] means $ or $$.
            open_now (Optional[bool]): Only businesses open at the moment of the request.
            attributes (Optional[List[str]]): Raw Yelp filter aliases, max 20, each 1-100 characters
                ('RestaurantsDelivery', 'GoodForKids', 'WheelchairAccessible'). A deliberate PASSTHROUGH, not an enum
                - Yelp's vocabulary runs to ~117 values per vertical and an alias it does not know is ignored
                upstream, returning unfiltered results.
            url (Optional[str]): A full yelp.com/search URL (1-1000 characters) as an alternative to term +
                location; the query, offset and sort are read out of it and the URL is rebuilt.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.yelp.search,
            term=term,
            location=location,
            page=page,
            sort=sort,
            price=price,
            open_now=open_now,
            attributes=attributes,
            url=url,
        )

    def yelp_business(self, business_id: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get one Yelp business in full.

        One business in full: rating and per-star histogram, review count, price band, categories, address and
        coordinates, phone, website and menu links, hours and holidays, amenities, photos and videos, popular items,
        health inspections, Q&A, licences and claim status - plus the first page of reviews at no extra cost. Provide
        business_id or url.

        Args:
            business_id (Optional[str]): A Yelp business alias ('desnudo-coffee-austin-2'), its opaque encid, or
                any yelp.com/biz URL carrying one (1-500 characters). Search rows return both id forms.
            url (Optional[str]): A full yelp.com/biz URL (1-1000 characters) as an alternative to business_id.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.yelp.business,
            business_id=business_id,
            url=url,
        )

    def yelp_reviews(
        self,
        business_id: Optional[str] = None,
        url: Optional[str] = None,
        page: Optional[int] = None,
        sort: Optional[str] = None,
        rating: Optional[int] = None,
    ) -> str:
        """Get a page of Yelp reviews.

        A page of reviews: rating, full text, language, author profile and expertise counts, attached photos, reaction
        counts and owner response. 10 per page. PAGE 1 IS REDUNDANT - it re-fetches the document yelp_business()
        already returned - so start at page 2. Provide business_id or url.

        Args:
            business_id (Optional[str]): A Yelp business alias ('desnudo-coffee-austin-2'), its opaque encid, or
                any yelp.com/biz URL carrying one (1-500 characters).
            url (Optional[str]): A full yelp.com/biz URL (1-1000 characters) as an alternative to business_id.
            page (Optional[int]): Reviews page, 1-based, 10 per page. Page 1 duplicates the reviews
                yelp_business() already returned and costs another 2 credits - start at 2. A page past the last review
                is a 404, not an empty result.
            sort (Optional[str]): Review ordering (upstream default 'relevance'). Closed enum: Yelp IGNORES an
                unrecognised value and serves default ranking under a billed 200. One of: "relevance", "newest",
                "oldest", "rating_high", "rating_low", "elites".
            rating (Optional[int]): Only reviews at this star rating, 1-5. Changes filtered_review_count on the
                response, not review_count. One of: 1, 2, 3, 4, 5.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.yelp.reviews,
            business_id=business_id,
            url=url,
            page=page,
            sort=sort,
            rating=rating,
        )

    # --------------------------------------------------------------- App Store

    def app_store_search(
        self,
        term: str,
        limit: Optional[int] = None,
        country: Optional[str] = None,
        entity: Optional[str] = None,
        lang: Optional[str] = None,
    ) -> str:
        """Search the Apple App Store.

        Search the App Store and get up to 200 fully-shaped app rows - the same 43-field row as app_store_app() - so a
        search doubles as a bulk metadata fetch and as a publisher lookup. NO PAGINATION: raise limit, there is no
        second page.

        Args:
            term (str): What to search for (1-500 characters). Apple matches an app name, a keyword OR a publisher
                name, so searching a developer returns their catalogue.
            limit (Optional[int]): Apps to return, 1-200 (default 25). The ONLY lever on result volume: the search
                API has no pagination and every offset spelling is silently ignored.
            country (Optional[str]): Two-letter ISO storefront code (default 'us'); decides price, currency,
                localised title and whether the app is sold there at all. Anything that is not exactly two letters is
                rejected with a free 400.
            entity (Optional[str]): Which catalogue to search: iPhone/iPad apps ('software', the default), iPad
                apps, or Mac App Store apps. These are separate stores, not a filter - Mac rows carry no iPad/Apple TV
                screenshots, advisories, features, supported devices or Game Center flag, returning them empty rather
                than absent. One of: "software", "ipad_software", "mac_software".
            lang (Optional[str]): Listing text language as a five-letter code ('en_us', 'ja_jp'); any other shape
                is rejected. Independent of country: the storefront sets the price, this sets the words.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.app_store.search,
            term,
            limit=limit,
            country=country,
            entity=entity,
            lang=lang,
        )

    def app_store_app(self, app_id: str, country: Optional[str] = None) -> str:
        """Get a full App Store listing.

        Full App Store listing: title, description, developer and seller identity, price and currency, all-time and
        current-version ratings, version and release notes, genres, content rating and advisories, icons at three
        sizes, screenshots, download size, minimum OS, languages, supported devices and the Game Center and VPP flags.

        Args:
            app_id (str): App Store id - the digits after 'id' in an apps.apple.com URL - or the app's bundle id
                ('notion.id', 'com.burbn.instagram'); both resolve to the identical payload. 1-255 characters matching
                ^[A-Za-z0-9][A-Za-z0-9._-]*$, so a pasted apps.apple.com URL is rejected with a free 400. An id Apple
                cannot resolve is a billed 404.
            country (Optional[str]): Two-letter ISO storefront code (default 'us'); decides price, currency,
                localised title and whether the app is sold there at all. Anything that is not exactly two letters is
                rejected with a free 400.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.app_store.app,
            app_id,
            country=country,
        )

    def app_store_reviews(
        self,
        app_id: str,
        country: Optional[str] = None,
        page: Optional[int] = None,
        sort: Optional[str] = None,
    ) -> str:
        """Get a page of App Store reviews.

        A page of App Store reviews: star rating, title, full text, author and the APP VERSION the review was written
        against. 50 per page, hard-stopped at page 10 - 500 reviews per storefront is Apple's anonymous ceiling. This
        endpoint cannot 404: an unknown id and a real app with no reviews return the same empty feed.

        Args:
            app_id (str): App Store id, NUMERIC ONLY - unlike app_store_app(), the reviews feed has no bundle-id
                form.
            country (Optional[str]): Two-letter ISO storefront code (default 'us'). Anything that is not exactly
                two letters is rejected with a free 400. Ask a different country to reach past the 500-review ceiling.
            page (Optional[int]): Reviews page, 1-10, 50 reviews each (default 1). Apple hard-stops at page 10.
            sort (Optional[str]): Review ordering (default 'most_recent'). The choice decides whether the vote
                fields mean anything: under most_recent almost every review is too new to have been voted on and
                returns zeroes, while most_helpful returns them densely populated.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.app_store.reviews,
            app_id,
            country=country,
            page=page,
            sort=sort,
        )

    # ------------------------------------------------------------- Google Play

    def google_play_search(
        self,
        query: str,
        hl: Optional[str] = None,
        gl: Optional[str] = None,
    ) -> str:
        """Search Google Play.

        Ranked Google Play apps: package name, title, developer, rating, install count, price and IAP range, content
        rating, icon and screenshots. A branded query returns the hero card as result 1 in the same row shape, plus
        Play's related-query rail. NO PAGINATION - one shelf of about 30 apps.

        Args:
            query (str): What to search the store for (1-200 characters): an app name, a publisher, or a category
                phrase. Apps only - games are folded into the apps vertical, but books and films use a different card
                shape and are not covered.
            hl (Optional[str]): UI language, 2-20 characters (default 'en'). Changes the STOREFRONT, not only the
                strings: at hl=pt-BR the title, description, install formatting and content rating all move with it.
                Play silently falls back to English on a value it does not serve.
            gl (Optional[str]): Country code, 2-10 characters (default 'us'), deciding which storefront's price
                and availability are returned. Play silently falls back to the US storefront on a country it does not
                serve.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.google_play.search,
            query,
            hl=hl,
            gl=gl,
        )

    def google_play_app(
        self,
        app_id: str,
        hl: Optional[str] = None,
        gl: Optional[str] = None,
    ) -> str:
        """Get a full Google Play store listing.

        Full Google Play store listing: installs including the REAL count Play publishes but never renders, rating and
        star histogram, description, developer identity and legal contact, price and IAPs, categories and gameplay
        tags, screenshots and trailer, version and Android requirement, release and update dates, changelog, the full
        permission tree, the Data safety table, the 20 server-rendered reviews and the similar-apps and
        more-by-developer rails.

        Args:
            app_id (str): Android package name ('com.spotify.music') or any play.google.com URL carrying one in
                its id param (1-500 characters).
            hl (Optional[str]): UI language, 2-20 characters (default 'en'). Changes the STOREFRONT, not only the
                strings: title, description, install formatting and content rating all move with it. Play silently
                falls back to English on a value it does not serve.
            gl (Optional[str]): Country code, 2-10 characters (default 'us'), deciding which storefront's price
                and availability are returned. Play silently falls back to the US storefront on a country it does not
                serve.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.google_play.app,
            app_id,
            hl=hl,
            gl=gl,
        )

    def google_play_reviews(
        self,
        app_id: str,
        sort: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
        hl: Optional[str] = None,
        gl: Optional[str] = None,
    ) -> str:
        """Get a page of Google Play reviews.

        A page of Google Play reviews: star score, full text, author, thumbs-up count, developer reply and the APP
        VERSION the reviewer was running. Paged by cursor, up to 200 per call. google_play_app() already returns the
        20 reviews Play server-renders; use this to page past them or sort differently.

        Args:
            app_id (str): Android package name ('com.spotify.music') or any play.google.com URL carrying one in
                its id param (1-500 characters).
            sort (Optional[str]): Review ordering (default 'newest'). Closed enum. The cursor encodes the sort, so
                keep this identical when paging. One of: "relevance", "newest", "rating".
            count (Optional[int]): Reviews to return, 1-200 (default 50); 200 is our cap, not Play's. Play honours
                more, but a single page that large is megabytes for one credit - page with cursor instead.
            cursor (Optional[str]): Continuation token from a prior response's next_cursor (1-4000 characters).
                Opaque and SINGLE-USE, and it encodes the sort as well as the position - send it back with the SAME
                sort it came from. A cursor past the last review is a 404, not an empty page.
            hl (Optional[str]): UI language, 2-20 characters (default 'en'). Changes the STOREFRONT, not only the
                strings. Play silently falls back to English on a value it does not serve.
            gl (Optional[str]): Country code, 2-10 characters (default 'us'), deciding which storefront's price
                and availability are returned. Play silently falls back to the US storefront on a country it does not
                serve.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.google_play.reviews,
            app_id,
            sort=sort,
            count=count,
            cursor=cursor,
            hl=hl,
            gl=gl,
        )

    # --------------------------------------------------------------- SEC EDGAR
    #
    # SEC EDGAR is LOOKUP-FIRST: sec_lookup resolves a name or ticker to the CIK the other calls are keyed by, though
    # every one of them also accepts a ticker directly.

    def sec_lookup(
        self,
        query: str,
        limit: Optional[int] = None,
        exchange: Optional[str] = None,
    ) -> str:
        """Resolve a company name or ticker to an SEC CIK.

        START HERE. Resolve a company name or ticker (AAPL) to the CIK (0000320193) every other SEC EDGAR endpoint is
        keyed by. Up to 100 rows, tiered by match quality.

        Args:
            query (str): Ticker ('AAPL', 'BRK.B'), company name, or a fragment of one (1-200 characters); each row
                carries its match tier as 'match'.
            limit (Optional[int]): Rows to return, 1-100. Defaults to 10. Sizes the response; it is not a page
                param.
            exchange (Optional[str]): Restrict to one listing venue; matched case-insensitively, so 'Nasdaq' also
                works. Filers the SEC lists with no exchange at all are excluded by any value. One of: "NASDAQ",
                "NYSE", "OTC", "CBOE".

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.sec.lookup,
            query,
            limit=limit,
            exchange=exchange,
        )

    def sec_company(self, cik: Optional[str] = None, ticker: Optional[str] = None) -> str:
        """Get an SEC EDGAR filer profile.

        SEC filer profile: legal and former names, SIC industry, filer category, EIN, LEI, state of incorporation,
        fiscal year end, addresses, every ticker with its exchange, and a preview of its 10 most recent filings.
        Provide cik or ticker.

        Args:
            cik (Optional[str]): Filer CIK in any spelling (1-20 characters): 320193, 0000320193 or CIK0000320193.
                A ticker is accepted here too.
            ticker (Optional[str]): Ticker symbol (1-20 characters), dotted or dashed (BRK.B / BRK-B). Wins over
                cik when both are given.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.sec.company,
            cik=cik,
            ticker=ticker,
        )

    def sec_filings(
        self,
        cik: Optional[str] = None,
        ticker: Optional[str] = None,
        form: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        include_history: Optional[bool] = None,
    ) -> str:
        """List a filer's SEC filings.

        A page of one filer's filings: accession number, form and root form, filing and period dates, 8-K item codes,
        direct links to the primary document, filing index and attachment directory. Up to 500 per page. Provide cik
        or ticker.

        Args:
            cik (Optional[str]): Filer CIK, zero-padded or bare (1-20 characters). A ticker is accepted here too.
            ticker (Optional[str]): Ticker symbol (1-20 characters), as an alternative to cik.
            form (Optional[str]): Form types to keep: '10-K', or the comma-joined '10-K,8-K'; at most 25 values,
                each 1-50 characters. Matched against the form AND its root form, so 10-K also returns 10-K/A
                amendments; ask for '10-K/A' to get only amendments.
            date_from (Optional[str]): Earliest filing date, inclusive (YYYY-MM-DD).
            date_to (Optional[str]): Latest filing date, inclusive (YYYY-MM-DD).
            page (Optional[int]): Results page, 1-based; page size is whatever limit is set to. No upper bound.
            limit (Optional[int]): Filings per page, 1-500. Defaults to 50.
            include_history (Optional[bool]): Also fetch the archived filing history beyond EDGAR's 'recent'
                block, which is not a fixed window (a decade for a quiet filer, about a year for a prolific one). Off
                by default; at most 10 archived shards are fetched, history_truncated says when a filer had more, and
                it is still 1 credit.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.sec.filings,
            cik=cik,
            ticker=ticker,
            form=form,
            date_from=date_from,
            date_to=date_to,
            page=page,
            limit=limit,
            include_history=include_history,
        )

    def sec_concept(
        self,
        concept: str,
        cik: Optional[str] = None,
        ticker: Optional[str] = None,
        taxonomy: Optional[str] = None,
        unit: Optional[str] = None,
        form: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> str:
        """Get every value a filer reported for one XBRL concept.

        Every value a filer reported for one XBRL concept, newest period first, with the form and filing each number
        came from. Restatements are kept, not collapsed. Up to 2000 rows. Provide cik or ticker.

        Args:
            concept (str): XBRL concept tag, CASE-SENSITIVE (1-120 characters, ^[A-Za-z][A-Za-z0-9]*$):
                'NetIncomeLoss' matches, 'netincomeloss' is a 404 upstream. Use sec_facts() to list what a filer
                actually reports.
            cik (Optional[str]): Filer CIK, zero-padded or bare (1-20 characters). A ticker is accepted here too.
            ticker (Optional[str]): Ticker symbol (1-20 characters), as an alternative to cik.
            taxonomy (Optional[str]): Reporting taxonomy (1-40 characters, ^[A-Za-z][A-Za-z0-9-]*$): us-gaap, dei,
                ifrs-full or srt. Defaults to 'us-gaap'.
            unit (Optional[str]): Unit of measure to keep (1-40 characters), e.g. 'USD' vs 'USD/shares'.
            form (Optional[str]): Form to keep (1-50 characters). EXACT match here, unlike sec_filings(), so
                '10-K' excludes 10-K/A.
            limit (Optional[int]): Rows to return, 1-2000. Defaults to 250. Sizes the response; it is not a page
                param.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.sec.concept,
            concept,
            cik=cik,
            ticker=ticker,
            taxonomy=taxonomy,
            unit=unit,
            form=form,
            limit=limit,
        )

    def sec_facts(
        self,
        cik: Optional[str] = None,
        ticker: Optional[str] = None,
        taxonomy: Optional[str] = None,
        query: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> str:
        """List every XBRL concept a filer reports.

        The index of every XBRL concept a filer reports - tag, label, description, units and most recent value -
        across us-gaap, dei and any other taxonomy it uses. This is how you find what to ask sec_concept() for. Up to
        2000 rows. Provide cik or ticker.

        Args:
            cik (Optional[str]): Filer CIK, zero-padded or bare (1-20 characters). A ticker is accepted here too.
            ticker (Optional[str]): Ticker symbol (1-20 characters), as an alternative to cik.
            taxonomy (Optional[str]): Restrict to one taxonomy (1-40 characters), e.g. 'us-gaap' or 'dei'.
            query (Optional[str]): Case-insensitive substring matched against the tag name and label (1-200
                characters).
            limit (Optional[int]): Rows to return, 1-2000. Defaults to 250. Sizes the response; it is not a page
                param.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.sec.facts,
            cik=cik,
            ticker=ticker,
            taxonomy=taxonomy,
            query=query,
            limit=limit,
        )

    def sec_search(
        self,
        query: Optional[str] = None,
        cik: Optional[str] = None,
        ticker: Optional[str] = None,
        form: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        location: Optional[str] = None,
        sort: Optional[str] = None,
        page: Optional[int] = None,
    ) -> str:
        """Run an EDGAR full-text search over filing documents.

        EDGAR full-text search, coverage starting 2001: each hit is the matching DOCUMENT with its URL, form, filing
        date and filer identity, plus facets by company, form, industry and state. 100 documents per page, last page
        is 100.

        Args:
            query (Optional[str]): Full-text query over filing documents (1-500 characters); a quoted phrase is
                matched exactly, bare words as a bag of terms. Optional - a cik, ticker, form or date filter on its
                own is a valid search.
            cik (Optional[str]): Restrict to one or more filers by CIK: a single value or a comma-joined string,
                at most 25 values, each 1-20 characters. Tickers are accepted here too.
            ticker (Optional[str]): Restrict to one or more filers by ticker symbol: a single value or a
                comma-joined string, at most 25 values, each 1-20 characters.
            form (Optional[str]): Form types to keep: '8-K', or the comma-joined '10-K,10-Q'; at most 25 values,
                each 1-50 characters.
            date_from (Optional[str]): Earliest filing date, inclusive (YYYY-MM-DD). Full-text coverage starts in
                2001.
            date_to (Optional[str]): Latest filing date, inclusive (YYYY-MM-DD).
            location (Optional[str]): Filer business-address locations as EDGAR's own 2-character codes (CA, NY,
                and its alphanumeric codes for foreign jurisdictions): a single value or a comma-joined string, at
                most 25 values.
            sort (Optional[str]): Result ordering. Defaults to the index's own relevance ranking. One of:
                "relevance", "newest", "oldest".
            page (Optional[int]): Results page, 1-based, 1-100, 100 documents per page. The SEC's index refuses a
                result window past 10,000, so 100 is the last page for any query.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.sec.search,
            query=query,
            cik=cik,
            ticker=ticker,
            form=form,
            date_from=date_from,
            date_to=date_to,
            location=location,
            sort=sort,
            page=page,
        )

    # ------------------------------------------------------------------ Redfin

    def redfin_search(
        self,
        location: Optional[str] = None,
        region_id: Optional[int] = None,
        region_type: Optional[int] = None,
        listing_status: Optional[str] = None,
        sold_within_days: Optional[int] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        beds_min: Optional[int] = None,
        beds_max: Optional[int] = None,
        baths_min: Optional[int] = None,
        sqft_min: Optional[int] = None,
        sqft_max: Optional[int] = None,
        lot_size_min: Optional[int] = None,
        year_built_min: Optional[int] = None,
        year_built_max: Optional[int] = None,
        max_hoa: Optional[float] = None,
        property_type: Optional[str] = None,
        has_pool: Optional[bool] = None,
        max_days_on_market: Optional[int] = None,
        min_days_on_market: Optional[int] = None,
    ) -> str:
        """Search Redfin listings.

        Redfin listings: price, price per sqft, beds, baths, living area, lot size, year built, coordinates, listing
        remarks and full photo galleries, for sale, sold or for rent. Up to 350 per page. Provide location, or
        region_id together with region_type.

        Args:
            location (Optional[str]): A redfin.com region URL (/city/, /neighborhood/, /county/, /zipcode/) or a
                bare 5-digit ZIP (1-500 characters). CITY NAMES ARE NOT ACCEPTED - Redfin's own name lookup is blocked
                to us; use region_id + region_type instead.
            region_id (Optional[int]): Redfin internal region id (>= 1), used together with region_type. NOT a ZIP
                code - the two are different number spaces and a ZIP here resolves to another city rather than
                failing.
            region_type (Optional[int]): Region kind that region_id belongs to: 1 neighborhood, 2 ZIP, 5 county, 6
                city. Must be sent together with region_id or both are ignored in favour of location.
            listing_status (Optional[str]): Market to search. Defaults to 'for_sale'. One of: "for_sale", "sold",
                "for_rent".
            sold_within_days (Optional[int]): Sold within the last N days (>= 1). REJECTED unless
                listing_status='sold', where it defaults to 90.
            page (Optional[int]): Results page, 1-based; page size is whatever limit is set to. No upper bound.
            limit (Optional[int]): Listings per page, 1-350. Defaults to 100.
            sort (Optional[str]): Result sort order. Defaults to 'recommended', Redfin's own ranking. One of:
                "recommended", "price_low", "price_high", "newest", "oldest", "sqft_low", "sqft_high",
                "price_per_sqft_low", "price_per_sqft_high".
            min_price (Optional[float]): Minimum price, inclusive (>= 0). Monthly rent when
                listing_status='for_rent'.
            max_price (Optional[float]): Maximum price, inclusive (>= 0). Monthly rent when
                listing_status='for_rent'.
            beds_min (Optional[int]): Minimum bedrooms (whole number >= 0); fractional values are rejected.
            beds_max (Optional[int]): Maximum bedrooms (whole number >= 0); fractional values are rejected.
            baths_min (Optional[int]): Minimum bathrooms (whole number >= 0). WHOLE BATHS ONLY - 1.5 is rejected
                rather than silently truncated to 1. There is no baths_max.
            sqft_min (Optional[int]): Minimum living area in square feet (whole number >= 0).
            sqft_max (Optional[int]): Maximum living area in square feet (whole number >= 0).
            lot_size_min (Optional[int]): Minimum lot size in square feet (whole number >= 0). There is no
                lot_size_max.
            year_built_min (Optional[int]): Earliest year built (whole number >= 0).
            year_built_max (Optional[int]): Latest year built (whole number >= 0).
            max_hoa (Optional[float]): Maximum monthly HOA fee in dollars (>= 0).
            property_type (Optional[str]): Restrict to one property type. One of: "house", "condo", "townhouse",
                "multi_family", "land", "other", "co_op".
            has_pool (Optional[bool]): Only listings with a pool.
            max_days_on_market (Optional[int]): Listed at most N days ago (whole number >= 0). Cannot be combined
                with min_days_on_market - Redfin expresses both bounds through one param.
            min_days_on_market (Optional[int]): Listed at least N days ago (whole number >= 0). Cannot be combined
                with max_days_on_market.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.redfin.search,
            location=location,
            region_id=region_id,
            region_type=region_type,
            listing_status=listing_status,
            sold_within_days=sold_within_days,
            page=page,
            limit=limit,
            sort=sort,
            min_price=min_price,
            max_price=max_price,
            beds_min=beds_min,
            beds_max=beds_max,
            baths_min=baths_min,
            sqft_min=sqft_min,
            sqft_max=sqft_max,
            lot_size_min=lot_size_min,
            year_built_min=year_built_min,
            year_built_max=year_built_max,
            max_hoa=max_hoa,
            property_type=property_type,
            has_pool=has_pool,
            max_days_on_market=max_days_on_market,
            min_days_on_market=min_days_on_market,
        )

    def redfin_property(self, property_id: str) -> str:
        """Get one Redfin listing in full.

        One Redfin listing in full: price, Redfin Estimate and rental estimate, complete MLS fact sheet, price and tax
        history, listing agents, open houses, schools, climate risk, walkability, sun exposure, monthly weather,
        permits, zoning, comparable sales and photos.

        Args:
            property_id (str): Redfin property id, or any redfin.com listing URL carrying one (1-500 characters).

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.redfin.property,
            property_id,
        )

    def redfin_market(
        self,
        location: Optional[str] = None,
        region_id: Optional[int] = None,
        region_type: Optional[int] = None,
    ) -> str:
        """Get Redfin housing-market stats for a region.

        Redfin housing-market stats for a region: median list and sale price, price per sqft, sale-to-list ratio,
        average offers and days on market, YoY movement, 0-100 compete score, live inventory by property type and by
        bedroom count, and Redfin agent presence. Provide location, or region_id together with region_type.

        Args:
            location (Optional[str]): A redfin.com region URL (/city/, /neighborhood/, /county/, /zipcode/) or a
                bare 5-digit ZIP (1-500 characters). City names are not accepted.
            region_id (Optional[int]): Redfin internal region id (>= 1), used together with region_type. Not a ZIP
                code.
            region_type (Optional[int]): Region kind that region_id belongs to: 1 neighborhood, 2 ZIP, 5 county, 6
                city. Must be sent together with region_id or both are ignored in favour of location.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.redfin.market,
            location=location,
            region_id=region_id,
            region_type=region_type,
        )

    # --------------------------------------------------------- Companies House
    #
    # Companies House is LOOKUP-FIRST: companies_house_search resolves a name to the company_number the other three
    # are keyed by.

    def companies_house_search(self, query: str, page: Optional[int] = None) -> str:
        """Search the UK Companies House register by name.

        START HERE. Search the UK register by name and get the company_number every other Companies House endpoint is
        keyed by, plus status, incorporation or dissolution date, registered office and matched former names. 20 per
        page, last page is 50.

        Args:
            query (str): Company name or fragment (1-200 characters, non-blank). Matches CURRENT AND FORMER names.
            page (Optional[int]): Results page, 1-based, 1-50, 20 results per page. Defaults to 1. The register
                serves only a 1000-result window per term whatever hit count it prints, and answers page 51 with HTTP
                416.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.companies_house.search,
            query,
            page=page,
        )

    def companies_house_company(self, company_number: str) -> str:
        """Get a full UK Companies House register entry.

        Full UK register entry: status, type, incorporation and dissolution dates, registered office, SIC codes,
        previous names, accounts and confirmation-statement due dates with overdue flags, and whether it has charges,
        insolvency history, officers or UK establishments.

        Args:
            company_number (str): UK company number (1-20 characters), zero-padded and upper-cased for you, so
                '445790' and 'sc090312' both work. Registry prefixes supported: SC, NI, OC, SO, NC, FC, BR, CE.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.companies_house.company,
            company_number,
        )

    def companies_house_officers(self, company_number: str, page: Optional[int] = None) -> str:
        """List a UK company's officers.

        UK company officers, current and resigned, 35 per page: name, role, appointment and resignation dates,
        correspondence address, nationality, country of residence, month-and-year date of birth and
        identity-verification status.

        Args:
            company_number (str): UK company number (1-20 characters), zero-padded and upper-cased for you.
            page (Optional[int]): Results page, 1-based, 35 per page. Defaults to 1. No upper bound: past the last
                page the register answers an ordinary 200 with an empty list, identical to a company with no officers.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.companies_house.officers,
            company_number,
            page=page,
        )

    def companies_house_filing_history(self, company_number: str, page: Optional[int] = None) -> str:
        """List a UK company's filings.

        UK filings, most recent first: date, filing type code (AA, CS01, SH03), description, register annotations and
        child documents, and a link to the filed PDF with its page count. A filing the register has not finished
        processing carries a processing_note instead of a document.

        Args:
            company_number (str): UK company number (1-20 characters), zero-padded and upper-cased for you.
            page (Optional[int]): Results page, 1-based. Defaults to 1. No upper bound: past the last page the
                register answers an ordinary 200 with an empty list.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.companies_house.filing_history,
            company_number,
            page=page,
        )

    # ---------------------------------------------------------------------- G2

    def g2_search(
        self,
        query: Optional[str] = None,
        page: Optional[int] = None,
        limit: Optional[int] = None,
        sort: Optional[str] = None,
        rating: Optional[int] = None,
        url: Optional[str] = None,
    ) -> str:
        """Search G2 for B2B software products.

        Search G2, the B2B software review site, for products: star rating, review count, vendor, categories, seller
        description and logo, with product_id and slug on every row. Up to 100 results per page (server default 20)
        and page-paginated; total_results is G2's Products-tab headline and caps at 10000, while total_by_type splits
        the query across products, sellers, categories and discussions. Provide query or url.

        Args:
            query (Optional[str]): Search term (1-200 characters). Provide this or url.
            page (Optional[int]): 1-based page number; page size follows limit (server default 20). G2 keeps
                paginating well past its own widget's page links.
            limit (Optional[int]): Results per page (1-100; server default 20). The 100 ceiling is ours, to keep a
                single request inside the 60s deadline; G2 itself paginates at any size.
            sort (Optional[str]): Result sort order (server default 'relevance'). Closed enum: G2 silently accepts
                an unknown sort and answers 200 with an unstated ordering. One of: "relevance", "popular",
                "alphabetical", "rating".
            rating (Optional[int]): Only products at or above this star rating (1-5, sent as an integer). Omit for
                no rating floor. One of: 1, 2, 3, 4, 5.
            url (Optional[str]): Full g2.com/search URL, as an alternative to query (1-1000 characters; the host
                is checked by the transport).

        Returns:
            str: JSON string of the API response. Costs 5 credits.
        """
        return self._call(
            self.client.g2.search,
            query=query,
            page=page,
            limit=limit,
            sort=sort,
            rating=rating,
            url=url,
        )

    def g2_product(self, product_id: Optional[str] = None, url: Optional[str] = None) -> str:
        """Get a full G2 product profile.

        Full G2 product profile: rating with per-star histogram, review count, vendor, description and seller website,
        pricing editions with parsed amounts, feature groups, categories and breadcrumbs, supported languages,
        integrations, alternatives, head-to-head comparisons, media, community discussions and G2's AI-derived pros
        and cons. Carries NO review text at all -- G2 loads review bodies in a separate frame, so call g2_reviews()
        for those. Provide product_id or url.

        Args:
            product_id (Optional[str]): G2 product slug ('notion') or the numeric G2 id ('82623') as a string
                (1-200 characters); both resolve on the same upstream path.
            url (Optional[str]): Full g2.com product URL, as an alternative to product_id (1-1000 characters).

        Returns:
            str: JSON string of the API response. Costs 5 credits.
        """
        return self._call(
            self.client.g2.product,
            product_id=product_id,
            url=url,
        )

    def g2_reviews(
        self,
        product_id: Optional[str] = None,
        url: Optional[str] = None,
        page: Optional[int] = None,
        sort: Optional[str] = None,
        rating: Optional[int] = None,
        company_size: Optional[str] = None,
        role: Optional[str] = None,
        region: Optional[str] = None,
        query: Optional[str] = None,
    ) -> str:
        """Get a page of G2 reviews with facet counts.

        A page of G2 reviews: rating, title, likes and dislikes, problems solved, reviewer job title, industry and
        company size, validated and incentivized flags -- plus what the profile page has no form of: exact per-star
        counts, pros and cons with per-theme counts, and company-size, role, industry, region and category facets with
        counts. Fixed at 10 reviews per page and paginates well past the 10 pages G2's own widget links to. Provide
        product_id or url.

        Args:
            product_id (Optional[str]): G2 product slug or numeric G2 id as a string (1-200 characters).
            url (Optional[str]): Full g2.com reviews URL, as an alternative to product_id (1-1000 characters).
            page (Optional[int]): 1-based page number; fixed at 10 reviews per page.
            sort (Optional[str]): Review sort order (server default 'relevance'). Closed enum: an unknown sort is
                silently accepted upstream and never runs. One of: "relevance", "newest", "most_helpful",
                "rating_high", "rating_low".
            rating (Optional[int]): Only reviews in this star bucket (1-5, sent as an integer). Buckets are half-
                star-inclusive: 1 returns 0, 0.5 and 1-star reviews. One of: 1, 2, 3, 4, 5.
            company_size (Optional[str]): Reviewer company size: small_business is 50 employees or fewer,
                mid_market 51-1000, enterprise over 1000. Closed enum -- an unknown value matches nothing and returns
                a billed 'Reviews (0)'.
            role (Optional[str]): Reviewer role. Closed enum -- an unknown value matches nothing rather than
                erroring. One of: "user", "administrator", "executive_sponsor", "internal_consultant", "consultant",
                "agency", "industry_analyst".
            region (Optional[str]): Reviewer region. Closed enum -- an unknown value matches nothing rather than
                erroring. One of: "north_america", "europe", "asia", "latin_america", "anz", "middle_east", "africa".
            query (Optional[str]): Full-text search within this product's reviews (1-200 characters); narrows the
                review list AND every facet count.

        Returns:
            str: JSON string of the API response. Costs 5 credits.
        """
        return self._call(
            self.client.g2.reviews,
            product_id=product_id,
            url=url,
            page=page,
            sort=sort,
            rating=rating,
            company_size=company_size,
            role=role,
            region=region,
            query=query,
        )

    # ---------------------------------------------------------------- Capterra

    def capterra_search(self, query: Optional[str] = None, url: Optional[str] = None) -> str:
        """Search Capterra for B2B software products.

        Search Capterra, the B2B software review site: 20 ranked products with name, vendor description, rating,
        review count, logo and paid-placement flag, each row carrying product_id and slug. The result set is fixed at
        20 and does NOT paginate -- Capterra serves identical rows for page 2, so there is deliberately no page
        parameter. Provide query or url.

        Args:
            query (Optional[str]): Search term (1-200 characters). Required in practice: a term-less Capterra
                search serves a fixed popular-products list unrelated to the caller.
            url (Optional[str]): Full capterra.com search URL, as an alternative to query (1-1000 characters; the
                transport also accepts capterra.co.uk and capterra.com.br hosts).

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.capterra.search,
            query=query,
            url=url,
        )

    def capterra_product(
        self,
        product_id: Optional[str] = None,
        slug: Optional[str] = None,
        url: Optional[str] = None,
    ) -> str:
        """Get a full Capterra product profile.

        Full Capterra profile: rating with per-star histogram and the four scored criteria, likelihood to recommend,
        review sentiment and topics, the complete pricing table with every plan and its features, every rated feature
        and integration, AI-derived pros and cons with the quoted review, FAQs, screenshots, badges and awards,
        competitor comparisons and alternatives, and the buyer profile by company size, industry and job function --
        PLUS the 25 most recent reviews at no extra cost. vendor is always null here: Capterra does not publish it as
        structured data on the product page. Provide product_id or url.

        Args:
            product_id (Optional[str]): The number in a Capterra product path such as /p/186596/Notion/ (1-50
                characters). Must be a STRING -- a JSON number is rejected.
            slug (Optional[str]): Product slug (1-200 characters). Cosmetic on this endpoint -- a wrong slug still
                returns the right profile -- but load-bearing on capterra_reviews().
            url (Optional[str]): Full Capterra product URL, as an alternative to product_id (1-1000 characters).

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.capterra.product,
            product_id=product_id,
            slug=slug,
            url=url,
        )

    def capterra_reviews(
        self,
        product_id: Optional[str] = None,
        slug: Optional[str] = None,
        url: Optional[str] = None,
        page: Optional[int] = None,
    ) -> str:
        """Get a page of Capterra reviews.

        A page of Capterra reviews: overall score plus five per-criterion scores, title, pros, cons, advice, usage
        duration, incentivized flag, alternatives considered and what they switched from, reviewer job title, industry
        and company size, and the vendor response -- plus a competitor list richer than the profile's, each
        alternative with its own rating histogram and starting price. 25 reviews per page, capped at page 100. Page 1
        already rides along inside capterra_product(), so use this to page past it. Provide product_id or url.

        Args:
            product_id (Optional[str]): Capterra product id as a string (1-50 characters).
            slug (Optional[str]): Product slug (1-200 characters). LOAD-BEARING here: it is case-sensitive
                upstream and a wrong one silently serves page one under a billed 200. Pass back the slug from
                capterra_search() or capterra_product().
            url (Optional[str]): Full Capterra reviews URL, as an alternative to product_id (1-1000 characters).
                Passing back reviews_url from capterra_product() is the reliable way to page.
            page (Optional[int]): 1-based page number (1-100); 25 reviews per page. 100 is a hard cap whatever the
                review count says -- past it Capterra answers 200 with page one.

        Returns:
            str: JSON string of the API response. Costs 2 credits.
        """
        return self._call(
            self.client.capterra.reviews,
            product_id=product_id,
            slug=slug,
            url=url,
            page=page,
        )

    # ------------------------------------------------- Google Ads Transparency
    #
    # Google Ads Transparency publishes an advertiser's ad total as a RANGE (total_ads_min / total_ads_max), never an
    # exact figure, and impression data on a creative is EEA-only, coming back null for US ads.

    def google_ads_advertisers(
        self,
        query: str,
        region: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> str:
        """Resolve a brand or domain to a Google advertiser_id.

        Resolve a brand name or domain to the advertiser_id that google_ads_search() and google_ads_creative() are
        keyed by. Returns two row kinds in one list: 'advertiser' rows carrying the id, verified name, verification
        country and total ad count as a range, and 'domain' rows carrying a website. A name query returns both kinds;
        a domain-shaped query returns domains only. Autocomplete-backed, roughly 20 rows per arm, and it does not
        paginate.

        Args:
            query (str): Brand name or domain to resolve (1-200 characters).
            region (Optional[str]): ISO 3166-1 alpha-2 country ('US', 'GB', 'DE') or a Google geo criteria id as a
                string (2-12 characters). Default: no region filter.
            limit (Optional[int]): Rows per arm (1-20; server default 10). Advertisers and domains are capped
                separately, so a name query can return up to twice this many rows.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.google_ads.advertisers,
            query,
            region=region,
            limit=limit,
        )

    def google_ads_search(
        self,
        domain: Optional[str] = None,
        advertiser_id: Optional[str] = None,
        region: Optional[str] = None,
        format: Optional[str] = None,
        platform: Optional[str] = None,
        topic: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List every ad Google Ads Transparency holds for an advertiser.

        Every ad Google Ads Transparency holds for one advertiser: the creative (archived image, rich-media bundle,
        Google's renderer link, dimensions), advertiser id and name, format, first and last seen dates and days
        actually run, plus total_ads_min and total_ads_max -- Google publishes the advertiser's ad total as a range,
        never an exact figure. Up to 100 ads per page (server default 40); paginate by sending next_cursor back as
        cursor alongside the SAME filters. Provide domain or advertiser_id.

        Args:
            domain (Optional[str]): Advertiser website (1-253 characters): bare host, www host or full URL,
                reduced to the registrable host. The only way to get `domain` back on each row.
            advertiser_id (Optional[str]): Google advertiser id, e.g. 'AR16735076323512287233' (3-40 characters).
                The shape is checked before any request, so a typo costs no credits. Querying by id drops `domain`
                from every row.
            region (Optional[str]): ISO 3166-1 alpha-2 country ('US', 'GB', 'DE') or a Google geo criteria id as a
                string (2-12 characters). Scopes the deep links on every row, and the same advertiser can share zero
                creatives between two countries. Default: worldwide.
            format (Optional[str]): Creative format. The three sets are disjoint -- an advertiser's text, image
                and video ads share no creatives. Default: all formats.
            platform (Optional[str]): Google surface the ad ran on. Default: all surfaces. One of: "play", "maps",
                "search", "shopping", "youtube".
            topic (Optional[str]): Ad topic (server default 'all').
            limit (Optional[int]): Ads per page (1-100; server default 40). 100 is a hard upstream ceiling, not
                our policy: Google answers a larger request with zero rows rather than an error.
            cursor (Optional[str]): next_cursor from the previous response (1-4000 characters), 100 ads per page.
                Re-send the same filters alongside it; next_cursor is null once exhausted.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.google_ads.search,
            domain=domain,
            advertiser_id=advertiser_id,
            region=region,
            format=format,
            platform=platform,
            topic=topic,
            limit=limit,
            cursor=cursor,
        )

    def google_ads_creative(self, advertiser_id: str, creative_id: str) -> str:
        """Get one Google ad creative with its impression history.

        One creative in full, and the only endpoint carrying its history: every size variation of the asset, the
        impression bucket, the per-region breakdown with first and last shown dates and a per-surface impression split
        inside each region, the format, Google's category label and the funder disclosure on political ads.
        Impressions and first_shown are EEA-only (DSA-compelled) and come back null for US creatives, and an
        impression bucket may carry only a lower or only an upper bound.

        Args:
            advertiser_id (str): Google advertiser id, e.g. 'AR16735076323512287233' (3-40 characters).
            creative_id (str): Creative id (3-40 characters). It must belong to the advertiser_id sent with it --
                the lookup is keyed by the pair and a mismatched pair is a 404.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.google_ads.creative,
            advertiser_id,
            creative_id,
        )

    # --------------------------------------------------------- Meta Ad Library
    #
    # Meta Ad Library pages 30 ads first and 10 per cursor page after that, and every page costs 1 credit.
    # total_results caps at 50000 with total_is_capped set, because Meta only ever reports '>50,000' - never present
    # it as an exact count.

    def meta_ads_search(
        self,
        query: str,
        country: Optional[str] = None,
        active_status: Optional[str] = None,
        ad_type: Optional[str] = None,
        media_type: Optional[str] = None,
        search_type: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Search the Meta Ad Library by keyword.

        Search the Meta Ad Library by keyword: 30 ads on page 1 with the full creative -- page name, ad copy,
        headline, CTA, images and videos, the platforms each ran on and its run dates -- then 10 ads per cursor page,
        walking has_next_page to the end of the query. total_results caps at 50000 with total_is_capped true, because
        Meta only reports '>50,000'; never present it as an exact count. Every page costs 1 credit.

        Args:
            query (str): Keyword to search the ad library for (1-200 characters).
            country (Optional[str]): Ad library country as an exactly 2-character ISO 3166-1 alpha-2 code (server
                default 'US').
            active_status (Optional[str]): Whether the ad is still running (server default 'all'). One of: "all",
                "active", "inactive".
            ad_type (Optional[str]): Set 'political_and_issue_ads' to expose spend, reach, impressions and the
                paid-for-by disclosure; commercial ads leave all four null (server default 'all').
            media_type (Optional[str]): Creative media filter. Default: no media filter. One of: "all", "image",
                "video", "meme", "image_and_meme", "none".
            search_type (Optional[str]): How the query is matched (server default 'keyword_unordered').
            cursor (Optional[str]): next_cursor from the previous response: page 1 is 30 ads, every cursor page is
                10. The cursor is a self-contained blob, so ALL other filters are ignored when it is present.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.meta_ads.search,
            query,
            country=country,
            active_status=active_status,
            ad_type=ad_type,
            media_type=media_type,
            search_type=search_type,
            cursor=cursor,
        )

    def meta_ads_advertiser(
        self,
        page_id: str,
        country: Optional[str] = None,
        active_status: Optional[str] = None,
        ad_type: Optional[str] = None,
        media_type: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List every ad a Facebook Page is running.

        Every ad a Facebook Page is running, by numeric page id: 30 ads on page 1 with the same creative detail as
        meta_ads_search(), then 10 ads per cursor page, walking has_next_page to the end of the advertiser. Every page
        costs 1 credit.

        Args:
            page_id (str): The advertiser's numeric Facebook Page id (3-25 digits, as a string).
            country (Optional[str]): Ad library country as an exactly 2-character ISO 3166-1 alpha-2 code (server
                default 'US').
            active_status (Optional[str]): Whether the ad is still running (server default 'all'). One of: "all",
                "active", "inactive".
            ad_type (Optional[str]): Set 'political_and_issue_ads' to expose spend, reach, impressions and the
                paid-for-by disclosure; commercial ads leave all four null (server default 'all').
            media_type (Optional[str]): Creative media filter. Default: no media filter. One of: "all", "image",
                "video", "meme", "image_and_meme", "none".
            cursor (Optional[str]): next_cursor from the previous response: page 1 is 30 ads, every cursor page is
                10. ALL other filters are ignored when it is present.

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.meta_ads.advertiser,
            page_id,
            country=country,
            active_status=active_status,
            ad_type=ad_type,
            media_type=media_type,
            cursor=cursor,
        )

    def meta_ads_ad(self, ad_archive_id: str) -> str:
        """Get one Meta ad by archive id.

        One Meta ad in full by archive id: creative, advertiser, run dates, the platforms it ran on, and the political
        disclosure when the ad carries one. Commercial ads leave spend, reach and impressions null.

        Args:
            ad_archive_id (str): Meta ad archive id (3-25 digits, as a string).

        Returns:
            str: JSON string of the API response. Costs 1 credit.
        """
        return self._call(
            self.client.meta_ads.ad,
            ad_archive_id,
        )

    # ------------------------------------------------------- Extract (any URL)
    #
    # Extract is not a platform, it is the core 'read this page' primitive. It is TIER-PRICED by mode and only a
    # successful extraction is billed, so a dead link, bot wall or timeout costs nothing.

    def extract_url(
        self,
        url: str,
        format: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> str:
        """Read any URL and get the page back as HTML, Markdown or plain text.

        Tier-priced by mode -- normal and advanced cost 1 credit, ultra costs 2 -- and only a successful extraction is
        billed, so a dead link, bot wall or timeout costs nothing.

        Args:
            url (str): Page to read (1-2048 characters). http(s) only; a bare host is upgraded to https, and
                loopback, private, link-local and metadata hosts are rejected with a 400.
            format (Optional[str]): Output format: 'html' is the raw page, 'markdown' a readability extraction,
                'text' that markdown flattened to plain text (server default 'markdown').
            mode (Optional[str]): Fetch tier, and the price-bearing parameter: 'normal' plain datacenter fetch (1
                credit), 'advanced' full browser render (1 credit), 'ultra' the hardest-target tier (2 credits).
                Server default 'normal'.

        Returns:
            str: JSON string of the API response. Tier-priced by mode: 'normal' and 'advanced' cost 1 credit, 'ultra'
            costs 2. Only a successful extraction is billed - a dead link, bot wall or timeout costs nothing.
        """
        return self._call(
            self.client.extract,
            url,
            format=format,
            mode=mode,
        )
