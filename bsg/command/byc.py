from contextlib import contextmanager
from datetime import datetime
from glob import glob
from itertools import chain, zip_longest
import logging
from os.path import getsize
from pathlib import Path
import re
import shutil
from .base import Command
from ..bbcode import BBCodeMarkdown
from ..byc import ByYourCommand, Dialog, ROLE_TEXT
from ..card import Cards
from ..image import Images
from ..search import Card, Location

class NonPublicCommandError(RuntimeError):
    pass

def format_private_channel(channel_name, user):
    return f"byc-{channel_name}-{format_username(user)}"

def format_username(user, replacement="-"):
    # Remove/replace spaces and other special characters (channel name-safe)
    return re.sub(r"\W+", replacement, user).strip(replacement)

def get_titles(key, title):
    keys = title.get("titles", [key])
    return [name if name[0].islower() else name.lower() for name in keys]

def has_titles(seed, titles, index):
    return index != -1 and all(seed.get(name, -1) == index for name in titles)

class BycCommand(Command):
    byc_games = {}

    def __init__(self, name, context):
        super().__init__(name, context)
        self.cards = Cards(self.context.config['cards_url'])
        self.images = Images(self.context.config['api_url'])
        self.bbcode = BBCodeMarkdown(self.images)
        self.game_state_path = None
        self.game_state = ""
        self.game_id = None

    @contextmanager
    def get_byc(self, keep=None):
        key = f"{self.game_id}-{self.context.user}"
        if key not in self.byc_games:
            byc = ByYourCommand(self.game_id, self.context.user,
                                self.context.config['script_url'])
            self.byc_games[key] = byc

        try:
            yield self.byc_games[key]
        finally:
            if keep is None or not keep():
                self.byc_games.pop(key, None)

    def format_button(self, button, text):
        if text == "Save and Quit":
            return f"**{self.context.prefix}commit**: {text}"

        if text.lower() == button:
            return f"**{self.context.prefix}{button}**"

        return f"**{self.context.prefix}{button}**: {text}"

    def update_banner(self, seed, banner_priority, index, meta):
        if "images" in meta and banner_priority[index] > meta["priority"]:
            banner = self.images.banner(meta["images"], seed["players"][index])
            if banner is not None:
                banner_priority[index] = meta["priority"]
                updated = seed["banners"][index] != banner
                seed["banners"][index] = banner
                return updated

        return False

    async def create_role(self, name, meta, class_name=None, mentionable=True):
        if class_name is None:
            class_name = name

        try:
            data = meta[class_name]
            color = self.context.get_color(data["color"])
        except (AttributeError, KeyError):
            logging.exception("Could not get class/title color for %s", name)
            color = self.context.get_color("default")

        return await self.context.create_role(name=name, colour=color,
                                              mentionable=mentionable)

    async def update_character_roles(self, roles, old_seed, seed):
        iterator = zip_longest(seed["usernames"], seed["players"],
                               old_seed.get("players", []))
        for username, character, old_character in iterator:
            if character is None:
                role = None
            elif character not in roles:
                # Search in cards what the class is and use metadata for color
                search = Card.search(using='main').source(['character_class']) \
                    .filter("term", deck="char").query("match", path=character)
                try:
                    card = search[:1].execute().hits[0]
                    class_name = card.character_class
                except IndexError:
                    logging.exception("Could not find character %s", character)
                    continue

                role = await self.create_role(character,
                                              self.cards.character_classes,
                                              class_name=class_name)
            else:
                role = roles[character]

            member = self.context.get_user(username)
            if member is not None:
                if role is not None:
                    await member.add_roles(role)
                if old_character is not None and \
                    old_character != character and old_character in roles:
                    await member.remove_roles(roles[old_character])

    async def update_title_roles(self, roles, old_seed, seed, banner_priority):
        updated = False
        for key, title in self.cards.titles.items():
            titles = get_titles(key, title)
            old_index = old_seed.get(titles[0], -1)
            index = seed.get(titles[0], -1)
            role = roles.get(key)
            if has_titles(seed, titles, index):
                if self.update_banner(seed, banner_priority, index, title):
                    updated = True

                if role is None:
                    role = await self.create_role(key, self.cards.titles)
                user = seed["usernames"][index]
                member = self.context.get_user(user)
                if member is not None and role is not None:
                    await member.add_roles(role)

            if role is not None and \
                has_titles(old_seed, titles, old_index) and \
                not has_titles(seed, titles, old_index):
                if self.update_banner(seed, banner_priority, old_index,
                                      self.cards.loyalty["Human"]):
                    updated = True

                old_user = seed["usernames"][old_index]
                old_member = self.context.get_user(old_user)
                if old_member is not None:
                    await old_member.remove_roles(role)

        return updated

    async def update_loyalty_roles(self, roles, old_seed, seed, banner_priority):
        updated = False
        iterator = enumerate(zip(seed["revealedCylons"], seed["usernames"]))
        for index, (cylon, user) in iterator:
            loyalty = "Cylon" if cylon else "Human"
            if self.update_banner(seed, banner_priority, index,
                                  self.cards.loyalty[loyalty]):
                updated = True
            if cylon:
                role = roles.get(loyalty)
                if role is None:
                    role = await self.create_role(loyalty, self.cards.loyalty,
                                                  mentionable=False)
                member = self.get_user(user)
                if member is not None and role is not None:
                    await member.add_roles(role)

        return updated

    async def update_channel(self, dialog, choices):
        if not choices and self.context.game_id == self.game_id and \
            self.context.user_byc_channel != "":
            topic = "By Your Command game"
        else:
            topic = f"byc:{self.game_id}:{dialog}:{':'.join(choices)}"

        await self.context.set_topic(topic)

    async def run(self, **kw):
        logging.info('%s: %s %r', self.context.user, self.name, kw)
        if not self.context.byc_enabled:
            await self.context.send("BYC is not enabled: Ensure that this is "
                                    "a valid server and that the bot has the "
                                    "necessary permissions :robot:")
            return

        self.game_id = self.context.game_id
        topic = self.context.topic
        logging.info('%d %s', self.game_id, topic)
        if topic is not None and topic.startswith("byc:"):
            parts = topic.split(":")
            self.game_id = int(parts[1])
            num_buttons = int(parts[2])
            options = Dialog.decode_options(parts[3])
            has_input = bool(parts[4])
            choices = [choice for choice in parts[5:] if choice != ""]
        else:
            num_buttons = 0
            options = {}
            has_input = False
            choices = []

        logging.info("%d %d %r %r %r", self.game_id, num_buttons, options, has_input, choices)

        self.game_state_path = Path(f"game/game-{self.game_id}.txt")
        game_state = "Starting a new BYC game...\n"
        self.initial_setup = False
        is_main_channel = self.context.game_id == self.game_id
        user_channel = self.context.user_byc_channel
        if not await self.check_game_state(game_state):
            if not self.initial_setup:
                return
        elif is_main_channel:
            # Playing in the main context (publicly)
            try:
                if not await self.check_public_command(choices, **kw):
                    return
            except NonPublicCommandError:
                user_channel = self.context.user_byc_channel
                if user_channel == "":
                    # Some contexts might not have different channels.
                    logging.info("Allowing BYC actions in public context.")
                elif channel is not None:
                    reply = (f"{self.context.mention} Perform this BYC action "
                             f"in your own, private channel: {user_channel}")
                    await self.context.send(reply)
                    return
                else:
                    reply = ("A BYC game is currently underway in this channel "
                             "and you do not seem to be a part of this game. "
                             "To start a new game, use another channel and "
                             "type **{self.context.prefix}byc** there.")
                    await self.context.send(reply)
                    return
        else:
            # Playing privately
            example = await self.check_private_command(**kw)
            if example:
                mention = self.context.get_channel_mention(self.game_id)
                await self.context.send(f"Please use the command {example} "
                                        "from within the public BYC game "
                                        f"channel, {mention}.")
                return

        force = await self.check_command(choices, options, num_buttons,
                                         has_input, **kw)
        if force == False:
            return

        # Now do the actual BYC execution
        query = False
        with self.get_byc(keep=lambda: query) as byc:
            if not self.initial_setup:
                # Try to avoid reading files all the time and use the browser's
                # current game state instead
                try:
                    game_state = byc.retrieve_game_state(force=force)
                except ValueError:
                    with self.game_state_path.open('r') as game_state_file:
                        game_state = game_state_file.read()

            run = True
            while run:
                dialog = byc.run_page(choices[2:] if self.initial_setup else choices,
                                      game_state, force=force)

                # Check if we got another dialog
                query = isinstance(dialog, Dialog)
                if query:
                    # Store choices into the topic, adjust channel topic
                    await self.update_channel(dialog, choices)
                    if await self.auto_select(dialog, choices):
                        continue

                    reply, run = self.get_dialog(dialog, choices)
                    await self.context.send(reply)
                else:
                    # Clear private channel choices when done
                    if not is_main_channel or user_channel == "":
                        await self.update_channel(Dialog.EMPTY, [])

                    # Update based on game state
                    await self.public_result(byc, game_state=dialog,
                                             old_game_state=game_state)

                    run = False

    async def check_game_state(self, game_state):
        """
        Check if a local state for this game exists yet.
        The `game_state_path` member variable refers to a nonexistent file, and
        thus we cannot retrieve the current game state. Most commands would
        not be able to perform anything in this case.
        """

        if self.game_state_path.exists():
            return True

        await self.context.send("There is no active BYC game in this channel. "
                                "You can start a new game using "
                                f"**{self.context.prefix}byc**.")
        return False

    async def check_public_command(self, choices, **kw):
        """
        Check if this command can be executed publicly like this, and 
        possibly handle the command completely if it requires no actual BYC 
        script execution.

        Returns `True` if the command should continue handling, `False` if all
        actions are taken here, or raises a `NonPublicCommandError` if the
        command is not supposed to be used in the public context this way.
        """

        if len(choices) >= 2 and choices[0] == "byc":
            if choices[1] != format_username(self.context.user):
                member = self.context.get_user(choices[1])
                mention = member.mention if member is not None else choices[1]
                await self.context.send("The game is currently being set up. "
                                        f"Only {mention} is able to interact "
                                        "with the dialogs.")
                return False

            self.initial_setup = True
            return True

        # Unless overridden, do not allow BYC commands in the main channel 
        # outside of the initial setup.
        raise NonPublicCommandError

    async def check_private_command(self, **kw):
        """
        Check if this command can be executed privately like this.
        Returns a string containing the marked-up command name indicating how
        the command should be used in a public context, or the empty string
        if the command can be executed just fine.
        """

        return ""

    async def check_command(self, choices, options, num_buttons, input, **kw):
        """
        Check if the command arguments are proper.

        This method must be overridden by subclasses unless all the actions
        are handled in `check_public_command` and `check_private_command`.
        This method may optionally handle all actions related to this command
        or adjust the choices to be processed in the BYC script.

        Returns `None` if the command should continue processing, `True` if the
        BYC page should be fully reloaded before processing or `False` if all
        actions are taken here.
        """

        logging.warning("%s: Subclass must implement check_command", self.name)
        return False

    async def add_choice(self, choices, options, num_buttons, input, choice):
        if choice in options:
            choices.append(f"\b{options[choice] + 1}")
        elif input:
            mentions = self.context.mentions
            if self.initial_setup and len(mentions) == 1:
                choices.append(mentions[0].name)
            else:
                choices.append(choice)
        elif choice.isnumeric() and 0 < int(choice) <= num_buttons:
            choices.append(f"\b{choice}")
        else:
            await self.context.send("Option not known. Correct your command usage.")
            return False

        return None

    async def auto_select(self, dialog, choices):
        """
        Perform automatic choices based on the dialog. Return `True` to
        immediately handle the choices and not display any other options to
        the user.

        This was useful for example when the "Show Hand Report" menu gave
        options to post in a spoiler, which we could deny during normal
        gameplay. Certain commands may still use this to move through menus to
        their desired option (which may be safer than defining all the choices
        beforehand).
        """

        return False

    def has_dialog_options(self, dialog):
        return len(dialog.buttons) > 1 or dialog.input

    def get_dialog_options(self, dialog):
        buttons = ["cancel", "ok"]
        options = ', '.join([
            self.format_button(buttons[index], text)
            for index, text in enumerate(dialog.buttons)
            if not dialog.input or buttons[index] != "ok"
        ])
        if dialog.input:
            sample = "input" if self.initial_setup else "number"
            options += f', **{self.context.prefix}choose** <{sample}>'
        return options

    def get_dialog(self, dialog, choices):
        reply = self.cards.replace_cards(dialog.msg, deck=False,
                                         display=self.context.emoji_display)
        run = True
        if "Save and Quit" in dialog.options:
            reply = reply \
                .replace("Print Hand Report",
                         f"Show Hand Report (**{self.context.prefix}hand**)") \
                .replace("Display Game State",
                         f"Post Game State (**{self.context.prefix}state**)")

        if self.has_dialog_options(dialog):
            options = self.get_dialog_options(dialog)

            reply += f"\nOptions: {options}"
            run = False
        else:
            choices.append("\b1")

        return reply, run

    async def public_result(self, byc, game_state="", old_game_state=""):
        seed = byc.get_game_seed(game_state)
        users = self.initial_setup
        updated = False
        old_seed = {}
        role_texts = {}
        roles = {}
        priority = [float('inf')] * len(seed["usernames"])
        for role_group, texts in ROLE_TEXT.items():
            role_texts[role_group] = any(text in game_state for text in texts)
            if role_texts[role_group] and old_seed is None:
                old_seed = byc.get_game_seed(old_game_state)
                roles = {role.name: role for role in self.context.roles}

        if role_texts["character"]:
            users = True
            await self.update_character_roles(roles, old_seed, seed)
        if role_texts["title"]:
            if await self.update_title_roles(roles, old_seed, seed, priority):
                updated = True
        if role_texts["loyalty"]:
            if await self.update_loyalty_roles(roles, old_seed, seed, priority):
                updated = True

        if self.initial_setup:
            usernames = [format_username(user) for user in seed["usernames"]]
            await self.context.update_byc_channels(self.game_id, usernames)

        if any(style != 1 for style in seed.get("promptStyle", [])):
            seed["promptStyle"] = [1] * len(seed["players"])
            updated = True
        if updated:
            game_state = byc.set_game_seed(game_state, seed)

        if self.game_state_path is not None:
            if "round" in seed:
                backup = f'game/game-{self.game_id}-{seed["round"]}-{seed["turn"]}-{datetime.now()}-{format_username(byc.user, "_")}.txt'
                shutil.copy(str(self.game_state_path), backup)

            with self.game_state_path.open('w') as game_state_file:
                game_state_file.write(game_state)

        # Process the game state (BBCode -> Markdown and HTML game state)
        game_state_markdown = self.bbcode.process_bbcode(game_state)
        message, mentions = self.context.replace_roles(game_state_markdown,
                                                       cards=self.cards,
                                                       seed=seed, users=users,
                                                       deck=False)

        if self.bbcode.game_state != "":
            image = byc.save_game_state_screenshot(self.images,
                                                   self.bbcode.game_state)
        else:
            image = None

        new_messages = await self.context.send(message, channel=self.game_id,
                                               allowed_mentions=mentions,
                                               file=image)

        # Pin the message if it has a screenshot - unpin others
        if image is not None and new_messages:
            await self.context.replace_pins(new_messages, channel=self.game_id)

