from os import getenv
from textwrap import dedent
from typing import Optional, Union

import requests

from agno.agent.agent import Agent, RunResponse
from agno.media import Audio, File, Image, Video
from agno.team.team import Team, TeamRunResponse
from agno.utils.log import log_info, log_warning

try:
    import discord

except (ImportError, ModuleNotFoundError):
    print("`discord.py` not installed. Please install using `pip install discord.py`")


class RequiresConfirmationView(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.value = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary)
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.value = True
        button.disabled = True
        await interaction.response.edit_message(view=self)
        self.clear_items()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.value = False
        button.disabled = True
        await interaction.response.edit_message(view=self)
        self.clear_items()
        self.stop()

    async def on_timeout(self):
        log_warning("Agent Timeout Error")


class DiscordClient:
    def __init__(
        self, agent: Optional[Agent] = None, team: Optional[Team] = None, client: Optional[discord.Client] = None
    ):
        self.agent = agent
        self.team = team
        if client is None:
            self.intents = discord.Intents.all()
            self.client = discord.Client(intents=self.intents)
        else:
            self.client = client
        self._setup_events()

    def _setup_events(self):
        @self.client.event
        async def on_message(message):
            if message.author == self.client.user:
                log_info(f"sent {message.content}")
                return

            message_image = None
            message_video = None
            message_audio = None
            message_file = None
            media_url = None
            message_text = message.content
            message_url = message.jump_url
            message_user = message.author.name
            message_user_id = message.author.id

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
            elif isinstance(message.channel, discord.channel.DMChannel):
                thread = message.channel  # type: ignore
            elif isinstance(message.channel, discord.TextChannel):
                thread = await message.create_thread(name=f"{message_user}'s thread")
            else:
                log_info(f"received {message.content} but not in a supported channel")
                return

            async with thread.typing():
                # TODO Unhappy with the duplication here but it keeps MyPy from complaining
                additional_context = dedent(f"""
                    Discord username: {message_user}
                    Discord url: {message_url}
                    """)
                if self.agent:
                    self.agent.additional_context = additional_context
                    agent_response: RunResponse = await self.agent.arun(
                        message_text,
                        user_id=message_user_id,
                        session_id=str(thread.id),
                        images=[Image(url=message_image)] if message_image else None,
                        videos=[Video(content=message_video)] if message_video else None,
                        audio=[Audio(url=message_audio)] if message_audio else None,
                        files=[File(content=message_file)] if message_file else None,
                    )
                    await self._handle_response_in_thread(agent_response, thread)
                elif self.team:
                    self.team.additional_context = additional_context
                    team_response: TeamRunResponse = await self.team.arun(
                        message_text,
                        user_id=message_user_id,
                        session_id=str(thread.id),
                        images=[Image(url=message_image)] if message_image else None,
                        videos=[Video(content=message_video)] if message_video else None,
                        audio=[Audio(url=message_audio)] if message_audio else None,
                        files=[File(content=message_file)] if message_file else None,
                    )
                    await self._handle_response_in_thread(team_response, thread)

    async def handle_hitl(
        self, run_response: RunResponse, thread: Union[discord.Thread, discord.TextChannel]
    ) -> RunResponse:
        """Handles optional Human-In-The-Loop interaction."""
        if run_response.is_paused:
            for tool in run_response.tools_requiring_confirmation:
                view = RequiresConfirmationView()
                await thread.send(f"Tool requiring confirmation: {tool.tool_name}", view=view)
                await view.wait()
                tool.confirmed = view.value if view.value is not None else False

            if self.agent:
                run_response = await self.agent.acontinue_run(
                    run_response=run_response,
                )

        return run_response

    async def _handle_response_in_thread(
        self, response: Union[RunResponse, TeamRunResponse], thread: Union[discord.TextChannel, discord.Thread]
    ):
        if isinstance(response, RunResponse):
            response = await self.handle_hitl(response, thread)

        if response.reasoning_content:
            await self._send_discord_messages(
                thread=thread, message=f"Reasoning: \n{response.reasoning_content}", italics=True
            )

        await self._send_discord_messages(thread=thread, message=str(response.content))

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
