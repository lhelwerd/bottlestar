import argparse
import asyncio
from datetime import datetime
from glob import glob
import logging
from pathlib import Path
import re
import shutil
import discord
import yaml
from elasticsearch_dsl.connections import connections
from bsg.bbcode import BBCodeMarkdown
from bsg.byc import ByYourCommand, Dialog
from bsg.rss import RSS
from bsg.card import Cards
from bsg.image import Images
from bsg.search import Card

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
images = Images(config['image_api_url'])
bbcode = BBCodeMarkdown(images)
rss = RSS(config['rss_url'], images, config['image_url'],
          config.get('session_id'))
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
    "undo": ("step", "Go back step(s) in the series of actions (expensive)"),
    "redo": "Perform the series of actions again (expensive), for bot restarts",
    "reset": "Go back to the start of the series of actions (like **!byc**)",
    "cleanup": ("channel", "Delete all items related to the current game")
}

async def check_for_updates(client, server_id, channel_id):
    if server_id is None or channel_id is None:
        logging.warning('No server ID or channel ID provided')
        return

    previous_check = datetime.now()
    timeout = 60 * 5
    while True:
        result = rss.parse(previous_check, one=True)
        try:
            message = next(result)
            logging.info('We have a new message in the RSS, posting')
            guild = client.get_guild(server_id)
            channel = guild.get_channel(channel_id)
            await channel.send(replace_roles(next(message), guild))
        except StopIteration:
            logging.info("No new message")

        previous_check = datetime.now()
        await asyncio.sleep(timeout)

def replace_roles(message, guild=None, seed=None, users=False, deck=True):
    message = cards.replace_cards(message, deck=deck)

    if guild is None:
        return message

    titles = cards.titles.keys()
    for role in guild.roles:
        # Optionally only replace roles belonging to BYC
        if not role.mentionable:
            continue
        if seed is None or role.name in seed["players"] or role.name in titles:
            message = re.sub(rf"\b{role.name}\b", role.mention, message)

    if seed is not None and users:
        for username in seed["usernames"]:
            member = guild.get_member_named(username)
            if member is not None:
                message = re.sub(rf"\b{username}\b", member.mention, message)

    return message

@client.event
async def on_ready():
    logging.info('We have logged in as %s', client.user)
    for guild in client.guilds:
        logging.info('Server: %s #%d', guild.name, guild.id)
        for channel in guild.channels:
            logging.info('Channel: %s #%d', channel.name, channel.id)
        for role in guild.roles:
            if role.mentionable:
                logging.info('Role: %s', role.name)

    client.loop.create_task(check_for_updates(client, config.get('server_id'),
                                              config.get('channel_id')))

def format_private_channel(channel_name, user):
    # If user contains spaces then remove/replace those
    return f"byc-{channel_name}-{user.split(' ')[0].lower()}"

async def byc_cleanup(guild, channel, game_id):
    await channel.edit(topic="", reason="Cleanup of BYC status")
    private_channel_prefix = f"byc-{channel.name}-"
    for channel in guild.channels:
        if channel.name.startswith(private_channel_prefix):
            # TODO: Cleanup BYC roles of the user
            #user = channel.name[len(private_channel_prefix):]
            await channel.delete(reason="Cleanup of private channels for BYC")

    for path in glob(f"game/game-{game_id}*.txt"):
        Path(path).unlink()
    for path in glob(f"game/game-state-{game_id}-*"):
        Path(path).unlink()
    for path in glob(f"game/page-{game_id}-*.html"):
        Path(path).unlink()

async def create_role(guild, name, metadata, class_name=None):
    if class_name is None:
        class_name = name

    try:
        data = metadata[class_name]
        color = getattr(discord.Colour, data["color"])()
    except (AttributeError, KeyError):
        logging.exception("Could not get class/title color for %s", name)
        color = discord.Colour.default()

    return await guild.create_role(name=name, colour=color, mentionable=True)

async def update_character_roles(guild, seed):
    roles = {role.name: role for role in guild.roles}
    for username, character in zip(seed["usernames"], seed["players"]):
        if character not in roles:
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
            await member.add_roles(role)

def has_titles(seed, titles, index):
    return index != -1 and all(seed.get(name, -1) == index for name in titles)

