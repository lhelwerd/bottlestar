import argparse
import logging
import discord
import yaml
from bsg.bgg import RSS
from bsg.card import Cards

with open("config.yml") as config_file:
    config = yaml.safe_load(config_file)

client = discord.Client()

COLORS = [
    ('Leadership', ':green_apple:'),
    ('Tactics', ':octopus:'),
    ('Politics', ':prince:'),
    ('Piloting', ':airplane_small:'),
    ('Engineering', ':large_blue_diamond:')
]

def replace_roles(message, guild=None):
    for skill_type, emoji in COLORS:
        message = message.replace(skill_type, skill_type + emoji)

    if guild is None:
        return message

    for role in roles:
        if role.mentionable:
            message = message.replace(role.name, role.mention)

    return message

@client.event
async def on_ready():
    logging.info('We have logged in as %s', client.user)
    for guild in client.guilds:
        logging.info('Server: %s', guild.name)
        for channel in guild.channels:
            logging.info('Channel: %s', channel.name)
        for role in guild.roles:
            if role.mentionable:
                logging.info('Role: %s', role.name)

@client.event
async def on_message(message):
    if message.author == client.user or not message.content.startswith('!'):
        return

    arguments = message.content.split(' ')
    command = arguments.pop(0)[1:]

    if command == "bot":
        await message.channel.send(f'Hello {message.author.mention}!')
    if command == "latest":
        rss = RSS(config['rss_url'])
        await message.channel.send(replace_roles(rss.parse(), message.guild))

    cards = Cards(config['cards_url'])
    result = cards.find(' '.join(arguments),
                        '' if command == "card" else command)
    if result is not None:
        await message.channel.send(result)

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    args = parser.parse_args()
    return args

def main():
    args = parse_args()
    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s',
                        level=getattr(logging, args.log, None))

    client.run(config['token'])

if __name__ == "__main__":
    main()
