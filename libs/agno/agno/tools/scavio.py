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
        all: bool = False,
        **kwargs,
    ):
        """Initialize ScavioTools, a unified search toolkit for AI agents.

        Scavio is a single Search API over Google, YouTube, Amazon, Walmart, Reddit,
        TikTok, TikTok Shop, Instagram, X, and LinkedIn. The toolkit exposes 97 tools,
        one per live billable endpoint, so every provider is gated by an ``enable_*``
        flag: register only what the agent needs rather than putting 97 tool
        definitions in front of the model.

        Credits are charged per call and are not uniform - most endpoints are 1, but
        YouTube transcripts are 8, LinkedIn job detail is 30, and most Instagram calls
        are 10. Each tool docstring states its own cost.

        Args:
            api_key: Scavio API key. If not provided, the ``SCAVIO_API_KEY`` env var is used.
            enable_google: Register the 14 Google tools: web search, AI Mode, Maps, Shopping,
                Flights, Hotels, News and Trends. Defaults to True.
            enable_amazon: Register the Amazon search, product, and offer-listing tools. Defaults to True.
            enable_walmart: Register the Walmart search and product tools. Defaults to True.
            enable_youtube: Register the 15 YouTube tools: search, Shorts, suggestions, video,
                comments, transcript, related, channel and streams. Defaults to True.
            enable_reddit: Register the Reddit search, post, subreddit, user, popular, and trending tools. Defaults to True.
            enable_tiktok: Register the TikTok tools. Defaults to True.
            enable_instagram: Register the Instagram tools. Defaults to True.
            enable_x: Register the X search, tweet, user, and trending tools. Defaults to True.
            enable_linkedin: Register the LinkedIn person, company, search, job, and post tools. Defaults to True.
            enable_tiktok_shop: Register the TikTok Shop search, product, review, category, shop, and URL-resolution tools. Defaults to True.
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
        if all or enable_walmart:
            tools.append(self.walmart_search)
            tools.append(self.walmart_product)
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

    # ----------------------------------------------------------------- Walmart

    def walmart_search(
        self,
        query: str,
        domain: Optional[str] = None,
        device: Optional[str] = None,
        sort_by: Optional[str] = None,
        start_page: Optional[int] = None,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        fulfillment_speed: Optional[str] = None,
        fulfillment_type: Optional[str] = None,
        delivery_zip: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> str:
        """Search Walmart for products matching a query.

        Args:
            query (str): The product search query.
            domain (Optional[str]): Walmart domain.
            device (Optional[str]): "desktop", "mobile" or "tablet".
            sort_by (Optional[str]): "best_match", "price_low", "price_high" or "best_seller".
            start_page (Optional[int]): Page to fetch, 1-based. Walmart pages on start_page;
                there is no page param here.
            min_price (Optional[int]): Minimum price filter.
            max_price (Optional[int]): Maximum price filter.
            fulfillment_speed (Optional[str]): "today", "tomorrow", "2_days" or "anytime".
            fulfillment_type (Optional[str]): "in_store" is the only accepted value.
            delivery_zip (Optional[str]): Delivery ZIP/postal code.
            store_id (Optional[str]): Restrict to a store.

        Returns:
            str: JSON string of matching products. Costs 1 credit.
        """
        return self._call(
            self.client.walmart.search,
            query,
            domain=domain,
            device=device,
            sort_by=sort_by,
            start_page=start_page,
            min_price=min_price,
            max_price=max_price,
            fulfillment_speed=fulfillment_speed,
            fulfillment_type=fulfillment_type,
            delivery_zip=delivery_zip,
            store_id=store_id,
        )

    def walmart_product(
        self,
        product_id: str,
        domain: Optional[str] = None,
        device: Optional[str] = None,
        delivery_zip: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> str:
        """Get full details for a single Walmart product by product ID.

        Args:
            product_id (str): The Walmart product id. Walmart identifies products by
                product_id, never by a query string or an ASIN.
            domain (Optional[str]): Walmart domain.
            device (Optional[str]): "desktop", "mobile" or "tablet".
            delivery_zip (Optional[str]): Delivery ZIP/postal code.
            store_id (Optional[str]): Restrict to a store.

        Returns:
            str: JSON string of the product details. Costs 1 credit.
        """
        return self._call(
            self.client.walmart.product,
            product_id,
            domain=domain,
            device=device,
            delivery_zip=delivery_zip,
            store_id=store_id,
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
