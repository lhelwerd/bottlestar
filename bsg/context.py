"""
Command context.
"""

import logging
import re
import discord
from .byc import Dialog
from .card import Cards
from .config import ServerConfig

class Context:
    """
    Context for a command.
    """

    @property
    def typing(self):
        """
        Indicate to the context that the bot is processing a command.
        """

        return None

    async def send(self, message, **kw):
        """
        Send a message to the context.
        """

        raise NotImplementedError("Must be implemented by subclasses")

    def replace_roles(self, message, **kw):
        return message, None

    def make_mentions(self, **kw):
        return None

    @property
    def emoji_display(self):
        """
        Return a string describing the preferred display style for emojis in
        this context. Can be an empty string to disable display.
        """

        return ""

    @property
    def prefix(self):
        """
        Return a string to place before commands when explaining how to run a
        command. If the bot only responds to certain prefixes, use the most
        commonly used one.
        """

        return ""

    @property
    def arguments(self):
        """
        Provide a dictionary of additional options that may be provided to
        commands dependent on context.
        """

        return {}

    @property
    def user(self):
        """
        Return an object describing the original sender that caused the bot to
        process a command. This object is context-dependent and could be used
        to feed back into certain context methods with keyword arguments.
        """

        raise NotImplementedError("Must be implemented by subclasses")

    @property
    def mention(self):
        """
        Return a string that can be used in a reply to the original sender
        that caused the bot to process a command in order to grab their
        attention in a reply.
        """

        raise NotImplementedError("Must be implemented by subclasses")

    @property
    def mentions(self):
        return []

    def get_user(self, username):
        return None

    def get_channel_mention(self, channel=None):
        if channel is not None:
            return channel

        return ""

    @property
    def config_editable(self):
        """
        Return a boolean indicating if commands that change configuration are
        enabled in this context. This can be denied if the configuration would
        become global or perform permisssion checks for the user.
        """

        return False

    @property
    def byc_enabled(self):
        """
        Return a boolean indicating if BYC commands are enabled in this context.
        """

        return True

    @property
    def user_byc_channel(self):
        """
        Return a string indicating the channel in which a user should post
        private commands to for BYC, or `None` if no such channel can be found.
        If this is the empty string, then the current channel is acceptable.
        """

        return None

    async def update_byc_channels(self, game_id, seed):
        pass

    @property
    def game_id(self):
        return 0

    @property
    def roles(self):
        return []

    @property
    def topic(self):
        return None

    async def set_topic(self, topic, reason=None):
        pass

    async def replace_pins(self, messages, channel=None):
        """
        Unpin all pinned messages made by the bot before and pin the list of
        messages in the provided `channel` or in the original message's
        channel if no `channel` is provided.

        Does nothing if pinning is not supported in this context.
        """

        pass

    def get_color(self, color):
        return ""

    async def create_role(self, **kw):
        return None

class CommandLineContext(Context):
    """
    A command being handled on the command line.
    """

    def __init__(self, args, config):
        self.args = args
        self.config = config
        self._topic = ""

    async def send(self, message, file=None, **kw):
        print(message)
        if file is not None:
            print(f"Associated file can be found in {file}")

        return []

    @property
    def emoji_display(self):
        return self.args.display

    @property
    def arguments(self):
        return self.args.__dict__

    @property
    def user(self):
        return self.args.user

    @property
    def mention(self):
        at = "@"
        return f"{at}{self.args.user}"

    @property
    def user_byc_channel(self):
        return ""

    @property
    def game_id(self):
        return self.args.game_id

    @property
    def topic(self):
        return self._topic

    async def set_topic(self, topic, reason=None):
        self._topic = topic

