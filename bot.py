import argparse
from contextlib import contextmanager
from datetime import datetime
from glob import glob
from itertools import chain, zip_longest
import logging
from pathlib import Path, PurePath
import re
import shutil
import discord
import yaml
from elasticsearch_dsl.connections import connections
from bsg.bbcode import BBCodeMarkdown
from bsg.byc import ByYourCommand, Dialog
from bsg.card import Cards
from bsg.image import Images
from bsg.search import Card, Location
from bsg.thread import Thread

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s',
                        level=getattr(logging, args.log, None))

with open("config.yml") as config_file:
    config = yaml.safe_load(config_file)

client = discord.Client()
cards = Cards(config['cards_url'])
images = Images(config['api_url'])
bbcode = BBCodeMarkdown(images)
thread = Thread(config['api_url'])
connections.create_connection(alias='main',
                              hosts=[config['elasticsearch_host']])
byc_games = {}
byc_commands = {
    "byc": "Start a BYC game or a series of actions",
    "ok": "Confirm performing an action",
    "cancel": "Reject perform an action",
    "choose": ("input", "Select a numeric value or input text (during setup)"),
    "commit": "Show result of series of actions in public",
    "state": "Display game state in public (must **!commit** afterward)",
    "hand": "Display hand in private",
    "undo": ("step", "Go back step(s) in the actions/states (expensive)"),
    "redo": "Perform the series of actions again (expensive), for bot restarts",
    "reset": "Go back to the start of the series of actions (like **!byc**)",
    "cleanup": ("channel", "Delete all items related to the current game"),
    "refresh": "Perform updates for the current game (role positions)"
}
byc_role_text = {
    "character": (" chooses to play ", " returns as ", " pick a new character"),
    "title": (" is now the ", " the Mutineer.", " receives the Mutineer card "),
    "loyalty": (" reveals ", " becomes a Cylon.", " is a [color=red]Cylon[/color]!")
}

async def send_message(channel, message, allowed_mentions=None, **kwargs):
    messages = []
    while len(message) > 2000:
        pos = message.rfind('\n', 0, 2000 - 1)
        messages.append(await channel.send(message[:pos],
                                           allowed_mentions=allowed_mentions))
        message = message[pos+1:]

    messages.append(await channel.send(message,
                                       allowed_mentions=allowed_mentions,
                                       **kwargs))
    return messages

def replace_roles(message, guild=None, seed=None, roles=None, users=None,
                  emoji=True, deck=True):
    if emoji or deck:
        message = cards.replace_cards(message,
                                      display='discord' if emoji else '',
                                      deck=deck)

    if guild is None:
        none = discord.AllowedMentions(everyone=False, users=False, roles=False)
        return message, none
    if roles is None:
        roles = guild.roles

    titles = cards.titles.keys()
    players = []
    usernames = []
    for role in roles:
        # Optionally only replace roles belonging to BYC
        if not role.mentionable:
            continue
        if seed is None or role.name in seed["players"] or role.name in titles:
            message, subs = re.subn(rf"\b{role.name}\b(?!['-])", role.mention,
                                    message)
            if subs > 0:
                players.append(role)

    if seed is not None and users:
        logging.info("Usernames to replace: %r", seed["usernames"])
        for username in seed["usernames"]:
            if "usernames" in config and username in config["usernames"]:
                member = guild.get_member(config["usernames"][username])
            else:
                member = guild.get_member_named(username)

            if member is not None:
                message, subs = re.subn(rf"\b{username}\b", member.mention,
                                        message)
                if subs > 0:
                    usernames.append(member)

    mentions = discord.AllowedMentions(everyone=False, users=usernames,
                                       roles=players)
    return message, mentions

@client.event
async def on_ready():
    logging.info('We have logged in as %s', client.user)
    for guild in client.guilds:
        logging.info('Server: %s #%d', guild.name, guild.id)
        for channel in guild.channels:
            logging.info('Channel: %s #%d', channel.name, channel.id)
        for role in guild.roles:
            if role.mentionable:
                logging.info('Role: %s (#%d)', role.name, role.position)

def format_private_channel(channel_name, user):
    return f"byc-{channel_name}-{format_username(user)}"

