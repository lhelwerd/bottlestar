import argparse
import asyncio
from datetime import datetime
import logging
import discord
import yaml
from bsg.bgg import RSS
from bsg.card import Cards

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    args = parser.parse_args()
    return args

if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s',
                        level=getattr(logging, args.log, None))

with open("config.yml") as config_file:
    config = yaml.safe_load(config_file)

client = discord.Client()
cards = Cards(config['cards_url'])
rss = RSS(config['rss_url'], config['image_url'], config.get('session_id'))

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
            pass

        previous_check = datetime.now()
        await asyncio.sleep(timeout)

def replace_roles(message, guild=None):
    message = cards.replace_cards(message)

    if guild is None:
        return message

    for role in guild.roles:
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

@client.event
async def on_message(message):
    if message.author == client.user or not message.content.startswith('!'):
        return

    arguments = message.content.split(' ')
    command = arguments.pop(0)[1:]

    if command == "bot":
        await message.channel.send(f'Hello {message.author.mention}!')
    if command == "latest":
        try:
            await message.channel.send(replace_roles(next(rss.parse()),
                                                     message.guild))
        except StopIteration:
            await message.channel.send('No post found!')

    result = cards.find(' '.join(arguments),
                        '' if command == "card" else command)
    if result is not None:
        await message.channel.send(result)

if __name__ == "__main__":
    client.run(config['token'])
