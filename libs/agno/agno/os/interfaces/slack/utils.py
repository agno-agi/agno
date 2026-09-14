"""Building blocks for the Slack interface: Block Kit cards, HITL button ids and
payload parsing, stream state and event mapping, session status, per-thread state,
and small helpers shared by the event and HITL handlers."""

from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple, Union, cast, get_args

import httpx
from slack_sdk.errors import SlackApiError
from slack_sdk.models.blocks import (
    ActionsBlock,
    CheckboxesElement,
    ContextBlock,
    DividerBlock,
    InputBlock,
    PlainTextInputElement,
    StaticSelectElement,
)
from slack_sdk.models.blocks.basic_components import MarkdownTextObject, Option, PlainTextObject
from slack_sdk.models.blocks.block_elements import ButtonElement, ImageElement
from slack_sdk.web.async_client import AsyncWebClient
from typing_extensions import TypedDict

from agno.agent import RunEvent
from agno.media import Audio, File, Image, Video
from agno.run.agent import BaseAgentRunEvent
from agno.run.requirement import PauseType, RunRequirement
from agno.run.team import TeamRunEvent
from agno.run.workflow import WorkflowRunEvent
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.serialize import json_serializer

if TYPE_CHECKING:
    from slack_sdk.web.async_chat_stream import AsyncChatStream

    from agno.run.agent import RunPausedEvent as AgentRunPausedEvent
    from agno.run.base import BaseRunOutputEvent
    from agno.run.team import RunPausedEvent as TeamRunPausedEvent


# -----------------------------------------------------------------------------
# components: components
# -----------------------------------------------------------------------------


@dataclass
class Card:
    # Card block shipped in Slack API 2024 but slack_sdk lacks model class
    actions: List[ButtonElement]
    icon: Optional[ImageElement] = None
    title: Optional[PlainTextObject | MarkdownTextObject] = None
    subtitle: Optional[PlainTextObject | MarkdownTextObject] = None
    body: Optional[PlainTextObject | MarkdownTextObject] = None
    subtext: Optional[PlainTextObject | MarkdownTextObject] = None
    block_id: Optional[str] = None

    @property
    def type(self) -> str:
        return "card"

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": self.type,
            "actions": [a.to_dict() for a in self.actions],
        }
        if self.icon:
            result["icon"] = self.icon.to_dict()
        if self.title:
            result["title"] = self.title.to_dict()
        if self.subtitle:
            result["subtitle"] = self.subtitle.to_dict()
        if self.body:
            result["body"] = self.body.to_dict()
        if self.subtext:
            result["subtext"] = self.subtext.to_dict()
        if self.block_id:
            result["block_id"] = self.block_id
        return result


# -----------------------------------------------------------------------------
# types: types
# -----------------------------------------------------------------------------

# Type aliases for Slack payload structures
SlackState = Dict[str, Dict[str, Any]]  # view.state.values from form submissions
SlackBlocks = List[Dict[str, Any]]  # Message block array


def block_to_dict(block: Any) -> Dict[str, Any]:
    """Convert a Slack block (SDK model, dataclass, or dict) to a plain dict."""
    if hasattr(block, "to_dict"):
        return block.to_dict()
    if hasattr(block, "model_dump"):
        return block.model_dump(exclude_none=True, mode="json")
    if is_dataclass(block) and not isinstance(block, type):
        return asdict(block)
    return block if isinstance(block, dict) else {}


# --- Context dataclasses for interaction handlers ---


@dataclass
class RowActionContext:
    # Decoded from button value
    req_id: str
    run_id: str
    awaiting_ts: Optional[str]
    # Extracted from payload
    channel: str
    card_ts: str
    blocks: List[Dict[str, Any]]
    # Present only when sessions are keyed per participant (see ids.decode_session_id)
    session_id: Optional[str] = None


@dataclass
class SubmitContext:
    run_id: str
    channel: str
    msg_ts: str
    thread_ts: str
    awaiting_ts: Optional[str]
    user_id: str
    team_id: Optional[str]
    state_values: SlackState
    # Present only when sessions are keyed per participant (see ids.decode_session_id)
    session_id: Optional[str] = None


@dataclass
class RowTransformResult:
    blocks: List[Dict[str, Any]]
    should_auto_submit: bool


@dataclass
class ConfirmationRowSummary:
    pending_ids: set
    has_global_submit: bool


# --- Decision parsing dataclasses ---


@dataclass
class ParsedDecision:
    requirement_id: str
    pause_type: PauseType
    approved: Optional[bool] = None
    rejected_note: Optional[str] = None
    input_values: Optional[Dict[str, Any]] = None
    feedback_selections: Optional[Dict[str, List[str]]] = None
    external_result: Optional[str] = None


@dataclass
class ParseError:
    requirement_id: str
    field: str
    message: str


# Slack buttons have a 2000-char value limit; text fields have 3000-char limits
def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


# tool_execution may be None or lack tool_name if requirement is for user_input/feedback
def tool_name(requirement: "RunRequirement") -> str:
    tool = requirement.tool_execution
    return getattr(tool, "tool_name", None) or "tool"


def tool_args(requirement: "RunRequirement") -> Dict[str, Any]:
    tool = requirement.tool_execution
    # Empty dict fallback ensures JSON serialization never fails
    return getattr(tool, "tool_args", None) or {}


# --- Slack state value extractors ---


def extract_field_value(action_state: Dict[str, Any]) -> Optional[str]:
    # Slack nests static_select under selected_option; text inputs use value directly
    if action_state.get("type") == "static_select":
        return (action_state.get("selected_option") or {}).get("value")
    return action_state.get("value")


def extract_feedback_picks(action_state: Dict[str, Any]) -> List[str]:
    # Checkboxes return selected_options list; static_select returns single selected_option
    etype = action_state.get("type")
    if etype == "checkboxes":
        return [opt["value"] for opt in action_state.get("selected_options", []) if opt.get("value")]
    if etype == "static_select":
        selected = action_state.get("selected_option") or {}
        return [selected["value"]] if selected.get("value") else []
    return []


# -----------------------------------------------------------------------------
# ids: ids
# -----------------------------------------------------------------------------

# --- Block ID prefixes ---

ROW_BLOCK_PREFIX = "row"
PAUSE_BLOCK_PREFIX = "pause"

# --- Action IDs (Slack returns these on button clicks) ---

ACTION_SUBMIT = "submit_pause"
ACTION_ROW_APPROVE = "row_approve"
ACTION_ROW_REJECT = "row_reject"
ACTION_CHECK_STATUS = "check_status"
ACTION_REJECT_REASON = "reject_reason"
ACTION_FEEDBACK_SELECT = "feedback_select"
ACTION_EXTERNAL_RESULT = "external_result"
ACTION_INPUT_FIELD_PREFIX = "input_field:"


# --- Block ID builders/parsers ---
# Block IDs encode row:req_id:kind:status[:decided] — Slack returns block_id on interactions,
# so we embed all routing info to avoid server-side lookups


def row_block_id(requirement_id: str, kind: PauseType, *, decided: Optional[str] = None) -> str:
    base = f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:pending"
    if decided is None:
        return base
    return f"{ROW_BLOCK_PREFIX}:{requirement_id}:{kind}:decided:{decided}"


def parse_row_block_id(block_id: str) -> Optional[Dict[str, str]]:
    if not block_id.startswith(f"{ROW_BLOCK_PREFIX}:"):
        return None
    # Limit split to 4 so decided value (which may contain colons) stays intact
    parts = block_id.split(":", 4)
    if len(parts) < 4:
        return None
    out: Dict[str, str] = {
        "req_id": parts[1],
        "kind": parts[2],
        "status": parts[3],
    }
    if len(parts) == 5 and parts[3] == "decided":
        out["decided"] = parts[4]
    return out


def pause_block_id(run_id: str) -> str:
    return f"{PAUSE_BLOCK_PREFIX}:{run_id}"


def reject_reason_block_id(requirement_id: str) -> str:
    return f"reject_reason:{requirement_id}"


# --- Field-level block/action ID builders ---


def user_input_block_id(requirement_id: str, field_name: str) -> str:
    return f"{row_block_id(requirement_id, 'user_input')}:{field_name}"


def user_input_action_id(field_name: str) -> str:
    return f"{ACTION_INPUT_FIELD_PREFIX}{field_name}"


def user_feedback_block_id(requirement_id: str, question_index: int) -> str:
    return f"{row_block_id(requirement_id, 'user_feedback')}:q{question_index}"


def feedback_action_id(question_index: int) -> str:
    return f"{ACTION_FEEDBACK_SELECT}:{question_index}"


def external_result_block_id(requirement_id: str) -> str:
    return f"{row_block_id(requirement_id, 'external_execution')}:result"


# --- Button value encoders/decoders ---
# Pipe-delimited because Slack button values are opaque strings, not JSON — simpler to parse.
# Every value may carry one optional trailing field: the session id, needed when sessions are
# keyed per participant and cannot be derived from the thread. It is only written when set,
# so default-config cards are byte-identical to older builds.


def _split(value: str) -> List[str]:
    return value.split("|") if value else []


def _extra(session_id: Optional[str]) -> str:
    return f"|{session_id}" if session_id else ""


def decode_session_id(value: str, base_fields: int) -> Optional[str]:
    parts = _split(value)
    return parts[base_fields] if len(parts) > base_fields and parts[base_fields] else None


def encode_row_button_value(
    req_id: str, run_id: str, awaiting_ts: Optional[str], session_id: Optional[str] = None
) -> str:
    return f"{req_id}|{run_id}|{awaiting_ts or ''}" + _extra(session_id)


def decode_row_button_value(value: str) -> Tuple[str, str, Optional[str]]:
    parts = _split(value)
    if len(parts) < 2:
        return "", "", None
    awaiting_ts = parts[2] if len(parts) > 2 and parts[2] else None
    return parts[0], parts[1], awaiting_ts


def encode_submit_button_value(run_id: str, awaiting_ts: Optional[str], session_id: Optional[str] = None) -> str:
    return f"{run_id}|{awaiting_ts or ''}" + _extra(session_id)


def decode_submit_button_value(value: str) -> Tuple[str, Optional[str]]:
    parts = _split(value)
    if not parts:
        return "", None
    awaiting_ts = parts[1] if len(parts) > 1 and parts[1] else None
    return parts[0], awaiting_ts