def format_username(user, replacement="-"):
    # Remove/replace spaces and other special characters (channel name-safe)
    return re.sub(r"\W+", replacement, user).strip(replacement)

async def byc_cleanup(guild, channel, game_id, user, game_state_path):
    # Cleanup channels
    await channel.edit(topic="", reason="Cleanup of BYC status")
    private_channel_prefix = f"byc-{channel.name}-"
    for other_channel in guild.channels:
        if other_channel.name.startswith(private_channel_prefix):
            await channel.delete(reason="Cleanup of private channels for BYC")

    # Cleanup roles of users involved in the game
    with game_state_path.open('r') as game_state_file:
        game_state = game_state_file.read()
        with get_byc(game_id, user) as byc:
            game_seed = byc.get_game_seed(game_state)

    roles = {role.name: role for role in guild.roles}
    empty_game_seed = game_seed.copy()
    empty_game_seed["players"] = []
    for key, title in cards.titles.items():
        empty_game_seed.update({field: -1 for field in get_titles(key, title)})

    banner_priority = [float('inf')] * len(game_seed["usernames"])
    await update_character_roles(guild, roles, game_seed, empty_game_seed)
    await update_title_roles(guild, roles, game_seed, empty_game_seed,
                             banner_priority)
    if "Cylon" in roles:
        for user in game_seed["usernames"]:
            member = guild.get_member_named(user)
            if member is not None:
                await member.remove_roles(roles["Cylon"])

    # Cleanup game states and HTML pages/screenshots
    game_state_path.unlink()
    for path in glob(f"game/game-{game_id}-*.txt"):
        Path(path).unlink()
    for path in glob(f"game/game-state-{game_id}-*"):
        Path(path).unlink()
    for path in glob(f"game/page-{game_id}-*.html"):
        Path(path).unlink()

async def create_role(guild, name, metadata, class_name=None, mentionable=True):
    if class_name is None:
        class_name = name

    try:
        data = metadata[class_name]
        color = getattr(discord.Colour, data["color"])()
    except (AttributeError, KeyError):
        logging.exception("Could not get class/title color for %s", name)
        color = discord.Colour.default()

    return await guild.create_role(name=name, colour=color,
                                   mentionable=mentionable)

async def update_character_roles(guild, roles, old_seed, seed):
    iterator = zip_longest(seed["usernames"], seed["players"],
                           old_seed.get("players"))
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

            role = await create_role(guild, character, cards.character_classes,
                                     class_name=class_name)
        else:
            role = roles[character]

        member = guild.get_member_named(username)
        if member is not None:
            if role is not None:
                await member.add_roles(role)
            if old_character is not None and old_character != character and \
                old_character in roles:
                await member.remove_roles(roles[old_character])

def get_titles(key, title):
    keys = title.get("titles", [key])
    return [name if name[0].islower() else name.lower() for name in keys]

def has_titles(seed, titles, index):
    return index != -1 and all(seed.get(name, -1) == index for name in titles)

def update_banner(seed, banner_priority, index, metadata):
    if "images" in metadata and banner_priority[index] > metadata["priority"]:
        banner = images.banner(metadata["images"], seed["players"][index])
        if banner is not None:
            banner_priority[index] = metadata["priority"]
            updated = seed["banners"][index] != banner
            seed["banners"][index] = banner
            return updated

    return False

async def update_title_roles(guild, roles, old_seed, seed, banner_priority):
    updated = False
    for key, title in cards.titles.items():
        titles = get_titles(key, title)
        old_index = old_seed.get(titles[0], -1)
        index = seed.get(titles[0], -1)
        role = roles.get(key)
        if has_titles(seed, titles, index):
            if update_banner(seed, banner_priority, index, title):
                updated = True

            if role is None:
                role = await create_role(guild, key, cards.titles)
            user = seed["usernames"][index]
            member = guild.get_member_named(user)
            if member is not None:
                await member.add_roles(role)

        if role is not None and has_titles(old_seed, titles, old_index) and \
            not has_titles(seed, titles, old_index):
            if update_banner(seed, banner_priority, old_index,
                             cards.loyalty["Human"]):
                updated = True

            old_user = seed["usernames"][old_index]
            old_member = guild.get_member_named(old_user)
            if old_member is not None:
                await old_member.remove_roles(role)

    return updated

