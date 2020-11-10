from .base import Command

@Command.register("get", "key", description="Retrieve a configuration value.")
class GetCommand(Command):
    async def run(self, key="", **kw):
        if key not in self.context.config:
            await self.context.send(f"Unknown configuration key `{key}`.")
            return

        value = self.context.config[key]
        try:
            valid = self.context.config.validate(key, value)
        except TypeError:
            await self.context.send("The value of the configuration key "
                                    f"`{key}` cannot be shown.")
            return

        await self.context.send(f"The configuration key `{key}` has the value "
                                f"`{value}` ({'' if valid else 'not '}valid)")

@Command.register("set", "key", "value",
                  enabled=lambda context: context.config_editable,
                  description="Adjust a configuration value for this context.")
class SetCommand(Command):
    async def run(self, key="", value="", **kw):
        if key not in self.context.config:
            await self.context.send(f"Unknown configuration key `{key}`.")
            return

        try:
            valid = self.context.config.validate(key, value)
        except TypeError:
            await self.context.send("The provided value for the configuration "
                                    f"key `{key}` is not valid.")
            return

        self.context.config[key] = value
        self.context.config.sync()
        await self.context.send("Configuration has been updated successfully, "
                                f"the value of the configuration key `{key}` "
                                f"is now {value} for this context.")

@Command.register("reset", "key",
                  enabled=lambda context: context.config_editable,
                  description="Reset a configuration value to its default.")
class ResetCommand(Command):
    async def run(self, key="", **kw):
        if key not in self.context.config:
            await self.context.send(f"Unknown configuration key {key}.")
            return

        value = self.context.config[key]
        try:
            self.context.config.validate(key, value)
        except TypeError:
            await self.context.send("The value of the configuration key "
                                    f"`{key}` cannot be reset.")
            return

        try:
            del self.context.config[key]
        except KeyError:
            await self.context.send(f"The configuration key `{key}` did not "
                                    "have an overridden value.")
            return

        self.context.config.sync()
        await self.context.send("Configuration has been updated successfully, "
                                f"the value of the configuration key `{key}` "
                                f"has been reset to the default.")
