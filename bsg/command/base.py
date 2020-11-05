"""
Base command interface.
"""

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
    def get_command(cls, context, name, arguments):
        if name not in cls.COMMANDS:
            raise KeyError(name)

        info = cls.COMMANDS[name]
        enabled = info.get("enabled", True)
        if not enabled or (callable(enabled) and not enabled(context)):
            raise KeyError(f"{name} is not enabled in this context")

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

        return command, keywords, info.get("slow")

    @classmethod
    async def execute(cls, context, name, arguments):
        try:
            command, keywords, slow = cls.get_command(context, name, arguments)
        except KeyError:
            return False

        try:
            if slow:
                await command.run_with_typing(**keywords)
            else:
                await command.run(**keywords)
        except:
            logging.exception("Command %s (called with %r)", name, arguments)
            await context.send("Uh oh")

        return True

    def __init__(self, name, context):
        self.name = name
        self.context = context

    async def run(self, **kw):
        raise NotImplementedError("Must be implemented by subclasses")

    async def run_with_typing(self, **kw):
        typing = self.context.typing
        if typing:
            async with typing():
                await self.run(**kw)
        else:
            await self.run(**kw)

