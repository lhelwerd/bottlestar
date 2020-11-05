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
from bsg.context import CommandLineContext
from bsg.image import Images
from bsg.search import Card
from bsg.thread import Thread

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    parser.add_argument('--user', default='command line user',
                        help='user to log in as')
    parser.add_argument('--display', choices=('unicode', 'discord'),
                        default='unicode', help='format emoji')
    parser.add_argument('--limit', default=10, type=int,
                        help='Number of results to show from card search')
    parser.add_argument('--game-id', dest='game_id', default=0, type=int,
                        help='Identifier for the BYC game to play')
    parser.add_argument('command', help='command')
    parser.add_argument('arguments', nargs='*', help='arguments')
    args = parser.parse_args()
    return args

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
        print(name, arguments)
        if loop.run_until_complete(Command.execute(context, name, arguments)):
            print("Enter another command, or **exit** or Ctrl-C to stop.")
            arguments = []
            while not arguments:
                arguments = input().split(' ')
            name = arguments.pop(0)
            if name == "exit":
                break

            command_loop += 1
        else:
            command_loop = 0

    loop.close()
    if command_loop != 0:
        return

    # TODO Old commands from here on out, mostly preserved for debugging, 
    # should be migrated and then the loop could say "invalid command" if it 
    # would break out in the 'else'
    cards = Cards(config['cards_url'])
    images = Images(config['api_url'])
    if name == "byc_maintenance":
        game_state = ""
        if len(arguments) >= 1:
            game_state_path = Path(arguments[0])
        else:
            game_state_path = Path("game/game-0.txt")

        try:
            with game_state_path.open('r') as game_state_file:
                game_state = game_state_file.read()
        except IOError:
            logging.exception("Could not read game state, starting new")

        if len(arguments) >= 2:
            user = arguments[1]
        else:
            user = args.user

        byc = ByYourCommand(0, user, config['script_url'])
        bbcode = BBCodeMarkdown(images)

        if user == "seed":
            print(byc.get_game_seed(game_state))
            return

        if user == "images":
            byc.check_images(images)
            return

        if user == "succession":
            seed = byc.get_game_seed(game_state)
            print(cards.lines_of_succession(seed))
            return

    if name == "bbcode":
        bbcode = BBCodeMarkdown(images)
        text = bbcode.process_bbcode(' '.join(arguments))
        print(cards.replace_cards(text, display=args.display))
        return

    if name == "state":
        thread = Thread(config['api_url'])
        game_id = config['thread_id']
        post, seed = thread.retrieve(game_id)
        if post is None:
            print('No latest post found!')
            return

        author = thread.get_author(ByYourCommand.get_quote_author(post)[0])
        if author is None:
            author = args.user
        byc = ByYourCommand(game_id, author, config['script_url'])

        choices = []
        dialog = byc.run_page(choices, post)
        if "You are not recognized as a player" in dialog.msg:
            choices.extend(["\b1", "1"])
        choices.extend(["2", "\b2", "\b1"])
        post = byc.run_page(choices, post, num=len(choices),
                            quits=True, quote=False)

        bbcode = BBCodeMarkdown(images)
        text = bbcode.process_bbcode(post)
        print(cards.replace_cards(text, display=args.display))

        return

    if name == "replace":
        print(cards.replace_cards(' '.join(arguments),
              display=args.display))
        return
    if name == "class":
        search = Card.search(using='main').source(['path', 'character_class']) \
            .filter("term", deck="char")
        if len(arguments) > 0:
            search = search.query("match", path=' '.join(arguments))
        for card in search.scan():
            print(card.to_dict())
            print(card.path, card.character_class)

if __name__ == "__main__":
    main()
