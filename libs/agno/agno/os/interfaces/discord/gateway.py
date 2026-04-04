import io
from typing import Any, List, Optional, Union

from agno.agent import Agent, RemoteAgent
from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.processing import MAX_ATTACHMENT_BYTES, run_entity, run_entity_stream, strip_mention
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_info, log_warning
from agno.workflow import RemoteWorkflow, Workflow

# discord.py is an optional dependency — only needed when Gateway mode is enabled.
# When absent, the HTTP webhook transport (router.py) still works independently.
try:
    import discord
except ImportError:
    discord = None  # type: ignore


class GatewayReplier:
    def __init__(self, channel: Any):
        self._channel = channel
        self._initial_message: Any = None

    async def send_initial_response(self, text: str) -> None:
        self._initial_message = await self._channel.send(text)

    async def edit_response(self, text: str) -> None:
        if self._initial_message is not None:
            await self._initial_message.edit(content=text)

    async def send_followup(self, text: str) -> None:
        await self._channel.send(text)

    async def send_media(self, content: bytes, filename: str) -> None:
        if discord is None:
            return
        await self._channel.send(file=discord.File(io.BytesIO(content), filename=filename))


def create_gateway_client(
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    stream: bool = False,
    reply_in_thread: bool = True,
    show_reasoning: bool = True,
    max_message_chars: int = 1900,
    allowed_guild_ids: Optional[List[str]] = None,
    allowed_channel_ids: Optional[List[str]] = None,
) -> Any:
    """Create a ``discord.Client`` that listens for @mentions and delegates to ``run_entity``.

    Returns the client instance (not started).  Callers should use
    ``await client.start(token)`` inside an async task.
    """
    if discord is None:
        raise ImportError("discord.py is required for gateway support. Install with: pip install discord.py")

    # Intents control which events Discord sends over the WebSocket.
    # messages=True subscribes to MESSAGE_CREATE events.
    # message_content privileged intent is NOT needed — Discord exempts bot @mention
    # messages from the intent requirement, so we can read message.content without it.
    intents = discord.Intents.default()
    intents.messages = True

    client = discord.Client(intents=intents)
    entity = agent or team or workflow

    @client.event
    async def on_ready() -> None:
        log_info(f"Discord Gateway connected as {client.user}")

    @client.event
    async def on_message(message: Any) -> None:
        # 1. Skip bot messages
        if message.author.bot:
            return

        # 2. In guilds, only respond to direct @mentions of the bot.
        #    In DMs there's no guild, so we always process (skip this check).
        if message.guild and (client.user is None or not client.user.mentioned_in(message)):
            return

        # 3. Ignore @everyone/@here pings — these aren't directed at the bot
        if message.mention_everyone:
            return

        # 4. Guild/channel allowlist checks
        if message.guild:
            if allowed_guild_ids and str(message.guild.id) not in allowed_guild_ids:
                return
            if allowed_channel_ids and str(message.channel.id) not in allowed_channel_ids:
                return

        # 5. Strip mention from text
        text = strip_mention(message.content)
        if not text and not message.attachments:
            return

        user_id = str(message.author.id)

        # 6. Determine reply channel and session ID.
        #
        # Session ID scheme (shared with router.py:_build_session_id):
        #   dc:thread:{id}                      — thread or newly-created thread
        #   dc:dm:{id}                           — direct message channel
        #   dc:channel:{id}:user:{user_id}       — guild text channel (scoped per user)
        #
        # When reply_in_thread=True, the bot creates a new thread from each @mention
        # message.  This keeps the main channel clean and gives each conversation its
        # own session context (history, memory).  If the message is already in a thread,
        # the bot replies in-place instead of nesting further.
        channel: Any = message.channel
        if isinstance(message.channel, discord.Thread):
            session_id = f"dc:thread:{message.channel.id}"
        elif isinstance(message.channel, discord.DMChannel):
            session_id = f"dc:dm:{message.channel.id}"
        elif reply_in_thread and message.guild:
            thread_name = text[:100].strip() or "New conversation"
            try:
                channel = await message.create_thread(name=thread_name)
                session_id = f"dc:thread:{channel.id}"
            except Exception as e:
                log_warning(f"Failed to create thread (missing MANAGE_THREADS permission?): {e}")
                channel = message.channel
                session_id = f"dc:channel:{message.channel.id}:user:{user_id}"
        else:
            channel = message.channel
            session_id = f"dc:channel:{message.channel.id}:user:{user_id}"

        # 7. Download attachments — oversized files (>25 MB) and download failures are
        # skipped silently so one bad attachment doesn't block the rest.
        images: List[Image] = []
        files_list: List[File] = []
        audio_list: List[Audio] = []
        videos: List[Video] = []

        for attachment in message.attachments:
            content_type = attachment.content_type or "application/octet-stream"
            if attachment.size > MAX_ATTACHMENT_BYTES:
                log_warning(f"Attachment too large ({attachment.size} bytes), skipping: {attachment.filename}")
                continue
            try:
                content_bytes = await attachment.read()
            except Exception as e:
                log_error(f"Failed to download attachment: {e}")
                continue

            if content_type.startswith("image/"):
                images.append(Image(content=content_bytes))
            elif content_type.startswith("video/"):
                videos.append(Video(content=content_bytes))
            elif content_type.startswith("audio/"):
                audio_list.append(Audio(content=content_bytes))
            else:
                files_list.append(File(content=content_bytes, filename=attachment.filename))

        # 8. Process with typing indicator
        # Streaming is only supported for local Agent/Team (not Workflow or Remote entities)
        use_stream = stream and (agent or team) and not isinstance(entity, (RemoteAgent, RemoteTeam))

        async with channel.typing():
            replier = GatewayReplier(channel=channel)
            try:
                if use_stream:
                    await run_entity_stream(
                        entity=entity,  # type: ignore[arg-type]
                        message_text=text,
                        user_id=user_id,
                        session_id=session_id,
                        replier=replier,
                        show_reasoning=show_reasoning,
                        max_message_chars=max_message_chars,
                        images=images or None,
                        files=files_list or None,
                        audio=audio_list or None,
                        videos=videos or None,
                    )
                else:
                    await run_entity(
                        entity=entity,  # type: ignore[arg-type]
                        message_text=text,
                        user_id=user_id,
                        session_id=session_id,
                        replier=replier,
                        show_reasoning=show_reasoning,
                        max_message_chars=max_message_chars,
                        images=images or None,
                        files=files_list or None,
                        audio=audio_list or None,
                        videos=videos or None,
                    )
            except Exception as e:
                log_error(f"Error processing Discord message: {e}")
                try:
                    await channel.send("Sorry, there was an error processing your message.")
                except Exception:
                    pass

    return client
