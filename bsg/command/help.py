"""
Help commands.
"""

from .base import Command

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
        extra_arguments = self.context.arguments
        lines = []
        for name, info in self.COMMANDS.items():
            group = info.get("group")
            if group is not None and group[0] != name:
                continue

            description = info.get("description", "")
            if callable(description):
                description = description(self.context)
            elif description == "":
                continue

            metavar = info.get("metavar")
            if metavar:
                name = f"<{metavar}>"

            command = f"**{self.context.prefix}{name}**"
            nargs = info.get("nargs")
            if nargs and info["arguments"]:
                nargs = nargs if isinstance(nargs, tuple) else []
                narg = info["arguments"][0]
                arguments = f"<{narg}...>"
                if len(info["arguments"]) > 1:
                    arguments += " " + \
                        " ".join(f"[{arg}]" for arg in info["arguments"][1:]
                                if arg in extra_arguments or arg in nargs)
            else:
                arguments = " ".join(f"<{arg}>" for arg in info["arguments"])

            if arguments != "":
                command = f"{command} {arguments}"
            if group is not None and not metavar:
                command += " (also " + ", ".join(
                    f"**{self.context.prefix}{other}**" for other in group[1:]
                ) + ")"
            lines.append(f"{command}: {description}")

        await self.context.send("\n".join(lines))