@Command.register("byc", slow=True,
                  description="Start a BYC game or a series of BYC actions")
class StartCommand(BycCommand):
    async def check_game_state(self, game_state):
        if self.game_state_path.exists() and getsize(self.game_state_path) > 0:
            return True

        self.game_state_path.touch()
        await self.context.send(f"{game_state}Only {self.context.mention} "
                                "will be able to answer the following dialogs.")
        self.initial_setup = True
        return False

    async def check_command(self, choices, options, num_buttons, input, **kw):
        if self.initial_setup:
            choices[:] = ["byc", format_username(self.context.user)]
            return None

        choices.clear()
        return True

@Command.register("ok", slow=True,
                  description="Confirm performing a BYC action")
class OkCommand(BycCommand):
    async def check_command(self, choices, options, num_buttons, input, **kw):
        return await self.add_choice(choices, options, num_buttons, input, "ok")

@Command.register("cancel", slow=True,
                  description="Reject performing a BYC action")
class CancelCommand(BycCommand):
    async def check_command(self, choices, options, num_buttons, input, **kw):
        if "Save and Quit" in options:
            await self.context.send("Canceling would make your actions public. "
                                    "If this is what you want here, then use "
                                    f"**{self.context.prefix}commit**.")
            return False

        return await self.add_choice(choices, options, num_buttons, input,
                                     "cancel")