async def update_loyalty_roles(guild, roles, old_seed, seed, banner_priority):
    updated = False
    iterator = enumerate(zip(seed["revealedCylons"], seed["usernames"]))
    for index, (cylon, user) in iterator:
        loyalty = "Cylon" if cylon else "Human"
        if update_banner(seed, banner_priority, index, cards.loyalty[loyalty]):
            updated = True
        if cylon:
            role = roles.get(loyalty)
            if role is None:
                role = await create_role(guild, loyalty, cards.loyalty,
                                         mentionable=False)
            member = guild.get_member_named(user)
            if member is not None:
                await member.add_roles(role)

    return updated

async def sort_roles(guild):
    roles = {role.name: role for role in guild.roles}
    iterator = chain(cards.character_classes.items(),
                     cards.titles.items(), cards.loyalty.items())
    priorities = {name: title.get("priority", 99) for name, title in iterator}
    search = Card.search(using='main').source(['path']) \
        .filter("term", deck="char")
    priorities.update({char.path: 99 for char in search.scan()})
    sorted_roles = sorted(roles.items(),
                          key=lambda item: priorities.get(item[0], -1))
    logging.info('%r', sorted_roles)
    for i, (name, role) in enumerate(reversed(sorted_roles)):
        if name in priorities:
            await role.edit(position=i + 1)

async def update_channel(channel, game_id, dialog, choices):
    if not choices and channel.id == game_id:
        topic = "By Your Command game"
    else:
        topic = f"byc:{game_id}:{dialog}:{':'.join(choices)}"

    await channel.edit(topic=topic)

async def update_channels(guild, channel, game_id, seed):
    byc_category = None
    for category in guild.categories:
        if category.name == 'By Your Command':
            byc_category = category
            break

    if byc_category is None:
        byc_category = await guild.create_category('By Your Command')

    for user in seed["usernames"]:
        private_channel = f"byc-{channel.name}-{format_username(user)}"
        deny = discord.PermissionOverwrite(read_messages=False,
                                           send_messages=False)
        allow = discord.PermissionOverwrite(read_messages=True,
                                            send_messages=True)
        member = guild.get_member_named(user)
        if member is not None:
            await guild.create_text_channel(private_channel, overwrites={
                guild.default_role: deny,
                member: allow,
                guild.me: allow
            }, category=byc_category, topic=f"byc:{game_id}:{Dialog.EMPTY}:")

def format_button(button, text):
    if text == "Save and Quit":
        return f"**!commit**: {text}"

    if text.lower() == button:
        return f"**!{button}**"

    return f"**!{button}**: {text}"

def is_byc_enabled(guild, channel):
    if guild is None:
        return False

    permissions = guild.get_member(client.user.id).permissions_in(channel)
    return permissions.is_superset(discord.Permissions(402910224))

@contextmanager
def get_byc(game_id, user, keep=None):
    key = f"{game_id}-{user}"
    if key not in byc_games:
        byc_games[key] = ByYourCommand(game_id, user, config['script_url'])

    try:
        yield byc_games[key]
    finally:
        if keep is None or not keep():
            byc_games.pop(key, None)

def format_undo_option(guild, data, timestamp):
    if data == {}:
        return 'Current game state'

    if "user" in data:
        member = guild.get_member_named(data["user"])
        mention = member.mention if member is not None else data["user"]
    else:
        mention = "an unknown user"

    date = timestamp.strftime("%Y-%m-%d %H:%M:%S")
    if "undo" in data:
        return (f'Undone game state that went {data["undo"]} steps back at '
                f'{date} triggered by {mention}')

    return f'Turn {data["round"]}.{data["turn"]+1} at {date} posted by {mention}'

def get_undo_data(files, timestamps, index, game_seed):
    if index >= len(timestamps) - 1:
        return game_seed

    return files[timestamps[index + 1]]

