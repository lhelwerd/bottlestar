import argparse
import base64
from datetime import datetime
import logging
from pathlib import Path
import re
import dateutil.parser
import yaml
from elasticsearch_dsl.connections import connections
from bsg.bbcode import BBCodeMarkdown
from bsg.rss import RSS
from bsg.byc import ByYourCommand, Dialog
from bsg.card import Cards
from bsg.image import Images
from bsg.search import Card

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    parser.add_argument('--user', default='command line user',
                        help='user to log in as')
    parser.add_argument('--display', choices=('unicode', 'discord'),
                        default='unicode', help='format emoji')
    parser.add_argument('command', help='command')
    parser.add_argument('arguments', nargs='*', help='arguments')
    args = parser.parse_args()
    return args

def main():
    args = parse_args()
    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s',
                        level=getattr(logging, args.log, None))

    with open("config.yml") as config_file:
        config = yaml.safe_load(config_file)

    # Define a default Elasticsearch client
    connections.create_connection(alias='main',
                                  hosts=[config['elasticsearch_host']])

    command = args.command
    arguments = args.arguments
    cards = Cards(config['cards_url'])
    images = Images(config['image_api_url'])

    if command == "bot":
        at = "@"
        print("Hello, {at}{args.user}!")
        return

    if command == "byc":
        game_state = ""
        game_state_path = Path("game/game-0.txt")
        if len(arguments) >= 1:
            game_state_path = Path(arguments[0])
            try:
                with game_state_path.open('r') as game_state_file:
                    game_state = game_state_file.read()
            except IOError:
                logging.exception("Could not read game state, starting new")

        if len(arguments) >= 2:
            user = arguments[1]
        else:
            user = args.user

        if user == "seed":
            match = re.search(r"New seed: (\S+)\[/color\]\[/size]", game_state)
            if match:
                seed = match.group(1)
                print(seed)
                print(base64.b64decode(seed.replace("-", "")))
            return

        byc = ByYourCommand(0, config['script_url'])
        bbcode = BBCodeMarkdown(images)

        if user == "images":
            byc.check_images(images)
            return

        choice = ""
        run = True
        dialog = None
        choices = []
        while choice != "exit":
            if choice != "":
                if choice in dialog.options:
                    choices.append(dialog.options[choice] + 1)
                elif dialog.input:
                    choices.append(choice)
                elif choice.isnumeric() and 0 < int(choice) <= len(dialog.buttons):
                    choices.append(int(choice))
                else:
                    print("Option not known")
                    run = False
            elif choices:
                run = False

            if run:
                dialog = byc.run_page(user, choices, game_state)

            if not isinstance(dialog, Dialog):
                game_state = dialog
                game_state_markdown = bbcode.process_bbcode(game_state)
                print(cards.replace_cards(game_state_markdown, args.display))
                with game_state_path.open('w') as game_state_file:
                    game_state_file.write(game_state)

                if bbcode.game_state != "":
                    byc.save_game_state_screenshot(bbcode.game_state)

                choice = "exit"
            else:
                print(cards.replace_cards(dialog.msg, args.display))
                if dialog.input:
                    print(', '.join(dialog.buttons))
                else:
                    print(' '.join(f"{idx+1}: {text}" for (idx, text) in enumerate(dialog.buttons)))
                print(f"More options: {dialog.options}")
                if len(dialog.buttons) == 1 and not dialog.input:
                    print("Only one option is available, continuing.")
                    choice = "1"
                else:
                    choice = input()
                run = True

        return
    if command == "bbcode":
        bbcode = BBCodeMarkdown(images)
        text = bbcode.process_bbcode(' '.join(arguments))
        print(cards.replace_cards(text, args.display))
        return

    if command == "latest" or command == "all" or command == "update":
        rss = RSS(config['rss_url'], images, config['image_url'],
                  config.get('session_id'))
        if command == "update":
            one = True
            if arguments:
                if_modified_since = dateutil.parser.parse(" ".join(arguments))
            else:
                if_modified_since = datetime.now()
        else:
            one = False
            if_modified_since = None

        result = rss.parse(if_modified_since=if_modified_since, one=one)
        try:
            ok = True
            while ok:
                print(cards.replace_cards(next(result), display=args.display))
                if command == "all":
                    print('\n' + '=' * 80 + '\n')
                else:
                    ok = False
        except StopIteration:
            print('No latest message found!')
        return
    if command == "replace":
        print(cards.replace_cards(' '.join(arguments),
              display=args.display))
        return

    if command in ('card', 'search'):
        deck = ''
    elif command not in cards.decks:
        return
    else:
        deck = command

    response, count = Card.search_freetext(' '.join(arguments), deck=deck)
    print(f'{count} hits (at most 10 are shown):')
    for hit in response:
        url = cards.get_url(hit.to_dict())
        print(f'{hit.name}: {url} (score: {hit.meta.score:.3f})')

if __name__ == "__main__":
    main()
