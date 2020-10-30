"""
Command context.
"""

import logging
import re
import discord
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
    def prefix(self):
        """
        Return a string to place before commands when explaining how to run a
        command. If the bot only responds to certain prefixes, use the most
        commonly used one.
        """

        return ""

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

class CommandLineContext(Context):
    """
    A command being handled on the command line.
    """

    def __init__(self, args, config):
        self.args = args
        self.config = config

    async def send(self, message, file=None, **kw):
        print(message)
        if file is not None:
            print(f"Associated file can be found in {file}")

    @property
    def user(self):
        return self.args.user

    @property
    def mention(self):
        at = "@"
        return f"{at}{self.args.user}"

class DiscordContext(Context):
    """
    A command being handled on Discord.
    """

    MESSAGE_LENGTH = 2000

    def __init__(self, message, config):
        self.message = message
        if self.message.guild is None:
            self.config = config
        else:
            self.config = ServerConfig(config, self.message.guild.id)

    @property
    def typing(self):
        return self.message.channel.typing

    async def send(self, message, file=None, allowed_mentions=None, **kw):
        channel = self.message.channel
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
    def prefix(self):
        return "!"

    @property
    def user(self):
        return self.message.author

    @property
    def mention(self):
        return self.message.author.mention