async def undo_backup(guild, channel, game_id, user, choice):
    files = {}
    game_seed = {}
    game_state_path = Path(f"game/game-{game_id}.txt")
    for path in glob(f"game/game-{game_id}-*.txt"):
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
    if choice.isnumeric() and 0 <= int(choice) < len(timestamps) and \
        (int(choice) != 0 or "undo" in files[0]):
        index = len(timestamps) - int(choice) - 1
        path = files[timestamps[index]]["path"]
        data = get_undo_data(files, timestamps, index, game_seed)
        backup = f"game/game-{game_id}-undo-{choice}-{datetime.now()}-{format_username(user, '_')}.txt"
        shutil.copy(str(game_state_path), backup)
        if path != game_state_path:
            shutil.copy(str(path), str(game_state_path))
            path.unlink()

        if int(choice) == 0:
            label = "to the latest undone game state: "
        else:
            label = f"{choice} game states to "
        label += format_undo_option(guild, data, timestamp)
        await channel.send(f'Going back {label}...')
        with game_state_path.open('r') as game_state_file:
            game_state = game_state_file.read()
            with get_byc(game_id, user) as byc:
                await byc_public_result(byc, guild, channel,
                                        game_state=game_state)

        return

    # Display options, including latest game seed data
    with game_state_path.open('r') as game_state_file:
        game_state = game_state_file.read()
        with get_byc(game_id, user) as byc:
            game_seed = byc.get_game_seed(game_state)

        match = re.match(r'\[q="([^"]*)"\]', game_state)
        if match:
            game_seed["user"] = match.group(1)

    msg = ""
    for index, timestamp in enumerate(timestamps):
        data = get_undo_data(files, timestamps, index, game_seed)
        if index == len(timestamps) - 1:
            msg += '\nCurrent game state: '
        else:
            msg += f'\n{len(timestamps) - index - 1}. '
        msg += format_undo_option(guild, data, timestamp)

    await channel.send(f"Pick a state to undo to with **!undo <number>**:{msg}")

async def byc_public_result(byc, guild, main_channel, game_state_path=None,
                            game_state="", old_game_state="",
                            initial_setup=False):
    seed = byc.get_game_seed(game_state)
    users = initial_setup
    updated = False
    old_seed = {}
    role_texts = {}
    roles = {}
    banner_priority = [float('inf')] * len(seed["usernames"])
    for role_group, role_text in byc_role_text.items():
        role_texts[role_group] = any(text in game_state for text in role_text)
        if role_texts[role_group] and old_seed is None:
            old_seed = byc.get_game_seed(old_game_state)
            roles = {role.name: role for role in guild.roles}

    if role_texts["character"]:
        users = True
        await update_character_roles(guild, roles, old_seed, seed)
    if role_texts["title"]:
        if await update_title_roles(guild, roles, old_seed, seed, banner_priority):
            updated = True
    if role_texts["loyalty"]:
        if await update_loyalty_roles(guild, roles, old_seed, seed, banner_priority):
            updated = True

    if initial_setup:
        await update_channels(guild, main_channel, byc.game_id, seed)

    if any(style != 1 for style in seed.get("promptStyle", [])):
        seed["promptStyle"] = [1] * len(seed["players"])
        updated = True
    if updated:
        game_state = byc.set_game_seed(game_state, seed)

    if game_state_path is not None:
        if "round" in seed:
            backup = f'game/game-{byc.game_id}-{seed["round"]}-{seed["turn"]}-{datetime.now()}-{format_username(byc.user, "_")}.txt'
            shutil.copy(str(game_state_path), backup)

        with game_state_path.open('w') as game_state_file:
            game_state_file.write(game_state)

    # Process the game state (BBCode -> Markdown and HTML game state)
    game_state_markdown = bbcode.process_bbcode(game_state)
    public_message, mentions = replace_roles(game_state_markdown, guild,
                                             seed=seed, users=users, deck=False)

    if bbcode.game_state != "":
        path = byc.save_game_state_screenshot(images, bbcode.game_state)
        image = discord.File(path)
    else:
        image = None

    new_messages = await send_message(main_channel, public_message, mentions,
                                      file=image)

    # Pin the message if it has a screenshot - unpin others
    if image is not None:
        pins = await main_channel.pins()
        for pin in pins:
            await pin.unpin()
        for new_message in new_messages:
            await new_message.pin()

