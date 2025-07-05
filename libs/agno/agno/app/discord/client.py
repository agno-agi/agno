from os import getenv
from typing import Optional

import requests

from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from agno.utils.log import log_info

try:
    import discord
except (ImportError, ModuleNotFoundError):
    print("`discord.py` not installed. Please install using `pip install discord.py`")


class DiscordClient:
    def __init__(self, agent: Optional[Agent] = None, team: Optional[Team] = None):
        self.agent = agent
        self.team = team
        self.intents = discord.Intents.all()
        self.client = discord.Client(intents=self.intents)
        self._setup_events()

    def _setup_events(self):
        @self.client.event
        async def on_message(message):
            if message.author == self.client.user:
                log_info(f"sent {message.content}")
            else:
                message_image = None
                message_video = None
                message_audio = None
                message_file = None
                media_url = None
                message_text = message.content
                message_url = message.jump_url
                message_user = message.author.name

                if message.attachments:
                    media = message.attachments[0]
                    media_type = media.content_type
                    media_url = media.url
                    if media_type.startswith("image/"):
                        message_image = media_url
                    elif media_type.startswith("video/"):
                        req = requests.get(media_url)
                        video = req.content
                        message_video = video
                    elif media_type.startswith("application/"):
                        req = requests.get(media_url)
                        document = req.content
                        message_file = document
                    elif media_type.startswith("audio/"):
                        message_audio = media_url

                log_info(f"processing message:{message_text} \n with media: {media_url} \n url:{message_url}")

                if isinstance(message.channel, discord.Thread):
                    thread = message.channel
                else:
                    thread = await message.create_thread(name=f"{message_user}'s thread")

                await thread.typing()

                if self.agent:
                    self.agent.additional_context = f"message username:\n{message_user} \n message_url:{message_url}"
                    response = await self.agent.arun(
                        message_text,
                        user_id=message_user,
                        session_id=str(thread.id),
                        images=[Image(url=message_image)] if message_image else None,
                        videos=[Video(content=message_video)] if message_video else None,
                        audio=[Audio(url=message_audio)] if message_audio else None,
                    )
                elif self.team:
                    self.team.additional_context = f"message username:\n{message_user} \n message_url:{message_url}"
                    response = await self.team.arun(
                        message=message_text,
                        user_id=message_user,
                        session_id=str(thread.id),
                        images=[Image(url=message_image)] if message_image else None,
                        videos=[Video(content=message_video)] if message_video else None,
                        audio=[Audio(url=message_audio)] if message_audio else None,
                        files=[File(url=message_audio)] if message_file else None,
                    )

                if response.reasoning_content:
                    await self._send_discord_messages(
                        thread=thread, message=f"Reasoning: \n{response.reasoning_content}", italics=True
                    )
                await self._send_discord_messages(thread=thread, message=response.content)

    async def _send_discord_messages(self, thread: discord.channel, message: str, italics: bool = False):  # type: ignore
        if len(message) < 1500:
            if italics:
                formatted_message = "\n".join([f"_{line}_" for line in message.split("\n")])
                await thread.send(formatted_message)  # type: ignore
            else:
                await thread.send(message)  # type: ignore
            return

        message_batches = [message[i : i + 1500] for i in range(0, len(message), 1500)]

        for i, batch in enumerate(message_batches, 1):
            batch_message = f"[{i}/{len(message_batches)}] {batch}"
            if italics:
                formatted_batch = "\n".join([f"_{line}_" for line in batch_message.split("\n")])
                await thread.send(formatted_batch)  # type: ignore
            else:
                await thread.send(batch_message)  # type: ignore

    def serve(self):
        try:
            token = getenv("DISCORD_BOT_TOKEN")
            if not token:
                raise ValueError("DISCORD_BOT_TOKEN NOT SET")
            return self.client.run(token)
        except Exception as e:
            raise ValueError(f"Failed to run Discord client: {str(e)}")