class DiscordContext(Context):
    """
    A command being handled on Discord.
    """

    MESSAGE_LENGTH = 2000

    def __init__(self, client, message, config):
        self.client = client
        self.message = message
        if self.message.guild is None:
            self.config = config
        else:
            self.config = ServerConfig(config, self.message.guild.id)

    @property
    def typing(self):
        return self.message.channel.typing

    async def send(self, message, file=None, allowed_mentions=None,
                   channel=None, **kw):
        if channel is None or self.message.guild is None:
            channel = self.message.channel
        else:
            channel = self.message.guild.get_channel(channel)

        tasks = []
        while len(message) > self.MESSAGE_LENGTH:
            pos = message.rfind('\n', 0, self.MESSAGE_LENGTH - 1)
            if pos == -1:
                pos = self.MESSAGE_LENGTH - 1

            tasks.append(await channel.send(message[:pos],
                                            allowed_mentions=allowed_mentions))
            message = message[pos+1:]

        discord_file = discord.File(file) if file is not None else None
        tasks.append(await channel.send(message,
                                        allowed_mentions=allowed_mentions,
                                        file=discord_file,
                                        **kw))
        return tasks

    def _replace_role(self, message, role, seed, titles, players):
        # Optionally only replace roles belonging to BYC
        if not role.mentionable:
            return message

        if seed is None or role.name in seed["players"] or role.name in titles:
            message, subs = re.subn(rf"\b{role.name}\b(?!['-])",
                                    role.mention, message)
            if subs > 0:
                players.append(role)

        return message

    def _replace_user(self, message, user, guild, usernames):
        if "usernames" in self.config and username in self.config["usernames"]:
            member = guild.get_member(self.config["usernames"][user])
        else:
            member = guild.get_member_named(user)

        if member is not None:
            message, subs = re.subn(rf"\b{user}\b", member.mention, message)
            if subs > 0:
                usernames.append(member)

        return message

    def replace_roles(self, message, **kw):
        cards = kw.get("cards")
        seed = kw.get("seed")
        roles = kw.get("roles")
        users = kw.get("users")
        emoji = kw.get("emoji", True)
        deck = kw.get("deck", True)

        if cards and (emoji or deck):
            message = cards.replace_cards(message,
                                          display='discord' if emoji else '',
                                          deck=deck)

        guild = self.message.guild
        if guild is None:
            return message, discord.AllowedMentions.none()

        if roles is None:
            roles = guild.roles

        titles = cards.titles.keys() if cards else Cards.load().titles.keys()
        players = []
        usernames = []
        for role in roles:
            message = self._replace_role(message, role, seed, titles, players)

        if seed is not None and users:
            logging.info("Usernames to replace: %r", seed["usernames"])
            for user in seed["usernames"]:
                message = self._replace_user(message, user, guild, usernames)

        mentions = self.make_mentions(everyone=False, users=usernames,
                                      roles=players)
        return message, mentions

    def make_mentions(self, **kw):
        return discord.AllowedMentions(**kw)

    @property
    def emoji_display(self):
        return "discord"

    @property
    def prefix(self):
        return "!"

    @property
    def user(self):
        return self.message.author

    @property
    def mention(self):
        return self.message.author.mention

    @property
    def mentions(self):
        return self.message.mentions

    def get_user(self, username):
        if self.message.guild is None:
            return None

        return self.message.guild.get_member_named(username)

    def get_channel_mention(self, channel=None):
        if channel is None or self.message.guild is None:
            return self.message.channel.mention

        mentioned_channel = self.message.guild.get_channel(channel)
        if mentioned_channel is not None:
            return mentioned_channel.mention

        return channel

    @property
    def config_editable(self):
        if getattr(self.client, 'bsg_app_info', None) is None:
            return False

        user = self.user
        app_info = self.client.bsg_app_info
        if app_info.owner == user:
            return True
        if app_info.team is not None:
            return user in app_info.team.members

        return False

    @property
    def byc_enabled(self):
        guild = self.message.guild
        if guild is None:
            return False

        channel = self.message.channel
        user = self.client.user
        permissions = guild.get_member(user.id).permissions_in(channel)
        # Required permissions: Manage Roles, Manage Channels,
        # Manage Nicknames, View Channels, Send Messages, Manage Messages, 
        # Embed Links, Attach Files, Read Message History, Mention Everyone
        return permissions.is_superset(discord.Permissions(402910224))

    @property
    def user_byc_channel(self):
        if self.message.guild is None:
            return None

        private_channel = f"byc-{self.message.channel.name}-{self.message.author.name}"
        for other in self.message.guild.channels:
            if other.name == private_channel:
                return other.mention

        return None

    async def update_byc_channels(self, game_id, usernames=None, delete=False):
        guild = self.message.guild
        if guild is None or game_id == self.message.channel.id:
            channel = self.message.channel
        else:
            channel = guild.get_channel(game_id)

        private_channel_prefix = f"byc-{channel.name}-"
        if delete:
            await channel.edit(topic="", reason="Cleanup of BYC status")
            reason = f"Cleanup of BYC private channels for #{channel.name}"
            for other_channel in guild.channels:
                if other_channel.name.startswith(private_channel_prefix):
                    await other_channel.delete(reason=rason)

            return

        byc_category = None
        for category in guild.categories:
            if category.name == 'By Your Command':
                byc_category = category
                break

        if byc_category is None:
            byc_category = await guild.create_category('By Your Command')

        if not usernames:
            return

        topic = f"byc:{game_id}:{Dialog.EMPTY}:"
        for user in usernames:
            private_channel = f"{private_channel_prefix}{format_username(user)}"
            deny = discord.PermissionOverwrite(read_messages=False,
                                               send_messages=False)
            allow = discord.PermissionOverwrite(read_messages=True,
                                                send_messages=True)
            member = guild.get_member_named(user)
            if member is not None:
                overwrites = {
                    guild.default_role: deny,
                    member: allow,
                    guild.me: allow
                }
                await guild.create_text_channel(private_channel,
                                                overwrites=overwrites,
                                                category=byc_category,
                                                topic=topic)

    @property
    def game_id(self):
        return self.message.channel.id

    @property
    def roles(self):
        if self.message.guild is None:
            return []

        return self.message.guild.roles

    @property
    def topic(self):
        return self.message.channel.topic

    async def set_topic(self, topic, reason=None):
        self.message.channel.edit(topic=topic, reason=reason)

    async def replace_pins(self, messages, channel=None):
        if channel is None or self.message.guild is None:
            channel = self.message.channel
        else:
            channel = self.message.guild.get_channel(channel)

        pins = await channel.pins()
        for pin in pins:
            if pin.author == self.client.user:
                await pin.unpin()
        for new_message in new_messages:
            await new_message.pin()

    def get_color(self, color):
        return getattr(discord.Colour, color)()

    async def create_role(self, **kw):
        if self.message.guild is None:
            return None

        return await self.message.guild.create_role(**kw)
