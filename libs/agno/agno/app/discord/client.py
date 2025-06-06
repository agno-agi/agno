from os import getenv
from typing import Optional
from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from agno.utils.log import log_info
import requests
try:
    import discord
except(ImportError,ModuleNotFoundError):
    print("`discord.py` not installed. Please install using `pip install discord.py`")

intents = discord.Intents.all()
client = discord.Client(intents=intents)
try:
    DISCORD_TOKEN= getenv("DISCORD_BOT_TOKEN")
except Exception:
    raise ValueError("DISCORD_BOT_TOKEN NOT SET")

def DiscordClient(agent: Optional[Agent] = None, team: Optional[Team] = None):
    @client.event
    async def on_message(message):
        if message.author == client.user:
            log_info(f"sent {message.content}")
        else:
            message_image = None
            message_video = None
            message_audio = None
            media_url=None
            message_text=message.content
            if message.attachments:
                media=message.attachments[0]
                media_type=media.content_type
                media_url=media.url
                if (media_type.startswith("image/")):
                    message_image=media_url
                elif(media_type.startswith("video/")):
                    req = requests.get(media_url)
                    video=req.content
                    message_video=video                
                elif(media_type.startswith("audio/")):
                    message_audio=media_url                
            log_info(f"processing message:{message_text} \n with media: {media_url}")
            if isinstance(message.channel, discord.Thread):
                thread = message.channel
            else:
                thread = await message.create_thread(name="thread")
            if agent:
                response = await agent.arun(message_text, user_id=message.author.name,session_id=thread.id,
                    images=[Image(url=message_image)] if message_image else None,
                    videos=[Video(content=message_video)] if message_video else None,
                    audio=[Audio(url=message_audio)] if message_audio else None)
            elif team:
                response = await team.arun(message_text, user_id=message.author.name,session_id=thread.id,
                    images=[Image(url=message_image)] if message_image else None,
                    videos=[Video(url=message_video)] if message_video else None,
                    audio=[Audio(url=message_audio)] if message_audio else None,)
            if response.reasoning_content:
                await _send_discord_messages(thread=thread,message= f"Reasoning: \n{response.reasoning_content}", italics=True)
            await _send_discord_messages(thread=thread,message=response.content)
        

    async def _send_discord_messages(thread: discord.channel , message: str, italics: bool = False):
        if len(message) < 1500:
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_message = "\n".join([f"_{line}_" for line in message.split("\n")])
                await thread.send(formatted_message)
            else:
                await thread.send(message)
            return


        message_batches = [message[i : i + 1500] for i in range(0, len(message), 1500)]

        # Add a prefix with the batch number
        for i, batch in enumerate(message_batches, 1):
            batch_message = f"[{i}/{len(message_batches)}] {batch}"
            if italics:
                # Handle multi-line messages by making each line italic
                formatted_batch = "\n".join([f"_{line}_" for line in batch_message.split("\n")])
                await thread.send(formatted_batch)
            else:
                await thread.send(batch_message)
    return client.run(DISCORD_TOKEN)
    