# --- Admin approval button value (4 fields: approval_id, req_id, run_id, awaiting_ts) ---


def encode_admin_approval_button_value(
    approval_id: str, req_id: str, run_id: str, awaiting_ts: Optional[str], session_id: Optional[str] = None
) -> str:
    return f"{approval_id}|{req_id}|{run_id}|{awaiting_ts or ''}" + _extra(session_id)


def decode_admin_approval_button_value(value: str) -> Tuple[str, str, str, Optional[str]]:
    parts = _split(value)
    if len(parts) < 3:
        return "", "", "", None
    approval_id, req_id, run_id = parts[0], parts[1], parts[2]
    awaiting_ts = parts[3] if len(parts) > 3 and parts[3] else None
    return approval_id, req_id, run_id, awaiting_ts


ROW_BUTTON_FIELDS = 3
SUBMIT_BUTTON_FIELDS = 2
ADMIN_BUTTON_FIELDS = 4


# -----------------------------------------------------------------------------
# helpers: helpers
# -----------------------------------------------------------------------------


async def call_db(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    # Database adapters come in sync and async flavours with the same method names;
    # a sync call is moved off the event loop so a slow query cannot stall Slack acks.
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


def slack_error_code(exc: BaseException) -> Optional[str]:
    # Extracts Slack API error code from exception for logging/handling
    resp = getattr(exc, "response", None)
    data = getattr(resp, "data", None) if resp else None
    if isinstance(data, dict):
        code = data.get("error")
        if isinstance(code, str):
            return code
    return None


async def resolve_session_id(
    entity: Any, entity_id: str, channel_id: str, thread_ts: str, user_key: Optional[str] = None
) -> str:
    # Per-participant sessions: each speaker in a thread keeps their own history strand.
    # Slack ts values are only unique per channel, so the channel stays in the key.
    if user_key:
        return f"{entity_id}:{channel_id}:{user_key}:{thread_ts}"
    # Sessions created before channel-scoped keys used "{entity_id}:{thread_ts}".
    # Probe for existing legacy session so an upgrade doesn't orphan history.
    legacy_id = f"{entity_id}:{thread_ts}"
    try:
        session = await entity.aget_session(session_id=legacy_id)
        if session is not None:
            return legacy_id
    except Exception:
        pass
    # New format includes channel_id to prevent cross-channel collisions
    return f"{entity_id}:{channel_id}:{thread_ts}"


def task_id(agent_name: Optional[str], base_id: str) -> str:
    # Prefix card IDs per agent so concurrent tool calls from different
    # team members don't collide in the Slack stream
    if agent_name:
        safe = agent_name.lower().replace(" ", "_")[:20]
        return f"{safe}_{base_id}"
    return base_id


def member_name(chunk: Any, entity_name: str) -> Optional[str]:
    # Return name only for team members (not leader) to prefix task card
    # labels like "Researcher: web_search" for disambiguation
    name = getattr(chunk, "agent_name", None)
    if name and isinstance(name, str) and name != entity_name:
        return name
    return None


def should_respond(event: dict, reply_to_mentions_only: bool) -> bool:
    event_type = event.get("type")
    if event_type not in ("app_mention", "message"):
        return False
    channel_type = event.get("channel_type", "")
    is_dm = channel_type == "im"
    if reply_to_mentions_only and event_type == "message" and not is_dm:
        return False
    # When responding to all messages, skip app_mention to avoid duplicates.
    # Slack fires both app_mention and message for the same @mention — the
    # message event already covers it.
    if not reply_to_mentions_only and event_type == "app_mention" and not is_dm:
        return False
    return True


def build_run_metadata(
    display_name: Optional[str],
    resolved_user_id: str,
    ctx: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    metadata: Dict[str, Any] = {}
    if display_name:
        metadata["user_name"] = display_name
        metadata["user_id"] = resolved_user_id
    if ctx.get("action_token"):
        metadata["action_token"] = ctx["action_token"]
    return metadata or None


def extract_event_context(event: dict) -> Dict[str, Any]:
    return {
        "message_text": event.get("text", ""),
        "channel_id": event.get("channel", ""),
        # Human sender ID (U.../W...) — empty for webhook/legacy bot messages
        "user": event.get("user") or "",
        # Bot sender ID (B...) — present on all bot-authored messages
        "bot_id": event.get("bot_id") or "",
        # Prefer existing thread; fall back to message ts for new conversations
        "thread_id": event.get("thread_ts") or event.get("ts", ""),
        # User-scoped token for assistant.search.context workspace search
        "action_token": event.get("assistant_thread", {}).get("action_token"),
    }


def strip_bot_mention(text: str, bot_user_id: Optional[str], bot_name: Optional[str] = None) -> str:
    """Replace the bot's own @mention with its display name (or remove if no name).

    Slack encodes mentions as ``<@U123>``. When a user @-mentions the bot,
    the agent shouldn't see its own ID in the text — it just adds noise and
    causes the model to echo back the raw mention tag.

    If bot_name is provided, the mention is replaced with that name so the
    agent sees "hi Scout" instead of "hi " when the user types "hi @Scout".

    Only processes the *bot's* mention; other users' mentions are preserved.
    """
    if not bot_user_id or not text:
        return text
    import re

    replacement = f" {bot_name} " if bot_name else " "
    return re.sub(rf"\s*<@{re.escape(bot_user_id)}>\s*", replacement, text).strip()


async def resolve_slack_user(async_client: Any, slack_user_id: str) -> Tuple[str, Optional[str]]:
    """Resolve a Slack user ID to (canonical_user_id, display_name).

    Returns the user's email as canonical_user_id if available, otherwise
    falls back to the raw Slack user ID. Display name is best-effort.
    """
    try:
        resp = await async_client.users_info(user=slack_user_id)
        user = resp.get("user", {}) if resp else {}
        profile = user.get("profile", {})

        email = profile.get("email")
        resolved_id = email if email else slack_user_id

        display_name = profile.get("display_name") or profile.get("real_name") or user.get("name") or None
        if display_name is not None and not display_name.strip():
            display_name = None

        return (resolved_id, display_name)
    except Exception as e:
        log_warning(f"Failed to resolve Slack user {slack_user_id}: {str(e)}")
        return (slack_user_id, None)


async def resolve_slack_bot(async_client: Any, bot_id: str) -> Tuple[str, Optional[str]]:
    try:
        resp = await async_client.bots_info(bot=bot_id)
        bot = resp.get("bot", {}) if resp else {}
        return (bot_id, bot.get("name") or None)
    except Exception as e:
        log_warning(f"Failed to resolve Slack bot {bot_id}: {str(e)}")
        return (bot_id, None)


class BotNameResolver:
    """Resolves a Slack bot user ID to its display name with per-instance caching.

    Instantiated once per mounted Slack interface so
    each interface keeps its own cache without polluting module-level state.
    Only successful lookups are cached — transient API failures are retried on
    the next message.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, str] = {}

    async def resolve(self, async_client: Any, bot_user_id: str) -> Optional[str]:
        if bot_user_id in self._cache:
            return self._cache[bot_user_id]

        try:
            resp = await async_client.users_info(user=bot_user_id)
            user = resp.get("user", {}) if resp else {}
            profile = user.get("profile", {})

            name = profile.get("display_name") or profile.get("real_name") or user.get("name") or None
            if name is not None and not name.strip():
                name = None

            if name is not None:
                self._cache[bot_user_id] = name
            return name
        except Exception as e:
            log_warning(f"Failed to resolve bot name for {bot_user_id}: {str(e)}")
            return None


async def resolve_channel_name(async_client: Any, channel_id: str) -> Optional[str]:
    """Resolve a Slack channel ID to its human-readable name."""
    try:
        resp = await async_client.conversations_info(channel=channel_id)
        channel = resp.get("channel", {}) if resp else {}
        # API returns "" for unnamed channels; normalize to None
        return channel.get("name") or None
    except Exception as e:
        log_warning(f"Failed to resolve channel name for {channel_id}: {str(e)}")
        return None


async def download_event_files_async(
    token: str, event: dict, max_file_size: int
) -> Tuple[List[File], List[Image], List[Video], List[Audio], List[str]]:
    files: List[File] = []
    images: List[Image] = []
    videos: List[Video] = []
    audio: List[Audio] = []
    skipped: List[str] = []

    if not event.get("files"):
        return files, images, videos, audio, skipped

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        for file_info in event["files"]:
            file_id = file_info.get("id")
            filename = file_info.get("name", "file")
            mimetype = file_info.get("mimetype", "application/octet-stream")
            file_size = file_info.get("size", 0)

            if file_size > max_file_size:
                limit_mb = max_file_size / (1024 * 1024)
                actual_mb = file_size / (1024 * 1024)
                skipped.append(f"{filename} ({actual_mb:.1f}MB — exceeds {limit_mb:.0f}MB limit)")
                continue

            url_private = file_info.get("url_private")
            if not url_private:
                continue

            try:
                resp = await client.get(url_private, headers=headers, timeout=30)
                resp.raise_for_status()
                file_content = resp.content

                if mimetype.startswith("image/"):
                    fmt = mimetype.split("/")[-1]
                    images.append(Image(content=file_content, id=file_id, mime_type=mimetype, format=fmt))
                elif mimetype.startswith("video/"):
                    videos.append(Video(content=file_content, mime_type=mimetype))
                elif mimetype.startswith("audio/"):
                    audio.append(Audio(content=file_content, mime_type=mimetype))
                else:
                    # Pass None for unsupported types to avoid File validation errors
                    safe_mime = mimetype if mimetype in File.valid_mime_types() else None
                    files.append(File(content=file_content, filename=filename, mime_type=safe_mime))
            except Exception as e:
                log_error(f"Failed to download file {file_id}: {str(e)}")

    return files, images, videos, audio, skipped


async def upload_response_media_async(async_client: Any, response: Any, channel_id: str, thread_ts: str) -> None:
    media_attrs = [
        ("images", "image.png"),
        ("files", "file"),
        ("videos", "video.mp4"),
        ("audio", "audio.mp3"),
    ]
    for attr, default_name in media_attrs:
        items = getattr(response, attr, None)
        if not items:
            continue
        for item in items:
            content_bytes = item.get_content_bytes()
            if content_bytes:
                try:
                    await async_client.files_upload_v2(
                        channel=channel_id,
                        content=content_bytes,
                        filename=getattr(item, "filename", None) or default_name,
                        thread_ts=thread_ts,
                    )
                except Exception as e:
                    log_error(f"Failed to upload {attr.rstrip('s')}: {str(e)}")


async def open_chat_stream(
    client: Any,
    channel: str,
    thread_ts: str,
    recipient_user_id: str,
    recipient_team_id: Optional[str],
    task_display_mode: str,
    buffer_size: int,
) -> Any:
    return await client.chat_stream(
        channel=channel,
        thread_ts=thread_ts,
        recipient_team_id=recipient_team_id,
        recipient_user_id=recipient_user_id,
        task_display_mode=task_display_mode,
        buffer_size=buffer_size,
    )


def slack_delivery_kwargs(unfurl_links: bool, unfurl_media: bool, mrkdwn: bool) -> Dict[str, Any]:
    # mrkdwn=False means plaintext delivery: parse="none" stops Slack from
    # linkifying bare URLs and link_names=False stops bare @name expansion. Note
    # this does NOT neutralize control sequences already encoded as `<!channel>`
    # / `<@U123>` — only parse="full" escapes those. Card bodies inert those
    # characters directly (see builders.inert_code_span_text); the plain message
    # path relies on the model not emitting pre-encoded sequences.
    kwargs: Dict[str, Any] = {"unfurl_links": unfurl_links, "unfurl_media": unfurl_media, "mrkdwn": mrkdwn}
    if not mrkdwn:
        kwargs["parse"] = "none"
        kwargs["link_names"] = False
    return kwargs


async def send_slack_message_async(
    async_client: Any,
    channel: str,
    thread_ts: str,
    message: str,
    italics: bool = False,
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    mrkdwn: bool = True,
) -> None:
    if not message or not message.strip():
        return

    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    delivery = slack_delivery_kwargs(unfurl_links, unfurl_media, mrkdwn)

    # Under Slack's 40K char limit with margin for batch prefix overhead
    max_len = 39900
    if len(message) <= max_len:
        await async_client.chat_postMessage(channel=channel, text=_format(message), thread_ts=thread_ts, **delivery)
        return

    message_batches = [message[i : i + max_len] for i in range(0, len(message), max_len)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        await async_client.chat_postMessage(
            channel=channel, text=_format(batch_message), thread_ts=thread_ts, **delivery
        )


# -----------------------------------------------------------------------------
# state: state
# -----------------------------------------------------------------------------

# Literal not Enum — values flow directly into Slack API dicts as plain strings.
# "pending" added for HITL pauses — Slack's AI Stream UI treats in_progress cards
# that outlive the stream idle window as errors, whereas pending cards are valid waits.
TaskStatus = Literal["pending", "in_progress", "complete", "error"]


class TaskUpdateDict(TypedDict):
    type: str
    id: str
    title: str
    status: TaskStatus


@dataclass
class TaskCard:
    title: str
    status: TaskStatus = "in_progress"


@dataclass
class StreamState:
    # Slack thread title — set once on first content to avoid repeated API calls
    title_set: bool = False
    # Error events may lack tool_call_id; this generates fallback IDs (tool_error_0, tool_error_1, ...)
    error_count: int = 0

    text_buffer: str = ""

    # Counter for unique reasoning task card keys (reasoning_0, reasoning_1, ...)
    reasoning_round: int = 0

    task_cards: Dict[str, TaskCard] = field(default_factory=dict)

    images: List["Image"] = field(default_factory=list)
    videos: List["Video"] = field(default_factory=list)
    audio: List["Audio"] = field(default_factory=list)
    files: List["File"] = field(default_factory=list)

    # Used by process_event to suppress nested agent events in workflow mode
    entity_type: Literal["agent", "team", "workflow"] = "agent"
    # Leader/workflow name; member_name() compares against it to detect team members
    entity_name: str = ""

    # Last StepOutput content; WorkflowCompleted uses as fallback when content is None
    workflow_final_content: str = ""

    # Set by handlers on terminal events; router reads this for the final flush
    terminal_status: Optional[TaskStatus] = None

    # Total chars sent to the current Slack stream; reset on rotation
    stream_chars_sent: int = 0

    # Stashed by _on_run_paused; router posts Block Kit approval card after stream.stop()
    paused_event: Optional[Union["AgentRunPausedEvent", "TeamRunPausedEvent"]] = None

    # Run id from the first event that carries one; the stop button cancels through it
    run_id: Optional[str] = None
    # Set when the run ended because the user pressed stop (or cancel_run was called)
    cancelled: bool = False

    def track_task(self, key: str, title: str, status: TaskStatus = "in_progress") -> None:
        self.task_cards[key] = TaskCard(title=title, status=status)

    def complete_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "complete"

    def error_task(self, key: str) -> None:
        card = self.task_cards.get(key)
        if card:
            card.status = "error"

    def resolve_all_pending(self, status: TaskStatus = "complete") -> List[TaskUpdateDict]:
        # Called at stream end to close any cards left in_progress (e.g. if the
        # model finished without emitting a ToolCallCompleted for every start).
        chunks: List[TaskUpdateDict] = []
        for key, card in self.task_cards.items():
            if card.status == "in_progress":
                card.status = status  # type: ignore[assignment]
                chunks.append(TaskUpdateDict(type="task_update", id=key, title=card.title, status=status))
        return chunks

    def append_content(self, text: str) -> None:
        self.text_buffer += str(text)

    def append_error(self, error_msg: str) -> None:
        self.text_buffer += f"\n_Error: {error_msg}_"

    def has_content(self) -> bool:
        return bool(self.text_buffer)

    def flush(self) -> str:
        result = self.text_buffer
        self.text_buffer = ""
        return result

    def collect_media(self, chunk: BaseRunOutputEvent) -> None:
        # Media can't be streamed inline — Slack requires a separate upload after
        # the stream ends. We collect here and upload_response_media() sends them.
        for img in getattr(chunk, "images", None) or []:
            if img not in self.images:
                self.images.append(img)
        for vid in getattr(chunk, "videos", None) or []:
            if vid not in self.videos:
                self.videos.append(vid)
        for aud in getattr(chunk, "audio", None) or []:
            if aud not in self.audio:
                self.audio.append(aud)
        for f in getattr(chunk, "files", None) or []:
            if f not in self.files:
                self.files.append(f)


# -----------------------------------------------------------------------------
# interactions: interactions
# -----------------------------------------------------------------------------

# --- Slack state helpers ---


def _get_action_state(state: SlackState, block_id: str, action_id: str) -> Dict[str, Any]:
    return state.get(block_id, {}).get(action_id, {})


# --- Pause type parsers ---
# Each parser extracts user decisions from Slack payload for one pause_type.
# Returns ParsedDecision with the resolved values; appends ParseError for validation failures.


# Parses Approve/Deny toggle state from block_id + optional rejection reason from InputBlock
def _parse_confirmation(
    requirement: RunRequirement,
    blocks: SlackBlocks,
    errors: List[ParseError],
    state: Optional[SlackState] = None,
) -> ParsedDecision:
    req_id = requirement.id or ""
    state = state or {}
    decision = None

    for block in blocks:
        parsed = parse_row_block_id(block.get("block_id", ""))
        if parsed and parsed.get("req_id") == req_id and parsed.get("kind") == "confirmation":
            if parsed.get("status") == "decided":
                decision = parsed.get("decided")
                break

    if decision is None:
        name = tool_name(requirement)
        errors.append(ParseError(requirement_id=req_id, field=name, message="Approval decision required"))
        return ParsedDecision(requirement_id=req_id, pause_type="confirmation", approved=None)

    rejected_note = None
    if decision == "deny":
        reason_state = _get_action_state(state, reject_reason_block_id(req_id), ACTION_REJECT_REASON)
        reason_text = (reason_state.get("value") or "").strip()
        if reason_text:
            rejected_note = reason_text

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="confirmation",
        approved=(decision == "approve"),
        rejected_note=rejected_note,
    )


# Parses text/dropdown fields from user_input_schema
def _parse_user_input(requirement: RunRequirement, state: SlackState, errors: List[ParseError]) -> ParsedDecision:
    req_id = requirement.id or ""
    values: Dict[str, Any] = {}

    for schema_field in requirement.user_input_schema or []:
        action_state = _get_action_state(
            state, user_input_block_id(req_id, schema_field.name), user_input_action_id(schema_field.name)
        )
        values[schema_field.name] = extract_field_value(action_state)
        if values[schema_field.name] is None:
            errors.append(ParseError(requirement_id=req_id, field=schema_field.name, message="This field is required"))

    return ParsedDecision(requirement_id=req_id, pause_type="user_input", input_values=values)


# Parses checkbox/dropdown selections from user_feedback_schema questions
def _parse_user_feedback(requirement: RunRequirement, state: SlackState, errors: List[ParseError]) -> ParsedDecision:
    req_id = requirement.id or ""
    selections: Dict[str, List[str]] = {}

    for i, question in enumerate(requirement.user_feedback_schema or []):
        action_state = _get_action_state(state, user_feedback_block_id(req_id, i), feedback_action_id(i))
        picked = extract_feedback_picks(action_state)
        if not picked:
            errors.append(ParseError(requirement_id=req_id, field=question.question, message="No option selected"))
        selections[question.question] = picked

    return ParsedDecision(requirement_id=req_id, pause_type="user_feedback", feedback_selections=selections)


# Parses pasted execution result from external_execution text field
def _parse_external(
    requirement: RunRequirement,
    state: SlackState,
    errors: List[ParseError],
) -> ParsedDecision:
    req_id = requirement.id or ""
    action_state = _get_action_state(state, external_result_block_id(req_id), ACTION_EXTERNAL_RESULT)
    result = (action_state.get("value") or "").strip()

    if not result:
        errors.append(ParseError(requirement_id=req_id, field="result", message="Result must be non-empty"))

    return ParsedDecision(
        requirement_id=req_id,
        pause_type="external_execution",
        external_result=result or None,
    )


# --- Context extraction helpers ---


def extract_row_action_context(payload: Dict[str, Any]) -> Optional[RowActionContext]:
    actions = payload.get("actions") or []
    if not actions:
        return None
    button_value = actions[0].get("value") or ""
    if "|" not in button_value:
        return None
    req_id, run_id, awaiting_ts = decode_row_button_value(button_value)

    channel = (payload.get("channel") or {}).get("id")
    message = payload.get("message") or {}
    card_ts = message.get("ts")
    if not channel or not card_ts:
        return None

    return RowActionContext(
        req_id=req_id,
        run_id=run_id,
        awaiting_ts=awaiting_ts,
        channel=channel,
        card_ts=card_ts,
        blocks=list(message.get("blocks") or []),
        session_id=decode_session_id(button_value, ROW_BUTTON_FIELDS),
    )


def extract_submit_context(payload: Dict[str, Any]) -> Optional[SubmitContext]:
    actions = payload.get("actions") or []
    if not actions:
        return None
    submit_block_id = actions[0].get("block_id") or ""
    if not submit_block_id.startswith("pause:"):
        return None
    run_id = submit_block_id.removeprefix("pause:")

    channel = (payload.get("channel") or {}).get("id")
    message = payload.get("message") or {}
    msg_ts = message.get("ts")
    if not (run_id and channel and msg_ts):
        return None

    thread_ts = message.get("thread_ts") or msg_ts
    button_value = actions[0].get("value") or ""
    _, awaiting_ts = decode_submit_button_value(button_value)

    return SubmitContext(
        run_id=run_id,
        channel=channel,
        msg_ts=msg_ts,
        thread_ts=thread_ts,
        awaiting_ts=awaiting_ts,
        user_id=(payload.get("user") or {}).get("id", ""),
        team_id=(payload.get("team") or {}).get("id"),
        state_values=(payload.get("state") or {}).get("values") or {},
        session_id=decode_session_id(button_value, SUBMIT_BUTTON_FIELDS),
    )


def confirmation_row_summary(blocks: List[Dict[str, Any]]) -> ConfirmationRowSummary:
    pending_ids: set[str] = set()
    has_global_submit = False
    for block in blocks:
        block_id = block.get("block_id", "")
        block_type = block.get("type", "")
        # Global submit button lives in an actions block with pause: prefix
        if block_type == "actions" and block_id.startswith("pause:"):
            has_global_submit = True
        # Count only Slack-resolvable confirmation rows; admin_approval cards must not block auto-submit
        if block_id.startswith("rowact:") and ":confirmation" in block_id:
            if ":selected:" not in block_id and ":decided:" not in block_id:
                parts = block_id.split(":")
                if len(parts) >= 2:
                    pending_ids.add(parts[1])
        # Decision marker removes from pending
        if block_id.startswith("row:") and ":confirmation:decided:" in block_id:
            parts = block_id.split(":")
            if len(parts) >= 2:
                pending_ids.discard(parts[1])
    return ConfirmationRowSummary(pending_ids=pending_ids, has_global_submit=has_global_submit)


def synthetic_submit_payload(
    payload: Dict[str, Any],
    run_id: str,
    awaiting_ts: Optional[str],
    blocks: List[Dict[str, Any]],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    synthetic = dict(payload)
    synthetic["actions"] = [
        {
            "action_id": "submit_pause",
            "block_id": f"pause:{run_id}",
            "value": encode_submit_button_value(run_id, awaiting_ts, session_id),
        }
    ]
    synthetic["message"] = {**(payload.get("message") or {}), "blocks": blocks}
    return synthetic


# --- Public API ---


# Entry point: routes each requirement to its pause_type parser
def parse_submit_payload(
    payload: Dict[str, Any],
    requirements: List[RunRequirement],
) -> tuple[List[ParsedDecision], List[ParseError]]:
    blocks: SlackBlocks = (payload.get("message") or {}).get("blocks") or []
    state: SlackState = (payload.get("state") or {}).get("values") or {}

    decisions: List[ParsedDecision] = []
    errors: List[ParseError] = []

    for requirement in requirements:
        kind = requirement.pause_type
        if kind == "confirmation":
            # approval_type="required" tools are resolved via os.agno.com, not Slack
            tool_exec = requirement.tool_execution
            if tool_exec and getattr(tool_exec, "approval_type", None) == "required":
                continue
            decisions.append(_parse_confirmation(requirement, blocks, errors, state))
        elif kind == "user_input":
            decisions.append(_parse_user_input(requirement, state, errors))
        elif kind == "user_feedback":
            decisions.append(_parse_user_feedback(requirement, state, errors))
        elif kind == "external_execution":
            decisions.append(_parse_external(requirement, state, errors))

    return decisions, errors


# Mutates RunRequirement objects — agent holds refs to these and polls for resolution
def apply_decisions(decisions: List[ParsedDecision], requirements: List[RunRequirement]) -> None:
    by_id = {r.id: r for r in requirements if r.id}

    for d in decisions:
        req = by_id.get(d.requirement_id)
        if req is None:
            continue

        if d.pause_type == "confirmation" and d.approved is True:
            req.confirm()
        elif d.pause_type == "confirmation" and d.approved is False:
            req.reject(d.rejected_note)
        elif d.pause_type == "user_input" and d.input_values is not None:
            req.provide_user_input(d.input_values)
        elif d.pause_type == "user_feedback" and d.feedback_selections is not None:
            req.provide_user_feedback(d.feedback_selections)
        elif d.pause_type == "external_execution" and d.external_result is not None:
            req.set_external_execution_result(d.external_result)


# -----------------------------------------------------------------------------
# builders: builders
# -----------------------------------------------------------------------------

# Slack caps messages at 50 blocks
MAX_MESSAGE_BLOCKS = 50


# Untrusted values are embedded in Slack inline code spans: a backtick closes the span,
# a newline exits it (inline code does not span lines), and <...> becomes a Slack control
# sequence once outside the span. Swap each for an inert lookalike / visible escape.
_CODE_SPAN_INERT = str.maketrans(
    {
        "`": "ˋ",  # modifier letter grave accent
        "<": "‹",  # single left-pointing angle quotation mark
        ">": "›",  # single right-pointing angle quotation mark
        "\r": "\\r",
        "\n": "\\n",
    }
)


def inert_code_span_text(text: str) -> str:
    return text.translate(_CODE_SPAN_INERT)


# Formats tool arg values for display in HITL approval cards; strings pass through, others
# JSON-encode. Output is always inerted so it cannot break out of the surrounding code span.
def render_arg_value(value: Any) -> str:
    if isinstance(value, str):
        rendered = value
    else:
        try:
            rendered = json.dumps(value, default=json_serializer)
        except (TypeError, ValueError):
            rendered = str(value)
    return inert_code_span_text(rendered)


# --- Type detection helpers ---


def _is_literal(field_type: Any) -> bool:
    return str(field_type).startswith("typing.Literal")


def _is_enum(field_type: Any) -> bool:
    return isinstance(field_type, type) and issubclass(field_type, Enum)


def _is_bool(field_type: Any) -> bool:
    return field_type is bool or (isinstance(field_type, type) and field_type.__name__ == "bool")


# --- Element builders ---


def _build_select_element(name: str, options: List[Tuple[str, str]]) -> StaticSelectElement:
    return StaticSelectElement(
        action_id=user_input_action_id(name),
        placeholder=PlainTextObject(text="Select"),
        options=[Option(text=PlainTextObject(text=text), value=value) for text, value in options],
    )


def _build_text_input(name: str, field_type: Any, initial_raw: Any) -> PlainTextInputElement:
    type_name = field_type.__name__ if isinstance(field_type, type) else str(field_type)
    multiline = type_name in ("list", "dict")
    initial_value: Optional[str] = None
    if initial_raw is not None:
        initial_value = initial_raw if isinstance(initial_raw, str) else json.dumps(initial_raw, default=str)
    return PlainTextInputElement(
        action_id=user_input_action_id(name),
        placeholder=PlainTextObject(text=f"Enter {name}"),
        initial_value=initial_value,
        multiline=multiline or None,
    )


# Maps Python type → Slack input element: dropdown for finite choices (Literal/Enum/bool), text box otherwise
def _field_type_to_input_element(name: str, field_type: Any, initial_raw: Any) -> Any:
    # Literal["a", "b"] → dropdown
    if _is_literal(field_type):
        args = get_args(field_type)
        return _build_select_element(name, [(str(a), str(a)) for a in args])

    # Enum → dropdown
    if _is_enum(field_type):
        return _build_select_element(name, [(m.name, m.name) for m in field_type])

    # bool → dropdown (True/False)
    if _is_bool(field_type):
        return _build_select_element(name, [("True", "true"), ("False", "false")])

    # Everything else → text input
    return _build_text_input(name, field_type, initial_raw)


# --- Main builder ---


# Converts a Pydantic field schema into a Slack Block Kit input element for HITL user_input cards
def _build_input_field(req_id: str, ui_field: Any) -> InputBlock:
    name = getattr(ui_field, "name", "field")
    description = getattr(ui_field, "description", None)
    field_type = getattr(ui_field, "field_type", str)
    initial_raw = getattr(ui_field, "value", None)

    element = _field_type_to_input_element(name, field_type, initial_raw)

    return InputBlock(
        block_id=user_input_block_id(req_id, name),
        label=PlainTextObject(text=name),
        element=element,
        hint=PlainTextObject(text=description) if description else None,
    )


def _user_feedback_option_to_slack_option(option: Any, index: int) -> Option:
    label = getattr(option, "label", f"option-{index}")
    description = getattr(option, "description", None)
    return Option(
        text=PlainTextObject(text=label),
        value=label,
        description=PlainTextObject(text=description) if description else None,
    )


# Checkboxes if multi_select, dropdown otherwise
def _feedback_question_to_input_element(slack_options: List[Option], multi_select: bool, q_index: int) -> Any:
    if multi_select:
        return CheckboxesElement(
            action_id=feedback_action_id(q_index),
            options=slack_options,
        )
    return StaticSelectElement(
        action_id=feedback_action_id(q_index),
        placeholder=PlainTextObject(text="Select one"),
        options=slack_options,
    )


# Builds Slack InputBlock for a HITL user_feedback question
def _build_user_feedback_question_block(req_id: str, question: Any, q_index: int) -> InputBlock:
    prompt = getattr(question, "question", f"Question {q_index + 1}")
    options = getattr(question, "options", None) or []
    multi_select = bool(getattr(question, "multi_select", False))

    slack_options = [_user_feedback_option_to_slack_option(opt, i) for i, opt in enumerate(options)]
    element = _feedback_question_to_input_element(slack_options, multi_select, q_index)

    return InputBlock(
        block_id=user_feedback_block_id(req_id, q_index),
        label=PlainTextObject(text=prompt),
        element=element,
    )


# Builds HITL confirmation card with Approve/Deny buttons for a tool execution
def _build_confirmation_card(
    requirement: RunRequirement,
    run_id: str = "",
    awaiting_ts: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Card:
    req_id = requirement.id or ""
    name = tool_name(requirement)
    args = tool_args(requirement)

    # Format args as bullet points in body (not subtitle which truncates). Arg keys are
    # model-derived and sit outside the code span, so inert them too.
    body_lines = [f"• {inert_code_span_text(str(k))}: `{render_arg_value(v)}`" for k, v in (args or {}).items()]
    body_text = "\n".join(body_lines) if body_lines else "_(no arguments)_"
    # Slack Block Kit section text has ~200 char limit; truncate to prevent silent card rejection
    body_text = truncate(body_text, 200)

    # approval_type="required" tools need admin approval via dashboard, not Slack buttons
    tool_exec = requirement.tool_execution
    if tool_exec and getattr(tool_exec, "approval_type", None) == "required":
        approval_id = getattr(tool_exec, "approval_id", None) or ""
        button_value = encode_admin_approval_button_value(approval_id, req_id, run_id, awaiting_ts, session_id)
        return Card(
            block_id=f"rowact:{req_id}:admin_approval",
            title=MarkdownTextObject(text=f"*{name}*"),
            body=MarkdownTextObject(text=body_text),
            subtext=MarkdownTextObject(text="Awaiting admin approval"),
            actions=[
                ButtonElement(
                    action_id=ACTION_CHECK_STATUS,
                    text=PlainTextObject(text="Check Status", emoji=True),
                    value=button_value,
                ),
            ],
        )

    button_value = encode_row_button_value(req_id, run_id, awaiting_ts, session_id)
    return Card(
        block_id=f"rowact:{req_id}:confirmation",
        title=MarkdownTextObject(text=f"*{name}*"),
        body=MarkdownTextObject(text=body_text),
        actions=[
            ButtonElement(
                action_id=ACTION_ROW_APPROVE,
                text=PlainTextObject(text="Approve", emoji=True),
                style="primary",
                value=button_value,
            ),
            ButtonElement(
                action_id=ACTION_ROW_REJECT,
                text=PlainTextObject(text="Deny", emoji=True),
                style="danger",
                value=button_value,
            ),
        ],
    )


def build_admin_approval_status_card(
    tool_name: str,
    body_text: str,
    status: str,
    req_id: str,
    approval_id: str,
    run_id: str,
    awaiting_ts: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Card:
    """Build card showing admin approval status after check."""
    button_value = encode_admin_approval_button_value(approval_id, req_id, run_id, awaiting_ts, session_id)

    # "approved" case handled by auto-continue in handle_check_status
    if status == "rejected":
        subtext = "Rejected by admin"
        actions: List[ButtonElement] = []
    else:
        # Still pending
        subtext = "Still pending approval"
        actions = [
            ButtonElement(
                action_id=ACTION_CHECK_STATUS,
                text=PlainTextObject(text="Check Again", emoji=True),
                value=button_value,
            ),
        ]

    return Card(
        block_id=f"rowact:{req_id}:admin_approval",
        title=MarkdownTextObject(text=f"*{tool_name}*"),
        body=MarkdownTextObject(text=body_text),
        subtext=MarkdownTextObject(text=subtext),
        actions=actions,
    )


# Confirmation card with toggle state — selected button gets styled + past tense label
def build_confirmation_toggle_card(
    req_id: str,
    run_id: str,
    awaiting_ts: Optional[str],
    tool_name: str,
    body_text: str,
    selected: str,
    session_id: Optional[str] = None,
) -> Card:
    button_value = encode_row_button_value(req_id, run_id, awaiting_ts, session_id)
    is_approved = selected == "approve"
    # Slack Block Kit section text has ~200 char limit
    body_text = truncate(body_text, 200)

    approve_btn = ButtonElement(
        action_id=ACTION_ROW_APPROVE,
        text=PlainTextObject(text="Approved" if is_approved else "Approve", emoji=True),
        style="primary" if is_approved else None,
        value=button_value,
    )
    deny_btn = ButtonElement(
        action_id=ACTION_ROW_REJECT,
        text=PlainTextObject(text="Denied" if not is_approved else "Deny", emoji=True),
        style="danger" if not is_approved else None,
        value=button_value,
    )

    return Card(
        block_id=f"rowact:{req_id}:confirmation:selected:{selected}",
        title=MarkdownTextObject(text=f"*{tool_name}*"),
        body=MarkdownTextObject(text=body_text),
        actions=[approve_btn, deny_btn],
    )


# --- Row transformation helpers ---


def decision_marker(req_id: str, decision: str) -> Dict[str, Any]:
    return {
        "type": "section",
        "block_id": f"row:{req_id}:confirmation:decided:{decision}",
        "text": {"type": "plain_text", "text": " "},
    }


def build_submit_button(
    run_id: str,
    awaiting_ts: Optional[str],
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    submit_btn = ButtonElement(
        action_id="submit_pause",
        text=PlainTextObject(text="Submit", emoji=True),
        style="primary",
        value=encode_submit_button_value(run_id, awaiting_ts, session_id),
    )
    return ActionsBlock(block_id=f"pause:{run_id}", elements=[submit_btn]).to_dict()


def select_confirmation_row(
    ctx: RowActionContext,
    selected: str,
    include_reason_input: bool = False,
) -> RowTransformResult:
    updated: List[Dict[str, Any]] = []
    for block in ctx.blocks:
        block_id = block.get("block_id", "")

        # Clicked row — replace with toggle card
        if block_id.startswith(f"rowact:{ctx.req_id}:confirmation"):
            name = (block.get("title") or {}).get("text", "*tool*").replace("*", "")
            body_text = (block.get("body") or {}).get("text", "")
            toggle_card = build_confirmation_toggle_card(
                req_id=ctx.req_id,
                run_id=ctx.run_id,
                awaiting_ts=ctx.awaiting_ts,
                tool_name=name,
                body_text=body_text,
                selected=selected,
                session_id=ctx.session_id,
            )
            updated.append(block_to_dict(toggle_card))
            # Deny keeps card interactive so user can add optional reason before Submit
            if include_reason_input:
                reason_input = InputBlock(
                    block_id=f"reject_reason:{ctx.req_id}",
                    label=PlainTextObject(text="Reason (optional)"),
                    element=PlainTextInputElement(
                        action_id=ACTION_REJECT_REASON,
                        placeholder=PlainTextObject(text="Why are you rejecting this action?"),
                        multiline=True,
                    ),
                    optional=True,
                )
                updated.append(block_to_dict(reason_input))
            updated.append(decision_marker(ctx.req_id, selected))
            continue

        # Skip stale decision markers and reason inputs for this row
        if block_id.startswith(f"row:{ctx.req_id}:confirmation:decided:"):
            continue
        if block_id == f"reject_reason:{ctx.req_id}":
            continue

        # Preserve all other blocks
        updated.append(block)

    summary = confirmation_row_summary(updated)
    should_auto_submit = bool(ctx.run_id and not summary.pending_ids and not summary.has_global_submit)
    return RowTransformResult(blocks=updated, should_auto_submit=should_auto_submit)


def append_submit_if_needed(
    blocks: List[Dict[str, Any]],
    run_id: str,
    awaiting_ts: Optional[str],
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not run_id:
        return blocks
    summary = confirmation_row_summary(blocks)
    if summary.pending_ids or summary.has_global_submit:
        return blocks
    return blocks + [build_submit_button(run_id, awaiting_ts, session_id)]


# Builds InputBlocks for user_input pause type (text fields, dropdowns for bool/Enum/Literal)
def _build_input_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    blocks: List[Any] = []
    schema = requirement.user_input_schema or []
    for ui_field in schema:
        blocks.append(_build_input_field(req_id, ui_field))
    return blocks


# Builds InputBlocks for user_feedback pause type (multiple-choice questions)
def _build_feedback_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    blocks: List[Any] = []
    schema = requirement.user_feedback_schema or []
    for i, question in enumerate(schema):
        blocks.append(_build_user_feedback_question_block(req_id, question, i))
    return blocks


# Builds InputBlock for external_execution pause type (paste execution result here)
def _build_external_row(requirement: RunRequirement) -> List[Any]:
    req_id = requirement.id or ""
    return [
        InputBlock(
            block_id=external_result_block_id(req_id),
            label=PlainTextObject(text="Result"),
            element=PlainTextInputElement(
                action_id=ACTION_EXTERNAL_RESULT,
                placeholder=PlainTextObject(text="Paste the execution output here"),
                multiline=True,
            ),
        ),
    ]


def build_pause_message(
    run_id: str,
    requirements: List[RunRequirement],
    awaiting_ts: Optional[str] = None,
    session_id: Optional[str] = None,
) -> List[Any]:
    blocks: List[Any] = []
    processed = 0
    truncated_count = 0
    total = len(requirements)
    # Reserve 2 blocks for Submit button + truncation warning
    budget = MAX_MESSAGE_BLOCKS - 2

    for i, requirement in enumerate(requirements):
        kind = requirement.pause_type
        if kind == "confirmation":
            row_blocks = [
                _build_confirmation_card(requirement, run_id=run_id, awaiting_ts=awaiting_ts, session_id=session_id)
            ]
        else:
            # Input/feedback/external rows: just fields, global Submit handles submission
            if kind == "user_input":
                row_blocks = _build_input_row(requirement)
            elif kind == "user_feedback":
                row_blocks = _build_feedback_row(requirement)
            elif kind == "external_execution":
                row_blocks = _build_external_row(requirement)
            else:
                continue

        header_size = 1 if i > 0 else 0
        if len(blocks) + header_size + len(row_blocks) > budget:
            truncated_count = total - processed
            break
        if i > 0:
            blocks.append(DividerBlock())
        blocks.extend(row_blocks)
        processed += 1

    if truncated_count:
        blocks.append(
            ContextBlock(
                elements=[
                    MarkdownTextObject(
                        text=f":warning: _{truncated_count} more pause row(s) omitted — "
                        "Slack message cap. Resolve shown rows; remaining re-render after._"
                    )
                ],
            )
        )

    # Global Submit button for non-confirmation rows (input/feedback/external)
    needs_submit = any(r.pause_type != "confirmation" for r in requirements[:processed])
    if needs_submit:
        blocks.append(
            ActionsBlock(
                block_id=pause_block_id(run_id),
                elements=[
                    ButtonElement(
                        action_id=ACTION_SUBMIT,
                        text=PlainTextObject(text="Submit"),
                        style="primary",
                        value=encode_submit_button_value(run_id, awaiting_ts, session_id),
                    ),
                ],
            )
        )
    return blocks


# --- response_blocks helpers ---


def _should_skip_block(btype: str, block_id: str) -> bool:
    if btype == "actions":
        return True
    if btype == "section" and ":confirmation:decided:" in block_id:
        return True
    if block_id.startswith("reject_reason:"):
        return True
    return False


def _finalize_card(block: Dict[str, Any]) -> Dict[str, Any]:
    card = {k: v for k, v in block.items() if k != "actions"}
    block_id = block.get("block_id", "")
    title_text = (card.get("title") or {}).get("text", "")

    if ":selected:approve" in block_id:
        card["title"] = {"type": "mrkdwn", "text": f"*Approved:* {title_text.replace('*', '')}"}
    elif ":selected:deny" in block_id:
        card["title"] = {"type": "mrkdwn", "text": f"*Denied:* {title_text.replace('*', '')}"}

    return card


def _extract_input_value(element: Dict[str, Any], submitted: Dict[str, Any]) -> str:
    etype = element.get("type")

    if etype == "plain_text_input":
        return submitted.get("value") or "_(empty)_"

    if etype == "static_select":
        opt = submitted.get("selected_option") or {}
        return (opt.get("text") or {}).get("text") or opt.get("value") or "_(none)_"

    if etype in ("checkboxes", "multi_static_select"):
        opts = submitted.get("selected_options") or []
        labels = [((o.get("text") or {}).get("text") or o.get("value") or "") for o in opts]
        return ", ".join(labels) if labels else "_(none)_"

    return "_(submitted)_"


# Replaces interactive form with readonly summary so users see what was submitted
def response_blocks(
    original_blocks: List[Dict[str, Any]],
    state_values: Dict[str, Dict[str, Any]],
    requirements: List[RunRequirement],
) -> List[Dict[str, Any]]:
    preserved: List[Dict[str, Any]] = []
    submissions: List[str] = []

    for block in original_blocks:
        btype = block.get("type", "")
        block_id = block.get("block_id", "")

        if _should_skip_block(btype, block_id):
            continue

        if btype == "card":
            preserved.append(_finalize_card(block))
            continue

        if btype != "input":
            preserved.append(block)
            continue

        # Extract submitted value from input block
        label = (block.get("label") or {}).get("text", "")
        element = block.get("element") or {}
        action_id = element.get("action_id", "")
        submitted = (state_values.get(block_id) or {}).get(action_id) or {}
        value = _extract_input_value(element, submitted)
        # Labels round-trip through Slack from the input schema (may be model-derived)
        # and sit outside the code span, so inert them too.
        submissions.append(f"• {inert_code_span_text(label)}: `{inert_code_span_text(value)}`")

    if not submissions:
        return preserved

    body_text = "\n".join(submissions)
    if len(body_text) > 200:
        body_text = body_text[:197] + "..."

    return preserved + [
        {
            "type": "card",
            "title": {"type": "mrkdwn", "text": "*Submitted*"},
            "body": {"type": "mrkdwn", "text": body_text},
        }
    ]


# -----------------------------------------------------------------------------
# pause: pause
# -----------------------------------------------------------------------------

PAUSE_LABELS = {
    "confirmation": "⏸ *Awaiting approval of* `{tool}`…",
    "user_input": "⏸ *Awaiting input for* `{tool}`…",
    "user_feedback": "⏸ *Awaiting feedback*…",
    "external_execution": "⏸ *Awaiting output for* `{tool}`…",
}


async def finalize_pause(
    *,
    client: "AsyncWebClient",
    stream: Any,
    state: Any,
    run_id: str,
    channel: str,
    thread_ts: str,
    requirements: List["RunRequirement"],
    log_prefix: str = "",
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    mrkdwn: bool = True,
) -> Optional[str]:
    # 1. Stop the stream with accumulated content
    stop_kwargs = {}
    if state.has_content():
        stop_kwargs["markdown_text"] = state.flush()
    if state.task_cards:
        chunks = state.resolve_all_pending("pending")
        if chunks:
            stop_kwargs["chunks"] = chunks

    try:
        await stream.stop(**stop_kwargs)
    except Exception as exc:
        log_error(f"[HITL] stream.stop failed: run_id={run_id} err={slack_error_code(exc)!r} | {exc}")

    # 2. Post awaiting indicator
    labels = [PAUSE_LABELS[r.pause_type].format(tool=tool_name(r)) for r in requirements]
    if not labels:
        return None

    try:
        resp = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="\n".join(labels),
            **slack_delivery_kwargs(unfurl_links, unfurl_media, mrkdwn),
        )
        return resp.get("ts")
    except Exception as exc:
        log_error(f"[HITL] awaiting indicator failed: {exc}")
        return None


async def post_pause_card(
    client: "AsyncWebClient",
    paused_event: Any,
    channel: str,
    thread_ts: str,
    awaiting_ts: Optional[str] = None,
    *,
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    mrkdwn: bool = True,
    session_id: Optional[str] = None,
) -> Optional[str]:
    run_id = getattr(paused_event, "run_id", None)
    requirements = list(getattr(paused_event, "active_requirements", None) or [])
    if not run_id or not requirements:
        return None

    try:
        # The card blocks embed untrusted tool-arg text, so unfurl flags must apply here
        blocks = build_pause_message(run_id, requirements, awaiting_ts, session_id=session_id)
        resp = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Run paused — please resolve below",
            blocks=[block_to_dict(b) for b in blocks],
            **slack_delivery_kwargs(unfurl_links, unfurl_media, mrkdwn),
        )
        return resp.get("ts")
    except Exception as exc:
        log_error(f"[HITL] post_pause_card failed: run_id={run_id} | {exc}")
        return None


# -----------------------------------------------------------------------------
# events: Slack Streaming Event Handlers
# -----------------------------------------------------------------------------

# =============================================================================
# Type Aliases
# =============================================================================

# Event handlers return True on terminal events to break the stream loop
_EventHandler = Callable[
    ["BaseRunOutputEvent", StreamState, "AsyncChatStream"],
    Awaitable[bool],
]


# =============================================================================
# Helper Functions
# =============================================================================


def _normalize_event(event: str) -> str:
    """Strip 'Team' prefix so agent and team events use the same handlers."""
    return event.removeprefix("Team")


@dataclass
class _ToolRef:
    """Reference to a tool call for task card tracking."""

    tid: str | None  # Slack task card ID (None when tool_call_id is missing)
    label: str  # Display title, e.g. "Researcher: web_search"
    errored: bool


def _extract_tool_ref(chunk: BaseRunOutputEvent, state: StreamState, *, fallback_id: str | None = None) -> _ToolRef:
    """Build unique (tid, label) for each tool call's Slack task card."""
    tool = getattr(chunk, "tool", None)
    tool_name = (tool.tool_name if tool else None) or "tool"
    call_id = (tool.tool_call_id if tool else None) or fallback_id
    member = member_name(chunk, state.entity_name)
    label = f"{member}: {tool_name}" if member else tool_name
    tid = task_id(member, call_id) if call_id else None  # type: ignore[arg-type]
    errored = bool(tool.tool_call_error) if tool else False
    return _ToolRef(tid=tid, label=label, errored=errored)


async def _emit_task(
    stream: AsyncChatStream,
    card_id: str,
    title: str,
    status: str,
    *,
    output: str | None = None,
) -> None:
    """Send a task card update to the Slack stream."""
    chunk: dict = {"type": "task_update", "id": card_id, "title": title, "status": status}
    if output:
        # Slack rejects plain strings in task_card output slots — requires rich_text
        # even though slack_sdk types output as Optional[str]. Truncate to 200 chars.
        chunk["output"] = {
            "type": "rich_text",
            "elements": [{"type": "rich_text_section", "elements": [{"type": "text", "text": output[:200]}]}],
        }
    await stream.append(markdown_text="", chunks=[chunk])


async def _wf_task(
    chunk: BaseRunOutputEvent,
    state: StreamState,
    stream: AsyncChatStream,
    prefix: str,
    label: str = "",
    *,
    started: bool,
    name_attr: str = "step_name",
) -> None:
    """Emit a workflow task card for paired events (Started/Completed)."""
    name = getattr(chunk, name_attr, None) or prefix
    sid = getattr(chunk, "step_id", None) or name
    key = f"wf_{prefix}_{sid}"
    title = f"{label}: {name}" if label else name
    if started:
        state.track_task(key, title)
        await _emit_task(stream, key, title, "in_progress")
    else:
        state.complete_task(key)
        await _emit_task(stream, key, title, "complete")


# =============================================================================
# Suppression Set
# =============================================================================

# Workflows orchestrate multiple agents via steps/loops/conditions. Without
# suppression, each inner agent's tool calls and reasoning events would flood
# the Slack stream with low-level noise. We only show step-level progress.
# Values are NORMALIZED (no "Team" prefix) so one set covers agent + team events.
_SUPPRESSED_IN_WORKFLOW: frozenset[str] = frozenset(
    {
        # Reasoning: internal chain-of-thought, not actionable for Slack users
        RunEvent.reasoning_started.value,
        RunEvent.reasoning_completed.value,
        # Tool calls: workflow steps already emit their own progress cards
        RunEvent.tool_call_started.value,
        RunEvent.tool_call_completed.value,
        RunEvent.tool_call_error.value,
        # Memory: background housekeeping, no user-facing impact
        RunEvent.memory_update_started.value,
        RunEvent.memory_update_completed.value,
        # Content: workflow consolidates final output in WorkflowCompleted
        RunEvent.run_content.value,
        RunEvent.run_intermediate_content.value,
        # Lifecycle: workflow-level events handle start/end, not inner runs
        RunEvent.run_completed.value,
        RunEvent.run_error.value,
        RunEvent.run_cancelled.value,
    }
)


# =============================================================================
# Handler Factory
# =============================================================================


def _make_wf_handler(
    prefix: str,
    label: str,
    *,
    started: bool,
    name_attr: str = "step_name",
) -> _EventHandler:
    """
    Factory to create workflow event handlers for simple paired events.

    This eliminates boilerplate for events that just call _wf_task with
    different parameters (e.g., ParallelStarted, ConditionCompleted, etc.).
    """

    async def handler(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
        await _wf_task(chunk, state, stream, prefix, label, started=started, name_attr=name_attr)
        return False

    return handler


# =============================================================================
# Agent/Team Event Handlers (require custom logic)
# =============================================================================


async def _on_reasoning_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    key = f"reasoning_{state.reasoning_round}"
    state.track_task(key, "Reasoning")
    await _emit_task(stream, key, "Reasoning", "in_progress")
    return False


async def _on_reasoning_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    key = f"reasoning_{state.reasoning_round}"
    state.complete_task(key)
    state.reasoning_round += 1
    await _emit_task(stream, key, "Reasoning", "complete")
    return False


async def _on_tool_call_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # Fallback when SDK chunks omit tool_call_id so cards still render
    ref = _extract_tool_ref(chunk, state, fallback_id=str(len(state.task_cards)))
    if ref.tid:
        state.track_task(ref.tid, ref.label)
        await _emit_task(stream, ref.tid, ref.label, "in_progress")
    return False


async def _on_tool_call_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    ref = _extract_tool_ref(chunk, state)
    if ref.tid:
        # Backfill card when Completed arrives without a prior Started event
        if ref.tid not in state.task_cards:
            state.track_task(ref.tid, ref.label)
        if ref.errored:
            state.error_task(ref.tid)
        else:
            state.complete_task(ref.tid)
        await _emit_task(stream, ref.tid, ref.label, "error" if ref.errored else "complete")
    return False


async def _on_tool_call_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    ref = _extract_tool_ref(chunk, state, fallback_id=f"tool_error_{state.error_count}")
    error_msg = getattr(chunk, "error", None) or "Tool call failed"
    state.error_count += 1
    if ref.tid:
        if ref.tid not in state.task_cards:
            state.track_task(ref.tid, ref.label)
        state.error_task(ref.tid)
        await _emit_task(stream, ref.tid, ref.label, "error", output=str(error_msg))
    return False


async def _on_run_content(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # In team mode, member agents stream their own RunContentEvent (which extends
    # BaseAgentRunEvent) before the leader synthesizes a TeamRunContent (which
    # extends BaseTeamRunEvent). Showing both would duplicate content.
    if state.entity_type == "team" and isinstance(chunk, BaseAgentRunEvent):
        return False
    content = getattr(chunk, "content", None)
    if content is not None:
        state.append_content(content)
    return False


async def _on_run_intermediate_content(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # Teams emit intermediate content from each member as they finish. Showing
    # these would interleave partial outputs in the stream. The team leader
    # emits a single consolidated RunContent at the end — that's what we show.
    if state.entity_type != "team":
        content = getattr(chunk, "content", None)
        if content is not None:
            state.append_content(content)
    return False


async def _on_memory_update_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.track_task("memory_update", "Updating memory")
    await _emit_task(stream, "memory_update", "Updating memory", "in_progress")
    return False


async def _on_memory_update_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.complete_task("memory_update")
    await _emit_task(stream, "memory_update", "Updating memory", "complete")
    return False


async def _on_run_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    return False  # Finalization handled by caller after stream ends


async def _on_run_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.error_count += 1
    error_msg = getattr(chunk, "content", None) or "An error occurred"
    state.append_error(error_msg)
    state.terminal_status = "error"
    return True


async def _on_run_cancelled(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # A stop is not a failure: open cards close as complete and the caller posts
    # a short "stopped" note instead of the error message.
    state.cancelled = True
    state.terminal_status = "complete"
    return True


async def _on_run_paused(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # For Teams: only stop on TeamRunPausedEvent (has team_id), not member RunPausedEvent.
    # HITL card must carry Team's run_id — aget_run_output(member_run_id) fails at approval.
    if state.entity_type == "team":
        if getattr(chunk, "team_id", None) is None:
            return False

    state.paused_event = cast(Union["AgentRunPausedEvent", "TeamRunPausedEvent"], chunk)
    state.terminal_status = "in_progress"

    if not state.has_content() and state.stream_chars_sent == 0 and not state.task_cards:
        await stream.append(markdown_text="_Reviewing request…_")

    # Don't break early — let generator drain naturally to avoid GeneratorExit.
    # The generator returns immediately after RunPausedEvent, so no extra events arrive.
    return False


# =============================================================================
# Workflow Event Handlers (require custom logic)
# =============================================================================


async def _on_step_output(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    # StepOutput is workflow-only (agents/teams never emit it).
    # Capture but don't stream — WorkflowCompleted uses this as fallback.
    content = getattr(chunk, "content", None)
    if content is not None:
        state.workflow_final_content = str(content)
    return False


async def _on_workflow_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    wf_name = getattr(chunk, "workflow_name", None) or state.entity_name or "Workflow"
    run_id = getattr(chunk, "run_id", None) or "run"
    key = f"wf_run_{run_id}"
    state.track_task(key, f"Workflow: {wf_name}")
    await _emit_task(stream, key, f"Workflow: {wf_name}", "in_progress")
    return False


async def _on_workflow_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    run_id = getattr(chunk, "run_id", None) or "run"
    wf_name = getattr(chunk, "workflow_name", None) or state.entity_name or "Workflow"
    key = f"wf_run_{run_id}"
    state.complete_task(key)
    await _emit_task(stream, key, f"Workflow: {wf_name}", "complete")
    final = getattr(chunk, "content", None)
    if final is None:
        final = state.workflow_final_content
    if final:
        state.append_content(final)
    return False


async def _on_workflow_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    state.error_count += 1
    error_msg = getattr(chunk, "error", None) or getattr(chunk, "content", None) or "Workflow failed"
    state.append_error(error_msg)
    state.terminal_status = "error"
    return True


async def _on_step_error(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    step_name = getattr(chunk, "step_name", None) or "step"
    sid = getattr(chunk, "step_id", None) or step_name
    key = f"wf_step_{sid}"
    error_msg = getattr(chunk, "error", None) or "Step failed"
    if key not in state.task_cards:
        state.track_task(key, step_name)
    state.error_task(key)
    await _emit_task(stream, key, step_name, "error", output=str(error_msg))
    return False


# =============================================================================
# Loop Event Handlers (custom logic for iteration tracking)
# =============================================================================


async def _on_loop_execution_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    loop_key = getattr(chunk, "step_id", None) or step_name
    max_iter = getattr(chunk, "max_iterations", None)
    title = f"Loop: {step_name}" + (f" (max {max_iter})" if max_iter else "")
    key = f"wf_loop_{loop_key}"
    state.track_task(key, title)
    await _emit_task(stream, key, title, "in_progress")
    return False


async def _on_loop_iteration_started(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    loop_key = getattr(chunk, "step_id", None) or getattr(chunk, "step_name", None) or "loop"
    iteration = getattr(chunk, "iteration", 0)
    max_iter = getattr(chunk, "max_iterations", None)
    title = f"Iteration {iteration}" + (f"/{max_iter}" if max_iter else "")
    key = f"wf_loop_{loop_key}_iter_{iteration}"
    state.track_task(key, title)
    await _emit_task(stream, key, title, "in_progress")
    return False


async def _on_loop_iteration_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    loop_key = getattr(chunk, "step_id", None) or getattr(chunk, "step_name", None) or "loop"
    iteration = getattr(chunk, "iteration", 0)
    key = f"wf_loop_{loop_key}_iter_{iteration}"
    state.complete_task(key)
    await _emit_task(stream, key, f"Iteration {iteration}", "complete")
    return False


async def _on_loop_execution_completed(chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    step_name = getattr(chunk, "step_name", None) or "loop"
    loop_key = getattr(chunk, "step_id", None) or step_name
    key = f"wf_loop_{loop_key}"
    state.complete_task(key)
    await _emit_task(stream, key, f"Loop: {step_name}", "complete")
    return False


# =============================================================================
# Dispatch Table
# =============================================================================

# Single dispatch table — keys are normalized (no "Team" prefix).
# Workflow event names never start with "Team" so normalization is a no-op for them.
HANDLERS: Dict[str, _EventHandler] = {
    # -------------------------------------------------------------------------
    # Agent/Team Events (normalized - use RunEvent values)
    # -------------------------------------------------------------------------
    RunEvent.reasoning_started.value: _on_reasoning_started,
    RunEvent.reasoning_completed.value: _on_reasoning_completed,
    RunEvent.tool_call_started.value: _on_tool_call_started,
    RunEvent.tool_call_completed.value: _on_tool_call_completed,
    RunEvent.tool_call_error.value: _on_tool_call_error,
    RunEvent.run_content.value: _on_run_content,
    RunEvent.run_intermediate_content.value: _on_run_intermediate_content,
    RunEvent.memory_update_started.value: _on_memory_update_started,
    RunEvent.memory_update_completed.value: _on_memory_update_completed,
    RunEvent.run_completed.value: _on_run_completed,
    RunEvent.run_error.value: _on_run_error,
    RunEvent.run_cancelled.value: _on_run_cancelled,
    # HITL pause — router posts approval card separately since appendStream rejects Block Kit
    RunEvent.run_paused.value: _on_run_paused,
    TeamRunEvent.run_paused.value: _on_run_paused,
    # -------------------------------------------------------------------------
    # Workflow Lifecycle Events
    # -------------------------------------------------------------------------
    WorkflowRunEvent.step_output.value: _on_step_output,
    WorkflowRunEvent.workflow_started.value: _on_workflow_started,
    WorkflowRunEvent.workflow_completed.value: _on_workflow_completed,
    WorkflowRunEvent.workflow_error.value: _on_workflow_error,
    WorkflowRunEvent.workflow_cancelled.value: _on_run_cancelled,
    # -------------------------------------------------------------------------
    # Workflow Step Events
    # -------------------------------------------------------------------------
    WorkflowRunEvent.step_started.value: _make_wf_handler("step", "", started=True),
    WorkflowRunEvent.step_completed.value: _make_wf_handler("step", "", started=False),
    WorkflowRunEvent.step_error.value: _on_step_error,
    # -------------------------------------------------------------------------
    # Workflow Loop Events
    # -------------------------------------------------------------------------
    WorkflowRunEvent.loop_execution_started.value: _on_loop_execution_started,
    WorkflowRunEvent.loop_iteration_started.value: _on_loop_iteration_started,
    WorkflowRunEvent.loop_iteration_completed.value: _on_loop_iteration_completed,
    WorkflowRunEvent.loop_execution_completed.value: _on_loop_execution_completed,
    # -------------------------------------------------------------------------
    # Workflow Structural Events (factory-generated)
    # -------------------------------------------------------------------------
    WorkflowRunEvent.parallel_execution_started.value: _make_wf_handler("parallel", "Parallel", started=True),
    WorkflowRunEvent.parallel_execution_completed.value: _make_wf_handler("parallel", "Parallel", started=False),
    WorkflowRunEvent.condition_execution_started.value: _make_wf_handler("cond", "Condition", started=True),
    WorkflowRunEvent.condition_execution_completed.value: _make_wf_handler("cond", "Condition", started=False),
    WorkflowRunEvent.router_execution_started.value: _make_wf_handler("router", "Router", started=True),
    WorkflowRunEvent.router_execution_completed.value: _make_wf_handler("router", "Router", started=False),
    WorkflowRunEvent.workflow_agent_started.value: _make_wf_handler(
        "agent", "Running", started=True, name_attr="agent_name"
    ),
    WorkflowRunEvent.workflow_agent_completed.value: _make_wf_handler(
        "agent", "Running", started=False, name_attr="agent_name"
    ),
    WorkflowRunEvent.steps_execution_started.value: _make_wf_handler("steps", "Steps", started=True),
    WorkflowRunEvent.steps_execution_completed.value: _make_wf_handler("steps", "Steps", started=False),
}


async def process_event(ev_raw: str, chunk: BaseRunOutputEvent, state: StreamState, stream: AsyncChatStream) -> bool:
    """
    Process a streaming event and update Slack accordingly.

    Args:
        ev_raw: Raw event name (e.g., "ToolCallStarted", "TeamRunContent")
        chunk: Stream chunk containing event data
        state: StreamState tracking session state
        stream: Slack chat_stream for sending updates

    Returns:
        True if this is a terminal event and the stream loop should break.
    """
    ev = _normalize_event(ev_raw)

    # Suppress nested agent internals in workflow mode
    if state.entity_type == "workflow" and ev in _SUPPRESSED_IN_WORKFLOW:
        return False

    handler = HANDLERS.get(ev)
    if handler:
        return await handler(chunk, state, stream)

    return False


# -----------------------------------------------------------------------------
# sessions: Slack agent-session status and prompts, with a fallback to the legacy Assistant API.
# -----------------------------------------------------------------------------

SessionStatus = Literal["processing", "active", "suspended", "closed"]

# Errors that mean "this app does not have the agent-session API", as opposed to a
# transient failure that should not flip the mode
_FALLBACK_ERRORS = frozenset(
    {"unknown_method", "method_deprecated", "missing_scope", "not_allowed_token_type", "invalid_arguments"}
)


class SlackSessions:
    def __init__(self, client: AsyncWebClient, loading_messages: Optional[List[str]] = None) -> None:
        self.client = client
        self.loading_messages = loading_messages
        self.legacy = False

    def use_assistant_api(self) -> None:
        """Pin the legacy API; called when Slack sends an Assistant-only event."""
        if not self.legacy:
            log_debug("Slack Assistant-view event received; using assistant API from now on")
            self.legacy = True

    def _fall_back(self, exc: SlackApiError) -> bool:
        code = slack_error_code(exc)
        if code in _FALLBACK_ERRORS:
            log_debug(f"Slack agent-session API unavailable ({code}); using assistant API from now on")
            self.legacy = True
            return True
        return False

    async def set_status(self, channel_id: str, thread_ts: str, status: SessionStatus, legacy_text: str = "") -> None:
        """Move the session to ``status``.

        Under the assistant API only a loading text exists: ``processing`` shows
        ``legacy_text`` and every other status clears it.
        """
        if not self.legacy:
            try:
                await self.client.agents_sessions_setStatus(channel_id=channel_id, thread_ts=thread_ts, status=status)
                return
            except SlackApiError as exc:
                if not self._fall_back(exc):
                    log_warning(f"agents.sessions.setStatus failed: {slack_error_code(exc)}")
                    return
            except Exception as exc:
                log_warning(f"agents.sessions.setStatus failed: {exc}")
                return

        kwargs: Dict[str, Any] = {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "status": legacy_text if status == "processing" else "",
        }
        if status == "processing" and self.loading_messages:
            kwargs["loading_messages"] = self.loading_messages
        try:
            await self.client.assistant_threads_setStatus(**kwargs)
        except Exception as exc:
            log_warning(f"assistant.threads.setStatus failed: {exc}")

    async def rename(self, channel_id: str, thread_ts: str, title: str) -> None:
        if not self.legacy:
            try:
                await self.client.agents_sessions_rename(channel_id=channel_id, thread_ts=thread_ts, title=title)
                return
            except SlackApiError as exc:
                if not self._fall_back(exc):
                    log_warning(f"agents.sessions.rename failed: {slack_error_code(exc)}")
                    return
            except Exception as exc:
                log_warning(f"agents.sessions.rename failed: {exc}")
                return
        try:
            await self.client.assistant_threads_setTitle(channel_id=channel_id, thread_ts=thread_ts, title=title)
        except Exception as exc:
            log_warning(f"assistant.threads.setTitle failed: {exc}")

    async def set_suggested_prompts(
        self, channel_id: str, prompts: List[Dict[str, str]], thread_ts: Optional[str] = None
    ) -> None:
        """Show ``prompts`` above the composer.

        On the Agent view prompts belong to the Messages tab as a whole and Slack
        rejects a thread, so ``thread_ts`` is only sent under the assistant API.
        """
        if not prompts:
            return
        kwargs: Dict[str, Any] = {"channel_id": channel_id, "prompts": prompts}
        if thread_ts and self.legacy:
            kwargs["thread_ts"] = thread_ts
        try:
            await self.client.assistant_threads_setSuggestedPrompts(**kwargs)
        except Exception as exc:
            log_warning(f"assistant.threads.setSuggestedPrompts failed: {slack_error_code(exc) or exc}")


# -----------------------------------------------------------------------------
# threads: Per-thread state the interface keeps between Slack events.
# -----------------------------------------------------------------------------


@dataclass
class ActiveRun:
    entity: Any
    # Slack user who started (or resumed) the run; only they may stop it
    owner: Optional[str] = None
    stream: Any = None
    run_id: Optional[str] = None
    cancel_requested: bool = False
    # Someone else pressed stop: Slack has already closed the streaming message
    stream_halted: bool = False


@dataclass
class ThreadState:
    run: Optional[ActiveRun] = None
    # What the user is looking at, from app_context_changed
    entities: List[Dict[str, Any]] = field(default_factory=list)
    # The last title this interface set, so a title_changed echo is not re-applied
    last_title: Optional[str] = None
    # Agno session ids already named after their first message
    named_sessions: List[str] = field(default_factory=list)


async def _cancel(entity: Any, run_id: str) -> None:
    try:
        from agno.os.services.runs import cancel_component_run

        await cancel_component_run(entity, run_id)
    except Exception as exc:
        log_error(f"Slack stop: cancelling run {run_id} failed: {exc}")


class Threads:
    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max_entries
        self._threads: "OrderedDict[Tuple[str, str], ThreadState]" = OrderedDict()

    def get(self, channel: str, thread_ts: str) -> Optional[ThreadState]:
        return self._threads.get((channel, thread_ts))

    def state(self, channel: str, thread_ts: str) -> ThreadState:
        key = (channel, thread_ts)
        thread = self._threads.get(key)
        if thread is None:
            thread = ThreadState()
            self._threads[key] = thread
            while len(self._threads) > self._max_entries:
                self._threads.popitem(last=False)
        return thread

    # -- active run ---------------------------------------------------------

    def start_run(self, channel: str, thread_ts: str, entity: Any, owner: Optional[str] = None) -> ActiveRun:
        run = ActiveRun(entity=entity, owner=owner or None)
        self.state(channel, thread_ts).run = run
        return run

    def finish_run(self, channel: str, thread_ts: str, run: ActiveRun) -> None:
        thread = self.get(channel, thread_ts)
        # Only the run that registered itself may clear the slot
        if thread is not None and thread.run is run:
            thread.run = None

    async def note_run_id(self, run: ActiveRun, run_id: str) -> None:
        if run.run_id == run_id:
            return
        run.run_id = run_id
        if run.cancel_requested:
            # Stop was pressed before the id was known
            log_debug(f"Slack stop: applying deferred cancel to run {run_id}")
            await _cancel(run.entity, run_id)

    async def request_stop(
        self, channel: str, thread_ts: str, requested_by: Optional[str] = None
    ) -> Tuple[Optional[ActiveRun], bool]:
        """Cancel the thread's run. Returns ``(run, allowed)``.

        Only the run's owner may stop it. A stop from anyone else is refused and the
        run is flagged so the streaming loop can recover from Slack's halted stream.
        """
        thread = self.get(channel, thread_ts)
        run = thread.run if thread else None
        if run is None:
            return None, False
        if run.owner and requested_by and requested_by != run.owner:
            run.stream_halted = True
            return run, False
        run.cancel_requested = True
        if run.run_id:
            await _cancel(run.entity, run.run_id)
        return run, True

    # -- context, titles, names ---------------------------------------------

    def set_context(self, channel: str, thread_ts: str, context: Optional[Dict[str, Any]]) -> None:
        thread = self.state(channel, thread_ts)
        context = context or {}
        entities = context.get("entities")
        if isinstance(entities, list):
            thread.entities = [e for e in entities if isinstance(e, dict)]
        elif context.get("channel_id"):
            # Assistant experience reports a single channel instead of an entity list
            thread.entities = [{"type": "slack#/types/channel_id", "value": context["channel_id"]}]
        else:
            thread.entities = []

    def entities_for(self, channel: str, thread_ts: str) -> List[Dict[str, Any]]:
        thread = self.get(channel, thread_ts)
        return list(thread.entities) if thread else []

    def set_last_title(self, channel: str, thread_ts: str, title: str) -> None:
        self.state(channel, thread_ts).last_title = title

    def last_title(self, channel: str, thread_ts: str) -> Optional[str]:
        thread = self.get(channel, thread_ts)
        return thread.last_title if thread else None

    def mark_session_named(self, channel: str, thread_ts: str, session_id: str) -> bool:
        """Record that ``session_id`` was named; returns False if it already was."""
        thread = self.state(channel, thread_ts)
        if session_id in thread.named_sessions:
            return False
        thread.named_sessions.append(session_id)
        return True