async def byc_command(message, command, arguments):
    choice = ' '.join(arguments)
    logging.info('%s: %s %s', message.author.name, command, choice)

    channel = message.channel
    guild = message.guild
    if guild is None:
        await channel.send("BYC is not enabled in direct messages.")
        return

    user = message.author.name
    # Check permissions
    if not is_byc_enabled(guild, channel):
        await channel.send("BYC is not enabled: Bot needs permissions :robot:")
        return

    logging.info('%d %s', channel.id, channel.topic)
    if channel.topic is not None and channel.topic.startswith("byc:"):
        parts = channel.topic.split(":")
        game_id = int(parts[1])
        num_buttons = int(parts[2])
        options = Dialog.decode_options(parts[3])
        has_input = bool(parts[4])
        choices = [choice for choice in parts[5:] if choice != ""]
    else:
        game_id = channel.id
        num_buttons = 0
        options = {}
        has_input = False
        choices = []

    game_state_path = Path(f"game/game-{game_id}.txt")
    game_state = "Starting a new BYC game...\n"
    initial_setup = False
    if not game_state_path.exists():
        if command == "byc":
            game_state_path.touch()
            initial_setup = True
            await channel.send(f"{game_state}Only {message.author.mention} "
                               "will be able to answer the following dialogs.")
        else:
            await channel.send("BYC is currently not running on this channel. "
                               "To start a new game, type **!byc**.")
            return
    elif channel.id == game_id:
        if command == "cleanup": # TODO: Check permissions?
            if choice != channel.mention:
                await channel.send("Please confirm permanent deletion "
                                   "of the BYC game in this channel by "
                                   "typing **!cleanup #name** using "
                                   "this channel's #name.")
                return

            await byc_cleanup(guild, channel, game_id, user, game_state_path)
            await channel.send("All items related to the BYC game deleted.")
            return
        elif command == "refresh":
            await sort_roles(guild)
            await channel.send("Roles have been repositioned.")
            return
        elif len(choices) >= 2 and choices[0] == "byc":
            if choices[1] != format_username(user):
                member = guild.get_member_named(choices[1])
                mention = member.mention if member is not None else choices[1]
                await channel.send("The game is currently being set up. Only "
                                   f"{mention} is able to answer the dialogs.")
                return

            initial_setup = True
        elif command in ("undo", "redo"):
            await undo_backup(guild, channel, game_id, user,
                              '0' if command == "redo" else choice)
            return
        elif command != "state":
            reply = ("A BYC game is currently underway in this channel and "
                     "you do not seem to be a part of this game. To start "
                     "a new game, use another channel and type **!byc**.")
            for other in guild.channels:
                if other.name == format_private_channel(channel.name, user):
                    reply = (f"{message.author.mention} Please perform BYC "
                             f"actions in your own channel: {other.mention}")
                    break

            await channel.send(reply)
            return
    elif command in ("cleanup", "refresh"):
        if command == "cleanup":
            example = "**!cleanup** #main_channel"
        else:
            example = f"**!{command}**"
        await channel.send(f"Please use the command {example} from within "
                           "the main BYC game channel.")
        return

    if command in ("ok", "cancel"):
        if command == "cancel" and "Save and Quit" in options:
            await channel.send("Canceling would make your actions public. "
                               "If this is what you want, use **!commit**.")
            return

        choice = command
    elif command == "commit":
        choice = "cancel"

    force = False
    if command == "undo":
        try:
            count = int(choice)
        except ValueError:
            count = 1

        await channel.send(f"Undoing last {choice} choice(s)...")
        choices = choices[:-count]
        force = True
    elif command == "redo":
        await channel.send("Redoing choices...")
        force = True
    elif command == "reset":
        await channel.send("Reverting to the state when you last used **!byc**")
        choices = []
        force = True
    elif command == "hand":
        if choices and "Save and Quit" not in options:
            await channel.send("Showing hand report is only possible when you "
                               "are in the main dialog.")
            return
        choices.append("1")
    elif command == "state":
        if channel.id == game_id and not initial_setup:
            choices = ["2", "\b2", "\b1"]
            force = True
        elif choices and "Save and Quit" not in options:
            await channel.send("Showing game state is only possible when you "
                               "are in the main dialog.")
            return
        else:
            choices.append("2")
    elif command == "byc":
        choices = ["byc", format_username(user)] if initial_setup else []
        force = not initial_setup
    elif choice in options:
        choices.append(f"\b{options[choice] + 1}")
    elif has_input:
        if initial_setup and choice.startswith('<@') and message.mentions:
            choices.append(message.mentions[0].name)
        else:
            choices.append(choice)
    elif choice.isnumeric() and 0 < int(choice) <= num_buttons:
        choices.append(f"\b{choice}")
    else:
        await channel.send("Option not known. Correct your command usage.")
        return

    query = False
    with get_byc(game_id, user, keep=lambda: query) as byc:
        if not initial_setup:
            # Try to avoid reading files all the time and use the browser's
            # current game state instead
            try:
                game_state = byc.retrieve_game_state(force=force)
            except ValueError:
                with game_state_path.open('r') as game_state_file:
                    game_state = game_state_file.read()

        run = True
        while run:
            dialog = byc.run_page(choices[2:] if initial_setup else choices,
                                  game_state, force=force)

            # Store choices into the topic, adjust channel topic
            query = isinstance(dialog, Dialog)
            if query:
                await update_channel(channel, game_id, dialog, choices)
                if len(dialog.buttons) == 2 and not dialog.input:
                    if dialog.buttons[0] == "Dialog":
                        # Do not allow hand display in Spoiler
                        # TODO: Unless the game has ended and the command is
                        # used from the main game channel
                        choices.append("\b1")
                        continue
                    if command == "state":
                        await send_message(channel, dialog.msg)
                        choices.append("\b2")
                        continue

                if command == "state":
                    reply = ("Options: **!commit**: Save and Quit,"
                             "**!undo 2**, **!reset**")
                    run = False
                else:
                    reply = cards.replace_cards(dialog.msg, deck=False)
                    if "Save and Quit" in dialog.options:
                        reply = reply \
                            .replace("Print Hand Report",
                                     "Show Hand Report (**!hand**)") \
                            .replace("Display Game State",
                                     "Post Game State (**!state**)")
                    if len(dialog.buttons) > 1 or dialog.input or \
                        command == "undo":
                        buttons = ["cancel", "ok"]
                        options = ', '.join([
                            format_button(buttons[index], text)
                            for index, text in enumerate(dialog.buttons)
                            if not dialog.input or buttons[index] != "ok"
                        ])
                        if dialog.input:
                            sample = "input" if initial_setup else "number"
                            options += f', **!choose** <{sample}>'
                        if command == "undo":
                            options += ', **!undo**'

                        reply += f"\nOptions: {options}"
                        run = False
                    else:
                        choices.append("\b1")

                await send_message(channel, reply)
            else:
                if channel.id != game_id or command != "state":
                    await update_channel(channel, game_id, Dialog.EMPTY, [])
                # Update based on game state
                main_channel = guild.get_channel(game_id)
                await byc_public_result(byc, guild, main_channel,
                                        game_state_path=game_state_path,
                                        game_state=dialog,
                                        old_game_state=game_state,
                                        initial_setup=initial_setup)

                run = False