async def update_title_roles(guild, old_seed, seed):
    roles = {role.name: role for role in guild.roles}
    for key, title in cards.titles.items():
        keys = title.get("titles", [key])
        titles = [name if name[0].islower() else name.lower() for name in keys]
        old_index = old_seed.get(titles[0], -1)
        index = seed.get(titles[0], -1)
        role = roles.get(key)
        if has_titles(seed, titles, index):
            if role is None:
                role = await create_role(guild, key, cards.titles)
            user = seed["usernames"][index]
            member = guild.get_member_named(user)
            if member is not None:
                await member.add_roles(role)
        elif role is not None and has_titles(old_seed, titles, old_index):
            old_user = seed["usernames"][old_index]
            old_member = guild.get_member_named(old_user)
            if old_member is not None:
                await old_member.remove_roles(role)

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
        private_channel = f"byc-{channel.name}-{user}"
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
    return permissions.is_superset(discord.Permissions(402902032))

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

            await byc_cleanup(guild, channel, game_id)
            await channel.send("All items related to the BYC game deleted.")
            return
        elif choices and choices[0] == "byc":
            if choices[1] != user:
                member = guild.get_member_named(choices[1])
                mention = member.mention if member is not None else choices[1]
                await channel.send("The game is currently being set up. Only "
                                   "{mention} is able to answer the dialogs.")
                return

            initial_setup = True
        else:
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
    elif command == "cleanup":
        await channel.send("Please use the command **!cleanup #main_channel** "
                           "from within the main BYC game channel.")
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
            choice = int(choice)
        except ValueError:
            choice = 1

        await channel.send(f"Undoing last {choice} choice(s)...")
        choices = choices[:-choice]
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
            await channel.send("Showing game state is only possible when you "
                               "are in the main menu.")
            return
        choices.append("1")
    elif command == "state":
        # TODO: Remove !state, !hand choices afterward to avoid too long chain
        if choices and "Save and Quit" not in options:
            await channel.send("Showing game state is only possible when you "
                               "are in the main dialog.")
            return
        choices.append("2")
    elif command == "byc":
        choices = ["byc", user] if initial_setup else []
        force = not initial_setup
    elif choice in options:
        choices.append(f"\b{options[choice] + 1}")
    elif has_input:
        choices.append(choice)
    elif choice.isnumeric() and 0 < int(choice) < num_buttons:
        choices.append(f"\b{choice}")
    else:
        await channel.send("Option not known. Correct your command usage.")
        return

    key = f"{game_id}-{user}"
    if key not in byc_games:
        byc_games[key] = ByYourCommand(game_id, user, config['script_url'])

    byc = byc_games[key]

    if not initial_setup:
        # Try to avoid reading files all the time and use the browser's current 
        # game state instead
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
                    # TODO: Unless the game has ended
                    choices.append("\b1")
                    continue
                elif command == "state":
                    await channel.send(dialog.msg)
                    choices.append("\b2")
                    continue

            reply = cards.replace_cards(dialog.msg, deck=False)
            if command == "state":
                reply = "Options: **!commit**: Save and Quit, **!undo 2**, **!reset**"
                run = False
            elif len(dialog.buttons) > 1 or dialog.input or command == "undo":
                buttons = ["cancel", "ok"]
                options = ', '.join([
                    format_button(buttons[index], text)
                    for index, text in enumerate(dialog.buttons)
                    if buttons[index] != "ok" or not dialog.input
                ])
                if dialog.input:
                    options += ', **!choose** <number>'
                if command == "undo":
                    options += ', **!undo**'

                reply += f"\nOptions: {options}"
                run = False
            else:
                choices.append("\b1")

            await channel.send(reply)
        else:
            await update_channel(channel, game_id, Dialog.EMPTY, [])
            # Update based on game state
            seed = byc.get_game_seed(dialog)
            users = initial_setup
            if " chooses to play " in dialog:
                users = True
                await update_character_roles(guild, seed)
            if " is now the " in dialog:
                try:
                    old_seed = byc.get_game_seed(game_state)
                except ValueError:
                    old_seed = {}

                await update_title_roles(guild, old_seed, seed)
            if initial_setup:
                await update_channels(guild, channel, game_id, seed)

            if "round" in seed:
                backup = f'game/game-{game_id}-{seed["round"]}-{seed["turn"]}-{datetime.now()}-{user}.txt'
                shutil.copy(str(game_state_path), backup)

            with game_state_path.open('w') as game_state_file:
                game_state_file.write(dialog)

            # Process the game state (BBCode -> Markdown and HTML game state)
            game_state_markdown = bbcode.process_bbcode(dialog)
            public_message = replace_roles(game_state_markdown, guild,
                                           seed=seed, users=users, deck=False)

            if bbcode.game_state != "":
                path = byc.save_game_state_screenshot(bbcode.game_state)
                image = discord.File(path)
            else:
                image = None

            main_channel = guild.get_channel(game_id)
            await main_channel.send(public_message, file=image)

            byc_games.pop(key, None)
            run = False

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
                 f"**!<deck>** <text>: Search a specific deck ({decks})\n")
        if is_byc_enabled(message.guild, message.channel):
            reply += "\n".join([
                format_command(command, description)
                for command, description in byc_commands.items()
            ])

        await message.channel.send(reply)
        return

    # BYC commands
    # Required permissions: Manage Roles, Manage Channels, Manage Nicknames,
    # View Channels, Send Messages, Embed Links, Attach Files,
    # Read Message History, Mention Everyone (402902032)
    #
    # Undocumented commands:
    # !bot      | test command
    # !latest   | retrieve BGG message from RSS feed

    if command in byc_commands:
        try:
            async with message.channel.typing():
                await byc_command(message, command, arguments)
        except:
            logging.exception("BYC error")
            await message.channel.send(f"Uh oh")
        return

    if command == "bot":
        await message.channel.send(f'Hello {message.author.mention}!')
    if command == "latest":
        try:
            await message.channel.send(replace_roles(next(rss.parse()),
                                                     message.guild))
        except StopIteration:
            await message.channel.send('No post found!')

    if command in ('card', 'search', ''):
        deck = ''
    elif command not in cards.decks:
        return
    elif "alias" in cards.decks[command]:
        deck = cards.decks[command]["alias"]
    else:
        deck = command

    response, count = Card.search_freetext(' '.join(arguments), deck=deck)
    if count == 0:
        await message.channel.send('No card found')
    else:
        for hit in response:
            url = cards.get_url(hit.to_dict())
            await message.channel.send(f'{url} (score: {hit.meta.score:.3f}, {count} hits)')
            break

if __name__ == "__main__":
    client.run(config['token'])