@Command.register("choose", "choice", nargs=True, slow=True,
                  description="Select a numeric value or input text")
class ChooseCommand(BycCommand):
    async def check_command(self, choices, options, num_buttons, input,
                            choice="", **kw):
        return await self.add_choice(choices, options, num_buttons, input,
                                     choice)

@Command.register("commit", slow=True,
                  description="Show result of series of BYC actions in public")
class CommitCommand(BycCommand):
    async def check_command(self, choices, options, num_buttons, input, **kw):
        return await self.add_choice(choices, options, num_buttons, input,
                                     "cancel")

@Command.register("state", slow=True,
                  description="Display game state in public")
class StateCommand(BycCommand):
    async def check_public_command(self, choices, **kw):
        return True

    async def check_command(self, choices, options, num_buttons, input, **kw):
        if self.context.game_id == self.game_id and not self.initial_setup:
            # Main channel (but cannot use .state during setup)
            choices[:] = ["2", "\b2", "\b1"]
            return True

        if choices and "Save and Quit" not in options:
            await self.context.send("Showing game state is only possible when "
                                    "you are in the main dialog.")
            return False

        choices.append("2")
        return None

    async def update_channel(self, dialog, choices):
        # TODO: Test if we can just override this always or if we only can do 
        # so when dialog == Dialog.EMPTY (go back to super().update_channel 
        # otherwise). Maybe this total override causes BYC/choice-topic desync 
        # when using .state while in a chain already?
        pass

    async def auto_select(self, dialog, choices):
        if len(dialog.buttons) == 2 and not dialog.input:
            await self.context.send(dialog.msg)
            choices.append("\b2")
            return True

        return False

    def get_dialog(self, dialog, choices, initial_setup):
        reply = (f"Options: **{self.context.prefix}commit**: Save and Quit, "
                 f"**{self.context.prefix}undo 2**, "
                 f"**{self.context.prefix}reset**")
        return reply, False

