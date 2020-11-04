import argparse
import logging
import discord
from elasticsearch_dsl.connections import connections
from bsg.command import Command
from bsg.context import DiscordContext
from bsg.config import Config

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

config = Config("config.yml")

client = discord.Client()
connections.create_connection(alias='main',
                              hosts=[config['elasticsearch_host']])

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

@client.event
async def on_message(message):
    if message.author == client.user or len(message.content) == 0 or \
        message.content[0] not in ('!', '.'):
        return

    arguments = message.content.rstrip(' ').split(' ')
    command = arguments.pop(0)[1:]
    context = DiscordContext(client, message, config)

    await Command.execute(context, command, arguments)

if __name__ == "__main__":
    client.run(config['token'])