def add_ping(text, guild, pings, role_mentions, **kwargs):
    ping, mention = replace_roles(text, guild=guild, emoji=False, deck=False,
                                  **kwargs)
    pings.append(ping)
    role_mentions.update(mention.roles)

def ping_command(guild, seed, author, bbcode, mentions):
    pings = []
    role_mentions = set([])
    try:
        author_role = seed["players"][seed["usernames"].index(author)]
    except (KeyError, IndexError, ValueError):
        try:
            author_role = bbcode.image_text[0]
        except IndexError:
            author_role = ""

    for interrupt in bbcode.interrupts:
        names = [
            player['name'] for player in interrupt['players']
            if player['action'] == ''
        ]
        if names:
            add_ping(f"Interrupts for {interrupt['topic']}: {' '.join(names)}",
                     guild, pings, role_mentions)

    for skill_check in bbcode.skill_checks:
        names = [
            player['name'] for player in skill_check['players']
            if player['bold'] != ''
        ]
        if names:
            add_ping(f"{skill_check['topic']}: {names[0]}", guild, pings,
                     role_mentions)

    remaining_roles = [
        role for role in mentions.roles
        if role.name != author_role and role not in role_mentions
    ]
    for bold in bbcode.bold_text:
        bold_roles = [role for role in remaining_roles if role.name in bold]
        if bold_roles:
            add_ping(bold, guild, pings, role_mentions, roles=bold_roles)

    response = "\n".join(pings)
    mentions = discord.AllowedMentions(everyone=False, users=False,
                                       roles=list(role_mentions))
    return response, mentions