@Command.register("hand", slow=True, description="Display hand in private")
class HandCommand(BycCommand):
    async def check_command(self, choices, options, num_buttons, input, **kw):
        if choices and "Save and Quit" not in options:
            await self.context.send("Showing hand report is only possible when "
                                    "you are in the main dialog.")
            return False

        choices.append("1")
        return None

class BackupCommand(BycCommand):
    """
    Abstract undo/redo command.
    """

    def format_undo_option(self, data, timestamp):
        if data == {}:
            return 'Current game state'

        if "user" in data:
            member = self.context.get_user(data["user"])
            mention = member.mention if member is not None else data["user"]
        else:
            mention = "an unknown user"

        date = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        if "undo" in data:
            return (f'Undone game state that went {data["undo"]} steps back at '
                    f'{date} triggered by {mention}')

        return f'Turn {data["round"]}.{data["turn"]+1} at {date} posted by {mention}'

    def get_undo_data(self, files, timestamps, index, game_seed):
        if index >= len(timestamps) - 1:
            return game_seed

        return files[timestamps[index + 1]]

    async def undo_backup(self, step):
        files = {}
        game_seed = {}
        for path in glob(f"game/game-{self.game_id}-*.txt"):
            parts = path.split('-')
            timestamp = datetime.strptime('-'.join(parts[4:-1]),
                                          '%Y-%m-%d %H:%M:%S.%f')
            files[timestamp] = {
                "path": Path(path),
                "user": parts[-1][:-len(".txt")]
            }
            if parts[2].isnumeric():
                files[timestamp].update({
                    "round": int(parts[2]),
                    "turn": int(parts[3]),
                })
            else:
                files[timestamp]["undo"] = int(parts[3])

        timestamps = sorted(files.keys())[-10:]
        if step.isnumeric() and 0 <= int(step) < len(timestamps) and \
            (int(step) != 0 or "undo" in files[0]):
            index = len(timestamps) - int(step) - 1
            path = files[timestamps[index]]["path"]
            data = self.get_undo_data(files, timestamps, index, game_seed)
            backup = f"game/game-{self.game_id}-undo-{step}-{datetime.now()}-{format_username(user, '_')}.txt"
            shutil.copy(str(self.game_state_path), backup)
            if path != self.game_state_path:
                shutil.copy(str(path), str(self.game_state_path))
                path.unlink()

            if int(step) == 0:
                label = "to the latest undone game state: "
            else:
                label = f"{step} game states to "
            label += self.format_undo_option(data, timestamp)
            await channel.send(f'Going back {label}...')
            with self.game_state_path.open('r') as game_state_file:
                game_state = game_state_file.read()
                with self.get_byc() as byc:
                    await self.public_result(byc, game_state=game_state)

            return

        # Display options, including latest game seed data
        with self.game_state_path.open('r') as game_state_file:
            game_state = game_state_file.read()
            with self.get_byc() as byc:
                game_seed = byc.get_game_seed(game_state)

            match = re.match(r'\[q="([^"]*)"\]', game_state)
            if match:
                game_seed["user"] = match.group(1)

        msg = ""
        for index, timestamp in enumerate(timestamps):
            data = self.get_undo_data(files, timestamps, index, game_seed)
            if index == len(timestamps) - 1:
                msg += '\nCurrent game state: '
            else:
                msg += f'\n{len(timestamps) - index - 1}. '
            msg += self.format_undo_option(data, timestamp)

        await self.context.send("Pick a state to undo to with "
                                f"**{self.context.prefix}undo <number>**:{msg}")

