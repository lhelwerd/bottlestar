"""
Bot commands.
"""

import asyncio
import logging

###

class Command:
    """
    Command interface.
    """

    COMMANDS = {}

    @classmethod
    def register(cls, name, *arguments, description=False):
        def decorator(subclass):
            cls.COMMANDS[name] = {
                "class": subclass,
                "arguments": arguments,
                "description": description
            }
            return subclass

        return decorator

    @classmethod
    def execute(cls, context, name, arguments):
        if name not in cls.COMMANDS:
            return False

        info = cls.COMMANDS[name]
        command = info["class"](context)
        keywords = dict(zip(info["arguments"], arguments))
        loop = asyncio.get_event_loop()
        try:
            loop.run_until_complete(command.run(**keywords))
        except:
            logging.exception("Command %s (called with %r)", name, arguments)
            loop.run_until_complete(context.send("Uh oh"))

        loop.close()
        return True

    def __init__(self, context):
        self.context = context

    async def run(self, **kw):
        raise NotImplementedError("Must be implemented by subclasses")

@Command.register("bot")
class BotCommand(Command):
    """
    Test command to say hello.
    """

    async def run(self, **kw):
        await self.context.send(f"Hello, {self.context.mention}!")

@Command.register("help")
class HelpCommand(Command):
    """
    Command to show all registered commands that have help messages.
    """

    async def run(self, **kw):
        lines = []
        for name, info in self.COMMANDS.items():
            if callable(info["description"]):
                description = ""
            elif info["description"]:
                description = info["description"]
            else:
                continue

            arguments = " ".join(f"<{arg}>" for arg in info["arguments"])
            lines.push(f"**{self.context.prefix}{name}** {arguments}: {description}")

        await self.context.send("\n".join(lines))
