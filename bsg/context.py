"""
Command context.
"""

class Context:
    """
    Context for a command.
    """

    async def send(self, message, **kw):
        """
        Send a message to the context.
        """

        raise NotImplementedError("Must be implemented by subclasses")

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

    def __init__(self, args):
        self.args = args

    async def send(self, message):
        print(message)

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

    def __init__(self, message):
        self.message = message

    async def send(self, message, allowed_mentions=None, **kw):
        channel = self.message.channel
        tasks = []
        while len(message) > self.MESSAGE_LENGTH:
            pos = message.rfind('\n', 0, self.MESSAGE_LENGTH - 1)
            if pos == -1:
                pos = self.MESSAGE_LENGTH - 1

            tasks.append(await channel.send(message[:pos],
                                            allowed_mentions=allowed_mentions))
            message = message[pos+1:]

        tasks.append(await channel.send(message,
                                        allowed_mentions=allowed_mentions,
                                        **kw))
        return tasks

    @property
    def prefix(self):
        return "!"

    @property
    def user(self):
        return self.message.author

    @property
    def mention(self):
        return self.message.author.mention
