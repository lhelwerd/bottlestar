import argparse
import logging
import yaml
from bsg.bgg import RSS
from bsg.card import Cards

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
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

    command = args.command
    arguments = args.arguments
    cards = Cards(config['cards_url'])

    if command == "bot":
        print("Hello, command line user!")
        return
    if command == "latest" or command == "all":
        rss = RSS(config['rss_url'])
        result = rss.parse()
        try:
            ok = True
            while ok:
                print(cards.replace_cards(next(result), display='unicode'))
                if command == "all":
                    print('\n' + '=' * 80 + '\n')
                else:
                    ok = False
        except StopIteration:
            print('No latest message found!')
        return

    print(cards.find(' '.join(arguments), '' if command == "card" else command))

if __name__ == "__main__":
    main()