async def thread_command(message, guild, command):
    game_id = config['thread_id']
    post, seed = thread.retrieve(game_id)
    if post is None:
        await message.channel.send('No latest post found!')

    if command == "succession":
        succession, mentions = replace_roles(cards.lines_of_succession(seed),
                                             guild)
        await send_message(message.channel, succession, mentions)
        return
    if command == "analyze":
        if not seed.get('gameOver'):
            await message.channel.send('Game is not yet over!')
        else:
            analysis = cards.analyze(seed)
            if analysis == '':
                analysis = 'No decks found in the game!'

            await send_message(message.channel, analysis)
        return

    author = thread.get_author(ByYourCommand.get_quote_author(post)[0])
    byc = ByYourCommand(game_id, author, config['script_url'])
    if command == "image":
        choices = []
        dialog = byc.run_page(choices, post)
        if "You are not recognized as a player" in dialog.msg:
            choices.extend(["\b1", "1"])
        choices.extend(["2", "\b2", "\b1"])
        post = byc.run_page(choices, post, num=len(choices),
                            quits=True, quote=False)

    bbcode = BBCodeMarkdown(images)
    text = bbcode.process_bbcode(post)
    if command == "image":
        path = byc.save_game_state_screenshot(images, bbcode.game_state)
        await message.channel.send(file=discord.File(path))
        return

    users = any(user_text in text for user_text in byc_role_text["character"])
    response, mentions = replace_roles(text, guild, seed=seed, users=users)
    if command == "ping":
        if not mentions.roles:
            await message.channel.send("I did not find anyone, what are you trying to do here? :robot:")
            return

        response, mentions = ping_command(guild, seed, author, bbcode, mentions)
        if response == "":
            await message.channel.send("I did not find anyone, what are you trying to do here? :robot:")
            return

    if message.guild != guild:
        # Useful for debugging but otherwise never do that
        mentions.roles = False
        response = discord.utils.escape_mentions(response)

    await send_message(message.channel, response, mentions)

async def show_search_result(channel, hit, deck, count, hidden):
    # Retrieve URL or (cropped) image attachment
    url = cards.get_url(hit.to_dict())
    if hit.bbox or hit.image:
        filename = f"{hit.expansion}_{hit.path}.{hit.ext}"
        path = Path(f"images/{filename}")
        if deck == 'board' and hit.bbox:
            name = hit.name.replace(' ', '_')
            target_path = Path(f"images/{hit.path}_{name}.{hit.ext}")
        else:
            target_path = path

        if not target_path.exists():
            if not path.exists():
                if hit.image:
                    path = images.retrieve(hit.image)
                    if not isinstance(path, PurePath):
                        raise ValueError(f'Could not retrieve image {hit.image}')
                else:
                    path = images.download(url, filename)

            if hit.bbox:
                try:
                    images.crop(path, target_path=target_path,
                                bbox=hit.bbox)
                except:
                    target_path = path
            else:
                target_path = path

        image = discord.File(target_path)
        url = ''
    else:
        image = None

    await channel.send(f'{cards.get_text(hit)}\n{url} (score: {hit.meta.score:.3f}, {count} hits, {len(hidden)} hidden)', file=image)

