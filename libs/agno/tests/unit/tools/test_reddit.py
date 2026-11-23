from __future__ import annotations

import json

import pytest

praw = pytest.importorskip("praw")

from agno.tools.reddit import RedditTools  # noqa: E402


class FakeSubreddit:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name
        self.flair = type("FakeFlair", (), {"link_templates": []})()
        self.submissions: list[dict[str, str]] = []

    def submit(self, **kwargs):
        self.submissions.append(kwargs)
        return FakeReply(subreddit=self, body=kwargs.get("selftext") or kwargs.get("url") or "")


class FakeReply:
    def __init__(self, subreddit: FakeSubreddit, body: str = "reply") -> None:
        self.id = "reply-id"
        self.body = body
        self.score = 0
        self.permalink = "/r/test/comments/reply-id"
        self.created_utc = 1.0
        self.author = "bot"
        self.parent_id = "parent-id"
        self.subreddit = subreddit


class FakeComment:
    def __init__(self, subreddit: FakeSubreddit) -> None:
        self.subreddit = subreddit
        self.author = "commenter"
        self.submission = type("FakeSubmissionRef", (), {"id": "submission-id"})()
        self.replies: list[str] = []

    def reply(self, body: str) -> FakeReply:
        self.replies.append(body)
        return FakeReply(subreddit=self.subreddit, body=body)


class FakeSubmission:
    def __init__(self, subreddit: FakeSubreddit) -> None:
        self.id = "post-id"
        self.title = "Title"
        self.author = "poster"
        self.subreddit = subreddit
        self.replies: list[str] = []

    def reply(self, body: str) -> FakeReply:
        self.replies.append(body)
        return FakeReply(subreddit=self.subreddit, body=body)


class FakeUser:
    def me(self) -> str:
        return "bot"


class FakeReddit:
    def __init__(self, subreddit_name: str) -> None:
        self.user = FakeUser()
        self.subreddit_obj = FakeSubreddit(subreddit_name)
        self.comment_obj = FakeComment(self.subreddit_obj)
        self.submission_obj = FakeSubmission(self.subreddit_obj)
        self.subreddit_calls: list[str] = []

    def comment(self, id: str) -> FakeComment:
        return self.comment_obj

    def submission(self, id: str) -> FakeSubmission:
        return self.submission_obj

    def subreddit(self, name: str) -> FakeSubreddit:
        self.subreddit_calls.append(name)
        return self.subreddit_obj


def reddit_tools(reddit: FakeReddit, allowed_subreddits: list[str] | None = None) -> RedditTools:
    tools = RedditTools(reddit_instance=reddit, allowed_subreddits=allowed_subreddits)
    tools.username = "bot"
    tools.password = "password"
    return tools


def test_allowed_subreddits_are_normalized() -> None:
    tools = reddit_tools(FakeReddit("Agno"), allowed_subreddits=["Agno"])

    assert tools.allowed_subreddits == ["agno"]


def test_allowed_subreddits_rejects_string_input() -> None:
    with pytest.raises(TypeError, match="allowed_subreddits must be a list"):
        RedditTools(reddit_instance=FakeReddit("Agno"), allowed_subreddits="agno")  # type: ignore[arg-type]


def test_reply_to_comment_blocks_disallowed_subreddit() -> None:
    reddit = FakeReddit("OtherSubreddit")
    tools = reddit_tools(reddit, allowed_subreddits=["Agno"])

    result = tools.reply_to_comment("comment-id", "hello")

    assert "not in the allowed_subreddits scope" in result
    assert reddit.comment_obj.replies == []


def test_reply_to_comment_allows_scoped_subreddit() -> None:
    reddit = FakeReddit("Agno")
    tools = reddit_tools(reddit, allowed_subreddits=["agno"])

    result = json.loads(tools.reply_to_comment("comment-id", "hello"))

    assert result["reply"]["body"] == "hello"
    assert reddit.comment_obj.replies == ["hello"]


def test_create_post_blocks_disallowed_subreddit_before_submit() -> None:
    reddit = FakeReddit("OtherSubreddit")
    tools = reddit_tools(reddit, allowed_subreddits=["Agno"])

    result = tools.create_post("OtherSubreddit", "Title", "Body")

    assert "not in the allowed_subreddits scope" in result
    assert reddit.subreddit_calls == []


def test_reply_to_post_blocks_disallowed_subreddit() -> None:
    reddit = FakeReddit("OtherSubreddit")
    tools = reddit_tools(reddit, allowed_subreddits=["Agno"])

    result = tools.reply_to_post("post-id", "hello")

    assert "not in the allowed_subreddits scope" in result
    assert reddit.submission_obj.replies == []
