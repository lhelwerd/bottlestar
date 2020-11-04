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

    command = args.command
    arguments = args.arguments

    context = CommandLineContext(args, config)
    loop = asyncio.get_event_loop()
    if loop.run_until_complete(Command.execute(context, command, arguments)):
        loop.close()
        return

    loop.close()

    cards = Cards(config['cards_url'])
    images = Images(config['api_url'])
    if command == "byc_interactive":
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

        choice = ""
        run = True
        dialog = None
        choices = []
        while choice != "exit":
            force = False
            if choice != "":
                if choice == "undo":
                    print("Undoing last choice -- redoing all choices before")
                    choices = choices[:-1]
                    force = True
                elif choice == "reset":
                    print("Going back to the state before the last play")
                    choices = []
                    force = True
                elif choice == "redo":
                    print("Redoing all choices")
                    force = True
                elif choice in dialog.options:
                    choices.append(f"\b{dialog.options[choice] + 1}")
                elif dialog.input:
                    choices.append(choice)
                elif choice.isnumeric() and 0 < int(choice) <= len(dialog.buttons):
                    choices.append(f"\b{choice}")
                else:
                    print("Option not known")
                    run = False
            elif choices:
                run = False

            if run:
                dialog = byc.run_page(choices, game_state, force=force)

            if not isinstance(dialog, Dialog):
                game_state = dialog
                game_state_markdown = bbcode.process_bbcode(game_state)
                print(cards.replace_cards(game_state_markdown, args.display))
                with game_state_path.open('w') as game_state_file:
                    game_state_file.write(game_state)

                if bbcode.game_state != "":
                    path = byc.save_game_state_screenshot(images,
                                                          bbcode.game_state)
                    print(f"Current game state found in screenshot at {path}")

                choice = "exit"
            else:
                print(cards.replace_cards(dialog.msg, args.display))
                print(f"{dialog}")
                if dialog.input:
                    print(', '.join(dialog.buttons))
                else:
                    print(' '.join(f"{idx+1}: {text}" for (idx, text) in enumerate(dialog.buttons)))
                print(f"More options: {dialog.options}, undo, reset, redo, exit")
                print(f"Choices made so far: {choices}")
                if len(dialog.buttons) == 1 and not dialog.input and choice != "undo":
                    print("Only one option is available, continuing.")
                    choice = "1"
                else:
                    choice = input()
                run = True

        return
    if command == "bbcode":
        bbcode = BBCodeMarkdown(images)
        text = bbcode.process_bbcode(' '.join(arguments))
        print(cards.replace_cards(text, display=args.display))
        return

    if command == "state":
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

    if command == "replace":
        print(cards.replace_cards(' '.join(arguments),
              display=args.display))
        return
    if command == "class":
        search = Card.search(using='main').source(['path', 'character_class']) \
            .filter("term", deck="char")
        if len(arguments) > 0:
            search = search.query("match", path=' '.join(arguments))
        for card in search.scan():
            print(card.to_dict())
            print(card.path, card.character_class)

if __name__ == "__main__":
    main()