async def search_command(channel, deck, expansion, text):
    # Collect three results; if some of them has a seed constraint then usually
    # another relevant one does not, or has the opposite constraint. However
    # avoid low-quality results that may make hidden results unfindable
    limit = 3
    hidden = []
    lower_text = text.lower()
    if deck == 'board':
        response, count = Location.search_freetext(text, expansion=expansion,
                                                   limit=limit)
    else:
        response, count = Card.search_freetext(text, deck=deck,
                                               expansion=expansion, limit=limit)
    if count == 0:
        await channel.send('No card found')
        return

    seed = None
    for index, hit in enumerate(response):
        # Check if the seed constraints may hide this result
        if hit.seed:
            if seed is None:
                seed = thread.retrieve(config['thread_id'], download=False)[1]
            # Seed may not be locally available at this point
            if seed is not None:
                for key, value in hit.seed.to_dict().items():
                    if seed.get(key, value) != value:
                        # Hide due to seed constraints
                        hidden.append(hit)
                        break

        if hit not in hidden:
            if not cards.is_exact_match(hit, lower_text):
                for hid in hidden:
                    if cards.is_exact_match(hid, lower_text):
                        await show_search_result(channel, hid, deck, count,
                                                 hidden)
                        return

            await show_search_result(channel, hit, deck, count, hidden)
            return

    # Always show a result even if seed constraints has hidden all of them;
    # prefer top result in that case
    await show_search_result(channel, response[0], deck, count, hidden)

def format_command(command, description):
    if isinstance(description, tuple):
        return f"**!{command}** <{description[0]}>: {description[1]}"

    return f"**!{command}**: {description}"

@client.event
async def on_message(message):
    if message.author == client.user or len(message.content) == 0 or \
        message.content[0] not in ('!', '.'):
        return

    arguments = message.content.rstrip(' ').split(' ')
    command = arguments.pop(0)[1:]

    if command == "help":
        decks = ', '.join(sorted(cards.decks.keys()))
        reply = ("**!search** <text>: Search all decks "
                 "(also **!card**, **!**) - any command may start with **.**\n"
                 f"**!<deck>** <text>: Search a specific deck ({decks})\n"
                 "**!board** <text> [expansion]: Search a board or location\n"
                 "**!latest**: Show the latest game post\n"
                 "**!image**: Show the lastest game state\n"
                 "**!ping**: Show who needs to do something\n"
                 "**!succession**: Show the line of succession\n"
                 "**!analyze**: Show the top cards of decks after game over\n")
        if is_byc_enabled(message.guild, message.channel):
            reply += "\n".join([
                format_command(command, description)
                for command, description in byc_commands.items()
            ])

        await send_message(message.channel, reply)
        return

    # BYC commands
    # Required permissions: Manage Roles, Manage Channels, Manage Nicknames,
    # View Channels, Send Messages, Manage Messages, Embed Links, Attach Files,
    # Read Message History, Mention Everyone (402910224)
    if command in byc_commands:
        try:
            async with message.channel.typing():
                await byc_command(message, command, arguments)
        except:
            logging.exception("BYC error")
            await message.channel.send(f"Uh oh")
        return

    # Undocumented commands:
    # !bot: test command
    if command == "bot":
        await message.channel.send(f'Hello {message.author.mention}!')
        return

    # Thread lookup commands
    if command in ("latest", "image", "ping", "succession", "analyze"):
        # Optionally can take a guild ID as argument, but doing so will not 
        # cause usable mentions and is for debugging only
        guild = None
        if len(arguments) >= 1 and arguments[0].isnumeric():
            guild = client.get_guild(int(arguments[0]))
        if guild is None:
            guild = message.guild

        try:
            async with message.channel.typing():
                await thread_command(message, guild, command)
        except:
            logging.exception(f"Thread {command} error")
            await message.channel.send(f"Uh oh")
        return

    # Search cards/board locations
    if command in ('card', 'search', ''):
        deck = ''
        expansion = ''
    elif command not in cards.decks:
        return
    else:
        if "alias" in cards.decks[command]:
            deck = cards.decks[command]["alias"]
        else:
            deck = command

        if cards.decks[deck].get("expansion"):
            expansion = cards.find_expansion(arguments)
        else:
            expansion = ''

    try:
        async with message.channel.typing():
            await search_command(message.channel, deck, expansion,
                                 ' '.join(arguments))
    except:
        logging.exception(f"Search {deck} error")
        await message.channel.send(f"Please try again later.")

if __name__ == "__main__":
    client.run(config['token'])
