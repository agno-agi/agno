import json
from os import getenv
from typing import Any, Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from scavio import ScavioClient
except ImportError:
    raise ImportError("`scavio` not installed. Please install using `pip install scavio`")


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
        all: bool = False,
        **kwargs,
    ):
        """Initialize ScavioTools, a unified search toolkit for AI agents.

        Scavio is a single Search API over Google, YouTube, Amazon, Walmart, Reddit,
        TikTok, and Instagram. Each provider is gated by an ``enable_*`` flag so you can
        expose only the tools your agent needs.

        Args:
            api_key: Scavio API key. If not provided, the ``SCAVIO_API_KEY`` env var is used.
            enable_google: Register the Google web search tool. Defaults to True.
            enable_amazon: Register the Amazon search and product tools. Defaults to True.
            enable_walmart: Register the Walmart search and product tools. Defaults to True.
            enable_youtube: Register the YouTube search and metadata tools. Defaults to True.
            enable_reddit: Register the Reddit search and post tools. Defaults to True.
            enable_tiktok: Register the TikTok tools. Defaults to True.
            enable_instagram: Register the Instagram tools. Defaults to True.
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
        if all or enable_amazon:
            tools.append(self.amazon_search)
            tools.append(self.amazon_product)
        if all or enable_walmart:
            tools.append(self.walmart_search)
            tools.append(self.walmart_product)
        if all or enable_youtube:
            tools.append(self.youtube_search)
            tools.append(self.youtube_metadata)
        if all or enable_reddit:
            tools.append(self.reddit_search)
            tools.append(self.reddit_post)
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

        super().__init__(name="scavio", tools=tools, **kwargs)

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        """Run a Scavio SDK call and return its JSON response as a string."""
        try:
            return json.dumps(fn(*args, **kwargs))
        except Exception as e:
            log_error(f"Scavio request failed: {e}")
            return json.dumps({"error": str(e)})

    # ------------------------------------------------------------------ Google

    def google_search(
        self,
        query: str,
        country_code: Optional[str] = None,
        language: Optional[str] = None,
        page: Optional[int] = None,
        search_type: Optional[str] = None,
        device: Optional[str] = None,
        nfpr: Optional[bool] = None,
        light_request: Optional[bool] = None,
    ) -> str:
        """Search Google for real-time web results.

        Args:
            query (str): The search query.
            country_code (Optional[str]): Two-letter country code to localize results (e.g. "us").
            language (Optional[str]): Two-letter language code for results (e.g. "en").
            page (Optional[int]): Result page number (1-based).
            search_type (Optional[str]): Result type: "classic", "news", "maps", or "images".
            device (Optional[str]): "desktop" or "mobile".
            nfpr (Optional[bool]): Disable auto-correction / spelling suggestions when True.
            light_request (Optional[bool]): Return a lighter, cheaper response when True.

        Returns:
            str: JSON string of search results.
        """
        return self._call(
            self.client.google.search,
            query,
            country_code=country_code,
            language=language,
            page=page,
            search_type=search_type,
            device=device,
            nfpr=nfpr,
            light_request=light_request,
        )

    # ------------------------------------------------------------------ Amazon

    def amazon_search(
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
        """Search Amazon for products matching a query.

        Args:
            query (str): The product search query.
            domain (Optional[str]): Amazon domain (e.g. "amazon.com").
            country (Optional[str]): Delivery country code.
            language (Optional[str]): Language code for results.
            currency (Optional[str]): Currency code for prices.
            device (Optional[str]): "desktop" or "mobile".
            sort_by (Optional[str]): Sort order for results.
            start_page (Optional[int]): First page to fetch.
            pages (Optional[int]): Number of pages to fetch.
            category_id (Optional[str]): Restrict to an Amazon category.
            merchant_id (Optional[str]): Restrict to a merchant.
            zip_code (Optional[str]): Delivery ZIP/postal code.
            autoselect_variant (Optional[bool]): Auto-select a product variant when True.

        Returns:
            str: JSON string of matching products.
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

    def amazon_product(
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
        """Get full details for a single Amazon product by ASIN.

        Args:
            asin (str): The Amazon Standard Identification Number (ASIN).
            domain (Optional[str]): Amazon domain (e.g. "amazon.com").
            country (Optional[str]): Delivery country code.
            language (Optional[str]): Language code for results.
            currency (Optional[str]): Currency code for prices.
            device (Optional[str]): "desktop" or "mobile".
            zip_code (Optional[str]): Delivery ZIP/postal code.
            autoselect_variant (Optional[bool]): Auto-select a product variant when True.

        Returns:
            str: JSON string of the product details.
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
            device (Optional[str]): "desktop" or "mobile".
            sort_by (Optional[str]): Sort order for results.
            start_page (Optional[int]): First page to fetch.
            min_price (Optional[int]): Minimum price filter.
            max_price (Optional[int]): Maximum price filter.
            fulfillment_speed (Optional[str]): Fulfillment speed filter.
            fulfillment_type (Optional[str]): Fulfillment type filter.
            delivery_zip (Optional[str]): Delivery ZIP/postal code.
            store_id (Optional[str]): Restrict to a store.

        Returns:
            str: JSON string of matching products.
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
            product_id (str): The Walmart product ID.
            domain (Optional[str]): Walmart domain.
            device (Optional[str]): "desktop" or "mobile".
            delivery_zip (Optional[str]): Delivery ZIP/postal code.
            store_id (Optional[str]): Restrict to a store.

        Returns:
            str: JSON string of the product details.
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

    def youtube_search(
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
        """Search YouTube for videos matching a query.

        Args:
            query (str): The search query.
            upload_date (Optional[str]): Filter by upload date.
            type (Optional[str]): Result type filter (e.g. "video", "channel", "playlist").
            duration (Optional[str]): Video duration filter.
            sort_by (Optional[str]): Sort order for results.
            hd (Optional[bool]): Restrict to HD videos when True.
            subtitles (Optional[bool]): Restrict to videos with subtitles when True.
            creative_commons (Optional[bool]): Restrict to Creative Commons videos when True.
            live (Optional[bool]): Restrict to live videos when True.

        Returns:
            str: JSON string of matching videos.
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

    def youtube_metadata(self, video_id: str) -> str:
        """Get structured metadata for a single YouTube video.

        Args:
            video_id (str): The YouTube video ID.

        Returns:
            str: JSON string of the video metadata.
        """
        return self._call(self.client.youtube.metadata, video_id)

    # ------------------------------------------------------------------ Reddit

    def reddit_search(
        self,
        query: str,
        type: Optional[str] = None,
        sort: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> str:
        """Search Reddit for posts or communities matching a query.

        Args:
            query (str): The search query.
            type (Optional[str]): What to search for (e.g. "posts", "communities").
            sort (Optional[str]): Sort order for results.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of search results.
        """
        return self._call(self.client.reddit.search, query, type=type, sort=sort, cursor=cursor)

    def reddit_post(self, url: str) -> str:
        """Fetch a Reddit post with its threaded comments by URL.

        Args:
            url (str): The full URL of the Reddit post.

        Returns:
            str: JSON string of the post and its comments.
        """
        return self._call(self.client.reddit.post, url)

    # ------------------------------------------------------------------ TikTok

    def tiktok_profile(self, username: Optional[str] = None, sec_user_id: Optional[str] = None) -> str:
        """Get a TikTok user profile.

        Args:
            username (Optional[str]): The TikTok username (without "@").
            sec_user_id (Optional[str]): The TikTok secUid. Provide this or username.

        Returns:
            str: JSON string of the profile.
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
            sec_user_id (str): The TikTok secUid of the user.
            cursor (Optional[str]): Pagination cursor from a previous response.
            count (Optional[int]): Number of posts to return.
            sort_type (Optional[str]): Sort order for posts.

        Returns:
            str: JSON string of the user's posts.
        """
        return self._call(self.client.tiktok.user_posts, sec_user_id, cursor=cursor, count=count, sort_type=sort_type)

    def tiktok_video(self, video_id: str) -> str:
        """Get details for a single TikTok video.

        Args:
            video_id (str): The TikTok video ID.

        Returns:
            str: JSON string of the video details.
        """
        return self._call(self.client.tiktok.video, video_id)

    def tiktok_video_comments(self, video_id: str, cursor: Optional[str] = None, count: Optional[int] = None) -> str:
        """List the comments on a TikTok video.

        Args:
            video_id (str): The TikTok video ID.
            cursor (Optional[str]): Pagination cursor from a previous response.
            count (Optional[int]): Number of comments to return.

        Returns:
            str: JSON string of the comments.
        """
        return self._call(self.client.tiktok.video_comments, video_id, cursor=cursor, count=count)

    def tiktok_comment_replies(
        self, video_id: str, comment_id: str, cursor: Optional[str] = None, count: Optional[int] = None
    ) -> str:
        """List the replies to a TikTok comment.

        Args:
            video_id (str): The TikTok video ID.
            comment_id (str): The comment ID to fetch replies for.
            cursor (Optional[str]): Pagination cursor from a previous response.
            count (Optional[int]): Number of replies to return.

        Returns:
            str: JSON string of the replies.
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
            keyword (str): The search keyword.
            cursor (Optional[str]): Pagination cursor from a previous response.
            count (Optional[int]): Number of videos to return.
            sort_type (Optional[str]): Sort order for results.
            publish_time (Optional[str]): Filter by publish time window.

        Returns:
            str: JSON string of matching videos.
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
            cursor (Optional[str]): Pagination cursor from a previous response.
            count (Optional[int]): Number of users to return.

        Returns:
            str: JSON string of matching users.
        """
        return self._call(self.client.tiktok.search_users, keyword, cursor=cursor, count=count)

    def tiktok_hashtag(self, hashtag_name: Optional[str] = None, hashtag_id: Optional[str] = None) -> str:
        """Get information about a TikTok hashtag.

        Args:
            hashtag_name (Optional[str]): The hashtag name (without "#").
            hashtag_id (Optional[str]): The hashtag ID. Provide this or hashtag_name.

        Returns:
            str: JSON string of the hashtag info.
        """
        return self._call(self.client.tiktok.hashtag, hashtag_name=hashtag_name, hashtag_id=hashtag_id)

    def tiktok_hashtag_videos(self, hashtag_id: str, cursor: Optional[str] = None, count: Optional[int] = None) -> str:
        """List videos for a TikTok hashtag.

        Args:
            hashtag_id (str): The hashtag ID (from tiktok_hashtag).
            cursor (Optional[str]): Pagination cursor from a previous response.
            count (Optional[int]): Number of videos to return.

        Returns:
            str: JSON string of the hashtag's videos.
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
            sec_user_id (str): The TikTok secUid of the user.
            count (Optional[int]): Number of followers to return.
            page_token (Optional[str]): Pagination token from a previous response.
            min_time (Optional[int]): Minimum timestamp filter.

        Returns:
            str: JSON string of the followers.
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
            sec_user_id (str): The TikTok secUid of the user.
            count (Optional[int]): Number of followings to return.
            page_token (Optional[str]): Pagination token from a previous response.
            min_time (Optional[int]): Minimum timestamp filter.

        Returns:
            str: JSON string of the followings.
        """
        return self._call(
            self.client.tiktok.user_followings, sec_user_id, count=count, page_token=page_token, min_time=min_time
        )

    # --------------------------------------------------------------- Instagram

    def instagram_profile(self, username: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """Get an Instagram user profile.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user ID. Provide this or username.

        Returns:
            str: JSON string of the profile.
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
            user_id (Optional[str]): The Instagram user ID. Provide this or username.
            count (Optional[int]): Number of posts to return.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's posts.
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
            user_id (Optional[str]): The Instagram user ID. Provide this or username.
            count (Optional[int]): Number of reels to return.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the user's reels.
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
            user_id (Optional[str]): The Instagram user ID. Provide this or username.
            count (Optional[int]): Number of posts to return.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the tagged posts.
        """
        return self._call(
            self.client.instagram.user_tagged, username=username, user_id=user_id, count=count, cursor=cursor
        )

    def instagram_user_stories(self, username: Optional[str] = None, user_id: Optional[str] = None) -> str:
        """Get the active stories of an Instagram user.

        Args:
            username (Optional[str]): The Instagram username (without "@").
            user_id (Optional[str]): The Instagram user ID. Provide this or username.

        Returns:
            str: JSON string of the user's stories.
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
            media_id (Optional[str]): The post media ID.
            shortcode (Optional[str]): The post shortcode. Provide one of url, media_id, or shortcode.

        Returns:
            str: JSON string of the post.
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
            url (Optional[str]): The full URL of the post. Provide shortcode or url.
            cursor (Optional[str]): Pagination cursor from a previous response.
            sort_order (Optional[str]): Sort order for comments.

        Returns:
            str: JSON string of the comments.
        """
        return self._call(
            self.client.instagram.post_comments, shortcode=shortcode, url=url, cursor=cursor, sort_order=sort_order
        )

    def instagram_comment_replies(self, media_id: str, comment_id: str, cursor: Optional[str] = None) -> str:
        """List the replies to an Instagram comment.

        Args:
            media_id (str): The post media ID.
            comment_id (str): The comment ID to fetch replies for.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the replies.
        """
        return self._call(self.client.instagram.comment_replies, media_id, comment_id, cursor=cursor)

    def instagram_search_users(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Instagram for users matching a keyword.

        Args:
            keyword (str): The search keyword.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of matching users.
        """
        return self._call(self.client.instagram.search_users, keyword, cursor=cursor)

    def instagram_search_hashtags(self, keyword: str, cursor: Optional[str] = None) -> str:
        """Search Instagram for hashtags matching a keyword.

        Args:
            keyword (str): The search keyword.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of matching hashtags.
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
            user_id (Optional[str]): The Instagram user ID. Provide this or username.
            count (Optional[int]): Number of followers to return.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the followers.
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
            user_id (Optional[str]): The Instagram user ID. Provide this or username.
            count (Optional[int]): Number of followings to return.
            cursor (Optional[str]): Pagination cursor from a previous response.

        Returns:
            str: JSON string of the followings.
        """
        return self._call(
            self.client.instagram.user_followings, username=username, user_id=user_id, count=count, cursor=cursor
        )
