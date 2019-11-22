import argparse
import asyncio
from datetime import datetime
from glob import glob
import logging
from pathlib import Path
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
byc_commands = {
    "byc": "Start a BYC game or a series of actions",
    "ok": "Confirm performing an action",
    "cancel": "Reject perform an action",
    "choose": "Select a numeric value or input text (during setup)",
    "commit": "Show result of series of actions in public",
    "undo": "Go back a step in the series of actions (expensive)",
    "reset": "Go back to the start of the series of actions (like **!byc**)",
    "cleanup": "Delete current game, all private channels and roles"
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

def replace_roles(message, guild=None):
    message = cards.replace_cards(message)

    if guild is None:
        return message

    for role in guild.roles:
        # TODO: Only replace roles belonging to BYC
        if role.mentionable:
            message = message.replace(role.name, role.mention)

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
    return f"byc-{channel_name}-{user}"

async def byc_cleanup(guild, channel_name, game_id):
    private_channel_prefix = f"byc-{channel_name}-"
    for channel in guild.channels:
        if channel.name.startswith(private_channel_prefix):
            # TODO: Cleanup BYC roles of the user
            #user = channel.name[len(private_channel_prefix):]
            channel.delete(reason="Cleanup of private channels for BYC")

    game_state_path = Path(f"game/game-{game_id}.txt")
    if game_state_path.exists():
        game_state_path.unlink()
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
        color = None

    return guild.create_role(name, colour=color, mentionable=True)

async def update_character_roles(guild, seed):
    roles = {role.name: role for role in guild.roles}
    for username, character in zip(seed["usernames"], seed["players"]):
        if character not in roles:
            # Search in cards what the class is and use metadata for color
            search = Card.search(using='main').source(['character_class']) \
                .filter("term", deck="character").filter("term", path=character)
            try:
                card = search[:1].execute().hits[0]
                class_name = card.character_class
            except IndexError:
                logging.exception("Could not find character %s", character)
                continue

            create_role(guild, character, cards.character_classes, class_name)
        else:
            role = roles[character]

        member = guild.get_member_named(username)
        member.add_roles(role)

def has_titles(seed, titles, index):
    return all(seed[name] == index for name in titles)

async def update_title_roles(guild, old_seed, seed):
    roles = {role.name: role for role in guild.roles}
    for key, title in cards.titles.items():
        titles = [name.lower() for name in title.get("titles", [key])]
        old_index = old_seed[titles[0]]
        index = seed[titles[0]]
        role = roles.get(title)
        if has_titles(seed, titles, index):
            if role is None:
                role = create_role(guild, title, cards.titles)
            user = seed["usernames"][index]
            member = guild.get_member_named(user)
            member.add_roles(role)
        elif role is not None and has_titles(old_seed, titles, old_index):
            old_user = seed["usernames"][old_index]
            old_member = guild.get_member_named(old_user)
            old_member.remove_roles(role)

async def update_channel(channel, game_id, dialog, choices):
    if not choices and channel.id == game_id:
        topic = "By Your Command game"
    else:
        topic = f"byc:{game_id}:{repr(dialog)}:{':'.join(choices)}"

    await channel.edit(topic=topic)

async def update_channels(guild, channel, game_id, seed):
    for user in seed["usernames"]:
        private_channel = f"byc-{channel.name}-{user}"
        deny = discord.PermissionOverwrite(read_messages=False,
                                           send_messages=False)
        allow = discord.PermissionOverwrite(read_messages=True,
                                            send_messages=True)
        member = guild.get_member_named(user)
        guild.create_text_channel(private_channel, overwrites={
            guild.default_role: deny,
            member: allow,
            guild.me: allow
            }, topic=f"byc:{game_id}:0:e30=:0:")

async def byc_command(message, command, arguments):
    choice = ' '.join(arguments)
    logging.debug('%s: %s %s', message.author.name, command, choice)

    channel = message.channel
    guild = message.guild
    user = message.author.name
    permissions = client.user.permissions_in(channel)
    # Check permissions
    if permissions < discord.Permissions(402902032):
        await channel.send("BYC is not enabled: Bot needs permissions :robot:")
        return

    logging.debug('%d %s / %d', channel.id, channel.topic, permissions.raw)
    if channel.topic.startswith("byc:"):
        # TODO: Also keep track of dialog options in channel topic
        parts = channel.topic.split(":")
        game_id = int(parts[1])
        num_buttons = int(parts[2])
        options = Dialog.decode_options(parts[3])
        has_input = bool(parts[4])
        choices = parts[5:]
    else:
        game_id = channel.id
        num_buttons = 0
        options = {}
        has_input = False
        choices = []

    game_state_path = Path(f"game/game-{game_id}.txt")
    game_state = "Starting a new **!byc** game..."
    initial_setup = False
    if not game_state_path.exists():
        if command == "byc":
            game_state_path.touch()
            initial_setup = True
            choices.append("byc")
        else:
            await channel.send("BYC is currently not running on this channel. "
                               "To start a new game, type **!byc**.")
            return
    elif channel.id == game_id:
        if choices and choices[0] == "byc":
            initial_setup = True
        elif command == "cleanup": # TODO: Check permissions?
            if choice != channel.mention:
                await channel.send("Please confirm permanent deletion "
                                   "of the BYC game in this channel by "
                                   "typing **!cleanup #name** using "
                                   "this channel's #name.")
                return

            await byc_cleanup(guild, channel.name, game_id)

        for other_channel in guild.channels:
            if other_channel.name == format_private_channel(channel.name, user):
                await channel.send("Please perform all BYC actions in your own "
                                   f"private channel: {other_channel.mention}")
                return

        await channel.send("A BYC game is currently underway in this channel "
                           "and you do not seem to be a part of this game. "
                           "To start a new game, use another channel and type "
                           "**!byc**.")
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
        await channel.send("Undoing last choice...")
        choices = choices[:-1]
        force = True
    elif command == "reset":
        await channel.send("Reverting to the state when you last used **!byc**")
        choices = []
        force = True
    elif command == "byc":
        choices = []
        force = True
    elif choice in options:
        choices.append(f"\b{options[choice] + 1}")
    elif has_input:
        choices.append(choice)
    elif choice.isnumeric() and 0 < int(choice) < num_buttons:
        choices.append(f"\b{choice}")
    else:
        await channel.send("Option not known. Correct your command usage.")
        return

    byc = ByYourCommand(game_id, config['script_url'])

    if not initial_setup:
        # Try to avoid reading files all the time and use the browser's current 
        # game state instead
        try:
            game_state = byc.retrieve_game_state(user, force=force)
        except ValueError:
            with game_state_path.open('r') as game_state_file:
                game_state = game_state_file.read()

    dialog = byc.run_page(user, choices, game_state, force=force)

    # Store choices into the topic, adjust channel topic after initial setup
    query = isinstance(dialog, Dialog)
    await update_channel(channel, game_id, dialog, choices if query else [])
    if query:
        message = cards.replace_cards(dialog.msg)
        if len(dialog.buttons) > 1 or dialog.input or command == "undo" or initial_setup:
            options = ', '.join([
                "!commit" if text == "Save and Quit" else f"!{text.lower()}"
                for text in dialog.buttons
            ])
            if dialog.input:
                options += ', !choose <input>'

            message += f"\nOptions: {options}"

        await channel.send(message)
    else:
        # Update based on game state
        seed = byc.get_game_seed(dialog)
        if " chooses to play " in dialog:
            await update_character_roles(guild, seed)
        if " is now the " in dialog:
            try:
                old_seed = byc.get_game_seed(game_state)
            except ValueError:
                old_seed = {}

            await update_title_roles(guild, old_seed, seed)
        if initial_setup:
            await update_channels(guild, channel, game_id, seed)

        # Process the game state (BBCode -> Markdown and HTML game state)
        game_state_markdown = bbcode.process_bbcode(dialog)
        await channel.send(cards.replace_cards(game_state_markdown))
        with game_state_path.open('w') as game_state_file:
            game_state_file.write(dialog)

        if bbcode.game_state != "":
            path = byc.save_game_state_screenshot(user, bbcode.game_state)
            image = discord.File(path)
            public_message = replace_roles(bbcode.game_state, guild)
            await guild.get_channel(game_id).send(public_message, file=image)

@client.event
async def on_message(message):
    if message.author == client.user or not message.content.startswith('!'):
        return

    arguments = message.content.split(' ')
    command = arguments.pop(0)[1:]

    ## TODO: BYC commands
    ## Required permissions: Manage Roles, Manage Channels, Manage Nicknames,
    ## View Channels, Send Messages, Embed Links, Attach Files,
    ## Read Message History, Mention Everyone (402902032)
    #
    # !bot      | test command
    # !latest   | retrieve BGG message from RSS feed
    # !search   | (also !card, !) search all decks
    # !<deck>   | search a specific deck

    if command in byc_commands:
        try:
            byc_command(message, command, arguments)
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
