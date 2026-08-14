"""Discord wire-protocol constants.

Discord's API speaks integers for types and flags; the enums here name them.
Values are verbatim from the official docs (linked per enum) and serialize to
the same JSON since IntEnum members are ints.
"""

from enum import IntEnum

DISCORD_API = "https://discord.com/api/v10"

MAX_MESSAGE_LENGTH = 2000
MAX_THREAD_NAME_LENGTH = 100

# Message flag: reply visible only to the invoking user
# https://docs.discord.com/developers/resources/message#message-object-message-flags
EPHEMERAL_FLAG = 64


class InteractionType(IntEnum):
    """https://docs.discord.com/developers/interactions/receiving-and-responding#interaction-object-interaction-type"""

    PING = 1
    APPLICATION_COMMAND = 2


class InteractionResponseType(IntEnum):
    """https://docs.discord.com/developers/interactions/receiving-and-responding#interaction-response-object-interaction-callback-type"""

    PONG = 1
    CHANNEL_MESSAGE_WITH_SOURCE = 4
    DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE = 5


class CommandOptionType(IntEnum):
    """https://docs.discord.com/developers/interactions/application-commands#application-command-object-application-command-option-type"""

    STRING = 3
    BOOLEAN = 5
    ATTACHMENT = 11


class IntegrationType(IntEnum):
    """Where an app can be installed.

    https://docs.discord.com/developers/resources/application#application-object-application-integration-types
    """

    GUILD_INSTALL = 0
    USER_INSTALL = 1


class InteractionContextType(IntEnum):
    """Where an installed command can be used.

    https://docs.discord.com/developers/interactions/receiving-and-responding#interaction-object-interaction-context-types
    """

    GUILD = 0
    BOT_DM = 1
    PRIVATE_CHANNEL = 2


class ChannelType(IntEnum):
    """https://docs.discord.com/developers/resources/channel#channel-object-channel-types"""

    ANNOUNCEMENT_THREAD = 10
    PUBLIC_THREAD = 11
    PRIVATE_THREAD = 12


# Channel types considered threads (payload channel types are plain ints;
# IntEnum members compare and hash equal to them)
THREAD_CHANNEL_TYPES = {
    ChannelType.ANNOUNCEMENT_THREAD,
    ChannelType.PUBLIC_THREAD,
    ChannelType.PRIVATE_THREAD,
}