@Command.register("undo", "step", slow=True,
                  description="Go back step(s) in the BYC actions/states (expensive)")
class UndoCommand(BackupCommand):
    async def check_public_command(self, choices, step="", **kw):
        await self.undo_backup(step)
        return False

    async def check_command(self, choices, options, num_buttons, input, step="",
                            **kw):
        try:
            count = int(step)
        except ValueError:
            count = 1

        await self.context.send(f"Undoing last {count} choice(s)...")
        del choices[-count:]
        return True

    def has_dialog_options(self, dialog):
        # Always show dialog after undo; do not do the step immediately again
        return True

    def get_dialog_options(self, dialog):
        options = super().get_dialog_options(dialog)
        return f"{options}, **{self.context.prefix}undo**"

@Command.register("redo", slow=True,
                  description="Perform a series of BYC actions/states again, "
                              "for bot restarts (expensive) or incorrect moves")
class RedoCommand(BackupCommand):
    async def check_public_command(self, choices, step="", **kw):
        await self.undo_backup("0")
        return False

    async def check_command(self, choices, options, num_buttons, input, step="",
                            **kw):
        await self.context.send("Redoing choices...")
        return True

@Command.register("reset", slow=True,
                  description="Go to the start of the series of BYC actions")
class ResetCommand(BycCommand):
    async def check_command(self, choices, options, num_buttons, input, step="",
                            **kw):
        await self.context.send("Reverting to the state when you last used "
                                f"**{self.context.prefix}byc**...")
        choices.clear()
        return True

