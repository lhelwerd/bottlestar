import logging
import discord
import yaml

with open("config.yml") as config_file:
    config = yaml.load(config_file)

client = discord.Client()

@client.event
async def on_ready():
    print(f'We have logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user or not message.content.startswith('!'):
        return

    arguments = message.content.split(' ')
    command = arguments.pop(0)[1:]

    if command == "bot":
        await message.channel.send(f'Hello @{message.author}!')

    cards = Cards(config['cards_url'])
    result = cards.find(' '.join(arguments),
                        '' if command == "card" else command)
    if result is not None:
        await message.channel.send(result)


def main():
    client.run(config['token'])

if __name__ == "__main__":
    main()
