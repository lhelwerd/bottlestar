"""
Base command interface.
"""

import asyncio
from collections import OrderedDict
import logging

class Command:
    """
    Command interface.
    """

    COMMANDS = OrderedDict()

    @classmethod
    def register(cls, name, *arguments, **keywords):
        def decorator(subclass):
            info = keywords.copy()
            info.update({
                "class": subclass,
                "arguments": arguments
            })
            if isinstance(name, tuple):
                info["group"] = name
                commands = name
            else:
                commands = (name,)

            for command in commands:
                cls.COMMANDS[command] = info

            return subclass

        return decorator

    @classmethod
    def execute(cls, context, name, arguments):
        if name not in cls.COMMANDS:
            return False

        info = cls.COMMANDS[name]
        command = info["class"](name, context)

        if info.get("nargs"):
            arguments = (' '.join(arguments),)
            extra_arguments = {
                arg: value for arg, value in context.arguments.items()
                if arg in info["arguments"]
            }
        else:
            extra_arguments = {}

        keywords = dict(zip(info["arguments"], arguments))
        keywords.update(extra_arguments)

        loop = asyncio.get_event_loop()
        try:
            if info.get("slow"):
                loop.run_until_complete(command.run_with_typing(**keywords))
            else:
                loop.run_until_complete(command.run(**keywords))
        except:
            logging.exception("Command %s (called with %r)", name, arguments)
            loop.run_until_complete(context.send("Uh oh"))

        loop.close()
        return True

    def __init__(self, name, context):
        self.name = name
        self.context = context

    async def run(self, **kw):
        raise NotImplementedError("Must be implemented by subclasses")

    async def run_with_typing(self, **kw):
        typing = context.typing
        if typing:
            async with typing:
                await self.run(**kw)
        else:
            await self.run(**kw)