@Command.register("cleanup", "channel", slow=True,
                  description="Delete data related to the current BYC game")
class CleanupCommand(BycCommand):
    async def check_public_command(self, choices, channel="", **kw):
        prefix = self.context.prefix
        mention = self.context.get_channel_mention()
        if channel != mention:
            await self.context.send("Please confirm permanent deletion of the "
                                    "BYC game in this channel by typing "
                                    f"**{prefix}cleanup {mention}**.")
            return False

        await self.cleanup()
        await self.context.send("All items related to the BYC game deleted.")
        return False

    async def check_private_command(self, channel="", **kw):
        if channel == "":
            channel = "#main_channel"

        return "**{self.context.prefix}cleanup {channel}**"

    async def cleanup(self):
        # Cleanup channels
        self.context.update_byc_channels(self.game_id, delete=True)

        # Cleanup roles of users involved in the game
        with self.game_state_path.open('r') as game_state_file:
            game_state = game_state_file.read()
            with self.get_byc() as byc:
                game_seed = byc.get_game_seed(game_state)

        roles = {role.name: role for role in self.context.roles}
        empty_game_seed = game_seed.copy()
        empty_game_seed["players"] = []
        for key, title in self.cards.titles.items():
            empty_game_seed.update({
                field: -1 for field in get_titles(key, title)
            })

        banner_priority = [float('inf')] * len(game_seed["usernames"])
        await self.update_character_roles(roles, game_seed, empty_game_seed)
        await self.update_title_roles(roles, game_seed, empty_game_seed,
                                      banner_priority)
        if "Cylon" in roles:
            for user in game_seed["usernames"]:
                member = self.context.get_user(user)
                if member is not None:
                    await member.remove_roles(roles["Cylon"])

        # Cleanup game states and HTML pages/screenshots
        self.game_state_path.unlink()
        for path in glob(f"game/game-{self.game_id}-*.txt"):
            Path(path).unlink()
        for path in glob(f"game/game-state-{self.game_id}-*"):
            Path(path).unlink()
        for path in glob(f"game/page-{self.game_id}-*.html"):
            Path(path).unlink()

@Command.register("refresh", slow=True,
                  description="Perform updates for the current BYC game (role positions)")
class RefreshCommand(BycCommand):
    async def check_public_command(self, choices, **kw):
        await self.sort_roles()
        await self.context.send("Roles have been repositioned.")
        return False

    async def check_private_command(self, **kw):
        return f"**{self.context.prefix}{self.name}"

    async def sort_roles(self):
        roles = {role.name: role for role in self.context.roles}
        iterator = chain(self.cards.character_classes.items(),
                         self.cards.titles.items(),
                         self.cards.loyalty.items())
        priorities = {
            name: title.get("priority", 99) for name, title in iterator
        }
        search = Card.search(using='main').source(['path']) \
            .filter("term", deck="char")
        priorities.update({char.path: 99 for char in search.scan()})
        sorted_roles = sorted(roles.items(),
                              key=lambda item: priorities.get(item[0], -1))
        logging.info('%r', sorted_roles)
        for i, (name, role) in enumerate(reversed(sorted_roles)):
            if name in priorities:
                await role.edit(position=i + 1)
