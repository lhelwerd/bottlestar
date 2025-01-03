import argparse
import asyncio
import logging
from pathlib import Path
from elasticsearch_dsl.connections import connections
from bsg.bbcode import BBCodeMarkdown
from bsg.byc import ByYourCommand, Dialog
from bsg.card import Cards
from bsg.config import Config
from bsg.command import Command
from bsg.command.byc import BycCommand
from bsg.context import CommandLineContext
from bsg.image import Images
from bsg.search import Card
from bsg.thread import Thread

@Command.register("seed", "path", "key")
class SeedCommand(BycCommand):
    async def run(self, path=None, key=None, **kw):
        game_state = ""
        if path is not None:
            self.game_state_path = Path(path)
        else:
            self.game_state_path = Path(f"game/game-{self.context.game_id}.txt")

        try:
            with self.game_state_path.open('r') as game_state_file:
                game_state = game_state_file.read()
        except IOError:
            logging.exception("Could not read game state!")

        with self.get_byc() as byc:
            seed = byc.get_game_seed(game_state)
            await self.context.send(seed if key is None else seed.get(key))

@Command.register("images")
class ImagesCommand(BycCommand):
    async def run(self, **kw):
        with self.get_byc() as byc:
            byc.check_images(self.images)

@Command.register("byc_succession")
class BycSuccessionCommand(BycCommand):
    async def run(self, **kw):
        game_state = ""
        self.game_state_path = Path(f"game/game-{self.context.game_id}.txt")

        try:
            with self.game_state_path.open('r') as game_state_file:
                game_state = game_state_file.read()
        except IOError:
            logging.exception("Could not read game state, starting new")

        with self.get_byc() as byc:
            seed = byc.get_game_seed(game_state)
            await self.context.send(self.cards.lines_of_succession(seed))

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    parser.add_argument('--user', default='command line user',
                        help='user to log in as')
    parser.add_argument('--display', choices=('unicode', 'discord', ''),
                        default='unicode', help='format emoji')
    parser.add_argument('--interactive', action='store_true', default=False,
                        help='Display interactive command line prompt')
    parser.add_argument('--limit', default=10, type=int,
                        help='Number of results to show from card search')
    parser.add_argument('--no-limit', dest='limit', action='store_const',
                        const=None, help='Show search result with suggestions')
    parser.add_argument('--game-id', dest='game_id', default=0, type=int,
                        help='Identifier for the BYC game to play')
    parser.add_argument('command', help='command')
    parser.add_argument('arguments', nargs='*', help='arguments')
    args = parser.parse_args()
    return args

@Command.register("bbcode", "text", nargs=True)
class BBCodeCommand(Command):
    async def run(self, text="", **kw):
        cards = Cards(self.context.config['cards_url'])
        images = Images(self.context.config['api_url'])
        bbcode = BBCodeMarkdown(images)
        post = bbcode.process_bbcode(text)
        message = cards.replace_cards(post, display=self.context.emoji_display)
        await self.context.send(message)

@Command.register("replace", "text", nargs=True)
class ReplaceCommand(Command):
    async def run(self, text="", **kw):
        cards = Cards(self.context.config['cards_url'])
        message = cards.replace_cards(text, display=self.context.emoji_display)
        await self.context.send(message)

@Command.register("state")
class StateCommand(Command):
    async def run(self, **kw):
        thread = Thread(self.context.config['api_url'])
        game_id = self.context.config['thread_id']
        post, seed = thread.retrieve(game_id)
        if post is None:
            print('No latest post found!')
            return

        author = thread.get_author(ByYourCommand.get_quote_author(post)[0])
        if author is None:
            author = self.context.user
        byc = ByYourCommand(game_id, author, self.context.config['script_url'])

        choices = []
        dialog = byc.run_page(choices, post)
        if "You are not recognized as a player" in dialog.msg:
            choices.extend(["\b1", "1"])
        choices.extend(["2", "\b2", "\b0"])
        post = byc.run_page(choices, post, num=len(choices),
                            quits=True, quote=False)

        cards = Cards(self.context.config['cards_url'])
        images = Images(self.context.config['api_url'])
        bbcode = BBCodeMarkdown(images)
        text = bbcode.process_bbcode(post)
        message = cards.replace_cards(text, display=self.context.emoji_display)
        await self.context.send(message)

@Command.register("class", "path", nargs=True)
class ClassCommand(Command):
    async def run(self, query="", **kw):
        search = Card.search(using='main').source(['path', 'character_class']) \
            .filter("term", deck="char")
        if len(arguments) > 0:
            search = search.query("match", path=path)
        for card in search.scan():
            await self.context.send(f"{card.to_dict()!r}")
            await self.context.send(f"{card.path} {card.character_class}")

@Command.register("full_succession")
class FullSuccessionCommand(Command):
    async def run(self, **kw):
        search = Card.search(using='main').source(['path']) \
            .filter("term", deck="char")
        chars = list(search.scan())
        cards = Cards(self.context.config['cards_url'])
        await self.context.send(cards.lines_of_succession({
            "players": chars,
            "CFB": True
        }, unquote=False))

def main():
    args = parse_args()
    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s',
                        level=getattr(logging, args.log, None))

    config = Config("config.yml")

    # Define a default Elasticsearch client
    connections.create_connection(alias='main',
                                  hosts=[config['elasticsearch_host']])

    name = args.command
    arguments = args.arguments

    context = CommandLineContext(args, config)
    loop = asyncio.get_event_loop()
    command_loop = 1
    while command_loop > 0:
        ok = loop.run_until_complete(Command.execute(context, name, arguments))
        if not args.interactive:
            break

        if ok:
            print("Enter another command, or **exit** to stop.")
        else:
            print("Invalid command. Enter a valid command or **exit** to stop.")

        arguments = []
        while not arguments:
            arguments = input('> ').split(' ')
        name = arguments.pop(0)
        if name == "exit":
            command_loop = 0
        else:
            command_loop += 1

    loop.close()

if __name__ == "__main__":
    main()
