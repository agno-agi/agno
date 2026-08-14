import json
from os import getenv
from typing import Any, Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_warning

try:
    from scavio import ScavioClient
except ImportError:
    raise ImportError("`scavio` not installed. Please install using `pip install scavio`")


class ScavioTools(Toolkit):
    """Unified search toolkit for Google, YouTube, Amazon, Walmart, Reddit, TikTok, and Instagram.

    Scavio provides real-time data from multiple platforms. Use include_tools/exclude_tools
    to register only the tools you need.

    Requires `pip install scavio` and a SCAVIO_API_KEY from https://scavio.dev
    """

    # Tool name constants for include_tools/exclude_tools
    # Google
    SEARCH_GOOGLE = "search_google"
    # Amazon
    SEARCH_AMAZON = "search_amazon"
    GET_AMAZON_PRODUCT = "get_amazon_product"
    # Walmart
    SEARCH_WALMART = "search_walmart"
    GET_WALMART_PRODUCT = "get_walmart_product"
    # YouTube
    SEARCH_YOUTUBE = "search_youtube"
    GET_YOUTUBE_VIDEO = "get_youtube_video"
    # Reddit
    SEARCH_REDDIT = "search_reddit"
    GET_REDDIT_POST = "get_reddit_post"
    # TikTok
    GET_TIKTOK_PROFILE = "get_tiktok_profile"
    LIST_TIKTOK_POSTS = "list_tiktok_posts"
    GET_TIKTOK_VIDEO = "get_tiktok_video"
    LIST_TIKTOK_VIDEO_COMMENTS = "list_tiktok_video_comments"
    LIST_TIKTOK_COMMENT_REPLIES = "list_tiktok_comment_replies"
    SEARCH_TIKTOK_VIDEOS = "search_tiktok_videos"
    SEARCH_TIKTOK_USERS = "search_tiktok_users"
    GET_TIKTOK_HASHTAG = "get_tiktok_hashtag"
    LIST_TIKTOK_HASHTAG_VIDEOS = "list_tiktok_hashtag_videos"
    LIST_TIKTOK_FOLLOWERS = "list_tiktok_followers"
    LIST_TIKTOK_FOLLOWINGS = "list_tiktok_followings"
    # Instagram
    GET_INSTAGRAM_PROFILE = "get_instagram_profile"
    LIST_INSTAGRAM_POSTS = "list_instagram_posts"
    LIST_INSTAGRAM_REELS = "list_instagram_reels"
    LIST_INSTAGRAM_TAGGED = "list_instagram_tagged"
    LIST_INSTAGRAM_STORIES = "list_instagram_stories"
    GET_INSTAGRAM_POST = "get_instagram_post"
    LIST_INSTAGRAM_POST_COMMENTS = "list_instagram_post_comments"
    LIST_INSTAGRAM_COMMENT_REPLIES = "list_instagram_comment_replies"
    SEARCH_INSTAGRAM_USERS = "search_instagram_users"
    SEARCH_INSTAGRAM_HASHTAGS = "search_instagram_hashtags"
    LIST_INSTAGRAM_FOLLOWERS = "list_instagram_followers"
    LIST_INSTAGRAM_FOLLOWINGS = "list_instagram_followings"

    @classmethod
    def _all_tool_names(cls) -> List[str]:
        return [value for key, value in vars(cls).items() if key.isupper() and isinstance(value, str)]

    # Agno 2.x per-provider flags, consumed below and translated to exclude_tools
    _legacy_param_aliases = {
        "enable_google": None,
        "enable_amazon": None,
        "enable_walmart": None,
        "enable_youtube": None,
        "enable_reddit": None,
        "enable_tiktok": None,
        "enable_instagram": None,
    }

    def __init__(self, api_key: Optional[str] = None, **kwargs):
        """Initialize ScavioTools for multi-platform search.

        Args:
            api_key: Scavio API key. Falls back to SCAVIO_API_KEY env var.
            **kwargs: Passed to Toolkit. Use include_tools/exclude_tools to filter.

        Example:
            # Include only Google and YouTube
            ScavioTools(include_tools=[ScavioTools.SEARCH_GOOGLE, ScavioTools.SEARCH_YOUTUBE])

            # Exclude TikTok tools
            ScavioTools(exclude_tools=[ScavioTools.GET_TIKTOK_PROFILE, ScavioTools.LIST_TIKTOK_POSTS])
        """
        # Translate deprecated 2.x per-provider flags (enable_tiktok=False, ...)
        # into an exclude_tools list, unless the caller filters explicitly
        legacy_excluded: List[str] = []
        for legacy_flag in list(self._legacy_param_aliases):
            if legacy_flag in kwargs:
                provider = legacy_flag[len("enable_") :]
                enabled = kwargs.pop(legacy_flag)
                log_warning(f"`{legacy_flag}` is deprecated for ScavioTools; use include_tools/exclude_tools instead.")
                if not enabled:
                    legacy_excluded.extend(name for name in self._all_tool_names() if provider in name)
        if legacy_excluded and kwargs.get("include_tools") is None and kwargs.get("exclude_tools") is None:
            kwargs["exclude_tools"] = sorted(legacy_excluded)

        self.api_key = api_key or getenv("SCAVIO_API_KEY")
        if not self.api_key:
            log_error("SCAVIO_API_KEY not provided")

        self.client: ScavioClient = ScavioClient(api_key=self.api_key)

        tools: List[Callable] = [
            # Google
            self.search_google,
            # Amazon
            self.search_amazon,
            self.get_amazon_product,
            # Walmart
            self.search_walmart,
            self.get_walmart_product,
            # YouTube
            self.search_youtube,
            self.get_youtube_video,
            # Reddit
            self.search_reddit,
            self.get_reddit_post,
            # TikTok
            self.get_tiktok_profile,
            self.list_tiktok_posts,
            self.get_tiktok_video,
            self.list_tiktok_video_comments,
            self.list_tiktok_comment_replies,
            self.search_tiktok_videos,
            self.search_tiktok_users,
            self.get_tiktok_hashtag,
            self.list_tiktok_hashtag_videos,
            self.list_tiktok_followers,
            self.list_tiktok_followings,
            # Instagram
            self.get_instagram_profile,
            self.list_instagram_posts,
            self.list_instagram_reels,
            self.list_instagram_tagged,
            self.list_instagram_stories,
            self.get_instagram_post,
            self.list_instagram_post_comments,
            self.list_instagram_comment_replies,
            self.search_instagram_users,
            self.search_instagram_hashtags,
            self.list_instagram_followers,
            self.list_instagram_followings,
        ]

        super().__init__(name="scavio", tools=tools, **kwargs)

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        """Run a Scavio SDK call and return its JSON response as a string."""
        try:
            return json.dumps(fn(*args, **kwargs))
        except Exception as e:
            log_error(f"Scavio request failed: {e}")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------ Google

    def search_google(
        self,
        query: str,
        gl: Optional[str] = None,
        hl: Optional[str] = None,
        start: Optional[int] = None,
        device: Optional[str] = None,
        nfpr: Optional[bool] = None,
        google_domain: Optional[str] = None,
        location: Optional[str] = None,
        safe: Optional[str] = None,
        time_period: Optional[str] = None,
    ) -> str:
        """Search Google for real-time organic web results.

        Args:
            query: Search query.
            gl: Two-letter country code (e.g. "us").
            hl: Two-letter language code (e.g. "en").
            start: Result offset for pagination (0, 10, 20, ...).
            device: "desktop" or "mobile".
            nfpr: Disable auto-correction when True.
            google_domain: Regional domain (e.g. "google.co.uk").
            location: Location to search from (e.g. "New York,New York,United States").
            safe: "active" to filter adult content.
            time_period: "last_hour", "last_day", "last_week", "last_month", or "last_year".

        Returns:
            JSON with organic_results list (title, link, snippet).
        """
        return self._call(
            self.client.google.search,
            query,
            gl=gl,
            hl=hl,
            start=start,
            device=device,
            nfpr=nfpr,
            google_domain=google_domain,
            location=location,
            safe=safe,
            time_period=time_period,
        )

    # ------------------------------------------------------------------ Amazon

    def search_amazon(
        self,
        query: str,
        domain: Optional[str] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        currency: Optional[str] = None,
        device: Optional[str] = None,
        sort_by: Optional[str] = None,
        start_page: Optional[int] = None,
        pages: Optional[int] = None,
        category_id: Optional[str] = None,
        merchant_id: Optional[str] = None,
        zip_code: Optional[str] = None,
        autoselect_variant: Optional[bool] = None,
    ) -> str:
        """Search Amazon for products.

        Args:
            query: Product search query.
            domain: Amazon domain (e.g. "amazon.com").
            country: Delivery country code.
            language: Language code for results.
            currency: Currency code for prices.
            device: "desktop" or "mobile".
            sort_by: Sort order.
            start_page: First page to fetch.
            pages: Number of pages to fetch.
            category_id: Restrict to category.
            merchant_id: Restrict to merchant.
            zip_code: Delivery ZIP code.
            autoselect_variant: Auto-select variant when True.

        Returns:
            JSON with matching products.
        """
        return self._call(
            self.client.amazon.search,
            query,
            domain=domain,
            country=country,
            language=language,
            currency=currency,
            device=device,
            sort_by=sort_by,
            start_page=start_page,
            pages=pages,
            category_id=category_id,
            merchant_id=merchant_id,
            zip_code=zip_code,
            autoselect_variant=autoselect_variant,
        )

    def get_amazon_product(
        self,
        asin: str,
        domain: Optional[str] = None,
        country: Optional[str] = None,
        language: Optional[str] = None,
        currency: Optional[str] = None,
        device: Optional[str] = None,
        zip_code: Optional[str] = None,
        autoselect_variant: Optional[bool] = None,
    ) -> str:
        """Get details for an Amazon product by ASIN.

        Args:
            asin: Amazon Standard Identification Number.
            domain: Amazon domain (e.g. "amazon.com").
            country: Delivery country code.
            language: Language code.
            currency: Currency code.
            device: "desktop" or "mobile".
            zip_code: Delivery ZIP code.
            autoselect_variant: Auto-select variant when True.

        Returns:
            JSON with product details.
        """
        return self._call(
            self.client.amazon.product,
            asin,
            domain=domain,
            country=country,
            language=language,
            currency=currency,
            device=device,
            zip_code=zip_code,
            autoselect_variant=autoselect_variant,
        )

    # ----------------------------------------------------------------- Walmart

    def search_walmart(
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
        """Search Walmart for products.

        Args:
            query: Product search query.
            domain: Walmart domain.
            device: "desktop" or "mobile".
            sort_by: Sort order.
            start_page: First page to fetch.
            min_price: Minimum price filter.
            max_price: Maximum price filter.
            fulfillment_speed: Fulfillment speed filter.
            fulfillment_type: Fulfillment type filter.
            delivery_zip: Delivery ZIP code.
            store_id: Restrict to store.

        Returns:
            JSON with matching products.
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

    def get_walmart_product(
        self,
        product_id: str,
        domain: Optional[str] = None,
        device: Optional[str] = None,
        delivery_zip: Optional[str] = None,
        store_id: Optional[str] = None,
    ) -> str:
        """Get details for a Walmart product.

        Args:
            product_id: Walmart product ID.
            domain: Walmart domain.
            device: "desktop" or "mobile".
            delivery_zip: Delivery ZIP code.
            store_id: Restrict to store.

        Returns:
            JSON with product details.
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

    def search_youtube(
        self,
        query: str,
        upload_date: Optional[str] = None,
        type: Optional[str] = None,
        duration: Optional[str] = None,
        sort_by: Optional[str] = None,
        hd: Optional[bool] = None,
        subtitles: Optional[bool] = None,
        creative_commons: Optional[bool] = None,
        live: Optional[bool] = None,
    ) -> str:
        """Search YouTube for videos.

        Args:
            query: Search query.
            upload_date: Filter by upload date.
            type: "video", "channel", or "playlist".
            duration: Video duration filter.
            sort_by: Sort order.
            hd: Restrict to HD videos.
            subtitles: Restrict to videos with subtitles.
            creative_commons: Restrict to Creative Commons.
            live: Restrict to live videos.

        Returns:
            JSON with matching videos.
        """
        return self._call(
            self.client.youtube.search,
            query,
            upload_date=upload_date,
            type=type,
            duration=duration,
            sort_by=sort_by,
            hd=hd,
            subtitles=subtitles,
            creative_commons=creative_commons,
            live=live,
        )

    def get_youtube_video(self, video_id: str) -> str:
        """Get metadata for a YouTube video.

        Args:
            video_id: YouTube video ID.

        Returns:
            JSON with video metadata (title, description, views, etc).
        """
        return self._call(self.client.youtube.metadata, video_id)

    # ------------------------------------------------------------------ Reddit

    def search_reddit(
        self,
        query: str,
        type: Optional[str] = None,
        sort: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Search Reddit for posts or communities.

        Args:
            query: Search query.
            type: "posts" or "communities".
            sort: Sort order.
            cursor: Pagination cursor.

        Returns:
            JSON with search results.
        """
        return self._call(self.client.reddit.search, query, type=type, sort=sort, cursor=cursor)

    def get_reddit_post(self, url: str) -> str:
        """Get a Reddit post with its comments.

        Args:
            url: Full URL of the Reddit post.

        Returns:
            JSON with post and threaded comments.
        """
        return self._call(self.client.reddit.post, url)

    # ------------------------------------------------------------------ TikTok

    def get_tiktok_profile(self, username: Optional[str] = None, sec_user_id: Optional[str] = None) -> str:
        """Get a TikTok user profile.

        Args:
            username: TikTok username (without "@").
            sec_user_id: TikTok secUid. Provide username or sec_user_id.

        Returns:
            JSON with profile data.
        """
        return self._call(self.client.tiktok.profile, username=username, sec_user_id=sec_user_id)

    def list_tiktok_posts(
        self,
        sec_user_id: str,
        cursor: Optional[str] = None,
        count: Optional[int] = None,
        sort_type: Optional[str] = None,
    ) -> str:
        """List videos posted by a TikTok user.

        Args:
            sec_user_id: TikTok secUid.
            cursor: Pagination cursor.
            count: Number of posts to return.
            sort_type: Sort order.

        Returns:
            JSON with user's posts.
        """
        return self._call(self.client.tiktok.user_posts, sec_user_id, cursor=cursor, count=count, sort_type=sort_type)

    def get_tiktok_video(self, video_id: str) -> str:
        """Get details for a TikTok video.

        Args:
            video_id: TikTok video ID.

        Returns:
            JSON with video details.
        """
        return self._call(self.client.tiktok.video, video_id)

    def list_tiktok_video_comments(
        self, video_id: str, cursor: Optional[str] = None, count: Optional[int] = None
    ) -> str:
        """List comments on a TikTok video.

        Args:
            video_id: TikTok video ID.
            cursor: Pagination cursor.
            count: Number of comments to return.

        Returns:
            JSON with comments.
        """
        return self._call(self.client.tiktok.video_comments, video_id, cursor=cursor, count=count)

    def list_tiktok_comment_replies(
        self, video_id: str, comment_id: str, cursor: Optional[str] = None, count: Optional[int] = None
    ) -> str:
        """List replies to a TikTok comment.

        Args:
            video_id: TikTok video ID.
            comment_id: Comment ID.
            cursor: Pagination cursor.
            count: Number of replies to return.

        Returns:
            JSON with replies.
        """
        return self._call(self.client.tiktok.comment_replies, video_id, comment_id, cursor=cursor, count=count)

    def search_tiktok_videos(
        self,
        keyword: str,
        cursor: Optional[str] = None,
        count: Optional[int] = None,
        sort_type: Optional[str] = None,
        publish_time: Optional[str] = None,
    ) -> str:
        """Search TikTok for videos.

        Args:
            keyword: Search keyword.
            cursor: Pagination cursor.
            count: Number of videos to return.
            sort_type: Sort order.
            publish_time: Filter by publish time window.

        Returns:
            JSON with matching videos.
        """
        return self._call(
            self.client.tiktok.search_videos,
            keyword,
            cursor=cursor,
            count=count,
            sort_type=sort_type,
            publish_time=publish_time,
        )

    def search_tiktok_users(self, keyword: str, cursor: Optional[str] = None, count: Optional[int] = None) -> str:
        """Search TikTok for users.

        Args:
            keyword: Search keyword.
            cursor: Pagination cursor.
            count: Number of users to return.

        Returns:
            JSON with matching users.
        """
        return self._call(self.client.tiktok.search_users, keyword, cursor=cursor, count=count)

    def get_tiktok_hashtag(self, hashtag_name: Optional[str] = None, hashtag_id: Optional[str] = None) -> str:
        """Get information about a TikTok hashtag.

        Args:
            hashtag_name: Hashtag name (without "#").
            hashtag_id: Hashtag ID. Provide hashtag_name or hashtag_id.

        Returns:
            JSON with hashtag info.
        """
        return self._call(self.client.tiktok.hashtag, hashtag_name=hashtag_name, hashtag_id=hashtag_id)

    def list_tiktok_hashtag_videos(
        self, hashtag_id: str, cursor: Optional[str] = None, count: Optional[int] = None
    ) -> str:
        """List videos for a TikTok hashtag.

        Args:
            hashtag_id: Hashtag ID (from get_tiktok_hashtag).
            cursor: Pagination cursor.
            count: Number of videos to return.

        Returns:
            JSON with hashtag videos.
        """
        return self._call(self.client.tiktok.hashtag_videos, hashtag_id, cursor=cursor, count=count)

    def list_tiktok_followers(
        self,
        sec_user_id: str,
        count: Optional[int] = None,
        page_token: Optional[str] = None,
        min_time: Optional[int] = None,
    ) -> str:
        """List followers of a TikTok user.

        Args:
            sec_user_id: TikTok secUid.
            count: Number of followers to return.
            page_token: Pagination token.
            min_time: Minimum timestamp filter.

        Returns:
            JSON with followers.
        """
        return self._call(
            self.client.tiktok.user_followers, sec_user_id, count=count, page_token=page_token, min_time=min_time
        )

    def list_tiktok_followings(
        self,
        sec_user_id: str,
        count: Optional[int] = None,
        page_token: Optional[str] = None,
        min_time: Optional[int] = None,
    ) -> str:
        """List accounts a TikTok user follows.

        Args:
            sec_user_id: TikTok secUid.
            count: Number of followings to return.
            page_token: Pagination token.
            min_time: Minimum timestamp filter.

        Returns:
            JSON with followings.
        """
        return self._call(
            self.client.tiktok.user_followings, sec_user_id, count=count, page_token=page_token, min_time=min_time
        )

    # --------------------------------------------------------------- Instagram

    def get_instagram_profile(self, username: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """Get an Instagram user profile.

        Args:
            username: Instagram username (without "@").
            user_id: Instagram user ID. Provide username or user_id.

        Returns:
            JSON with profile data.
        """
        return self._call(self.client.instagram.profile, username=username, user_id=user_id)

    def list_instagram_posts(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List posts by an Instagram user.

        Args:
            username: Instagram username.
            user_id: Instagram user ID. Provide username or user_id.
            count: Number of posts to return.
            cursor: Pagination cursor.

        Returns:
            JSON with user's posts.
        """
        return self._call(
            self.client.instagram.user_posts, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def list_instagram_reels(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List reels by an Instagram user.

        Args:
            username: Instagram username.
            user_id: Instagram user ID. Provide username or user_id.
            count: Number of reels to return.
            cursor: Pagination cursor.

        Returns:
            JSON with user's reels.
        """
        return self._call(
            self.client.instagram.user_reels, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def list_instagram_tagged(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List posts an Instagram user is tagged in.

        Args:
            username: Instagram username.
            user_id: Instagram user ID. Provide username or user_id.
            count: Number of posts to return.
            cursor: Pagination cursor.

        Returns:
            JSON with tagged posts.
        """
        return self._call(
            self.client.instagram.user_tagged, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def list_instagram_stories(self, username: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """List active stories of an Instagram user.

        Args:
            username: Instagram username.
            user_id: Instagram user ID. Provide username or user_id.

        Returns:
            JSON with user's stories.
        """
        return self._call(self.client.instagram.user_stories, username=username, user_id=user_id)

    def get_instagram_post(
        self,
        url: Optional[str] = None,
        media_id: Optional[str] = None,
        shortcode: Optional[str] = None,
    ) -> str:
        """Get an Instagram post.

        Args:
            url: Full URL of the post.
            media_id: Post media ID.
            shortcode: Post shortcode. Provide one of url, media_id, or shortcode.

        Returns:
            JSON with post data.
        """
        return self._call(self.client.instagram.post, url=url, media_id=media_id, shortcode=shortcode)

    def list_instagram_post_comments(
        self,
        shortcode: Optional[str] = None,
        url: Optional[str] = None,
        cursor: Optional[str] = None,
        sort_order: Optional[str] = None,
    ) -> str:
        """List comments on an Instagram post.

        Args:
            shortcode: Post shortcode.
            url: Full URL of the post. Provide shortcode or url.
            cursor: Pagination cursor.
            sort_order: Sort order for comments.

        Returns:
            JSON with comments.
        """
        return self._call(
            self.client.instagram.post_comments, shortcode=shortcode, url=url, cursor=cursor, sort_order=sort_order
        )

    def list_instagram_comment_replies(self, media_id: str, comment_id: str, cursor: Optional[str] = None) -> str:
        """List replies to an Instagram comment.

        Args:
            media_id: Post media ID.
            comment_id: Comment ID.
            cursor: Pagination cursor.

        Returns:
            JSON with replies.
        """
        return self._call(self.client.instagram.comment_replies, media_id, comment_id, cursor=cursor)

    def search_instagram_users(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Instagram for users.

        Args:
            keyword: Search keyword.
            cursor: Pagination cursor.

        Returns:
            JSON with matching users.
        """
        return self._call(self.client.instagram.search_users, keyword, cursor=cursor)

    def search_instagram_hashtags(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Instagram for hashtags.

        Args:
            keyword: Search keyword.
            cursor: Pagination cursor.

        Returns:
            JSON with matching hashtags.
        """
        return self._call(self.client.instagram.search_hashtags, keyword, cursor=cursor)

    def list_instagram_followers(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List followers of an Instagram user.

        Args:
            username: Instagram username.
            user_id: Instagram user ID. Provide username or user_id.
            count: Number of followers to return.
            cursor: Pagination cursor.

        Returns:
            JSON with followers.
        """
        return self._call(
            self.client.instagram.user_followers, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def list_instagram_followings(
        self,
        username: Optional[str] = None,
        user_id: Optional[str] = None,
        count: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """List accounts an Instagram user follows.

        Args:
            username: Instagram username.
            user_id: Instagram user ID. Provide username or user_id.
            count: Number of followings to return.
            cursor: Pagination cursor.

        Returns:
            JSON with followings.
        """
        return self._call(
            self.client.instagram.user_followings, username=username, user_id=user_id, count=count, cursor=cursor
        )
