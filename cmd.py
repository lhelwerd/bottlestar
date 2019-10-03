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

    if command == "bot":
        print("Hello, command line user!")
        return
    if command == "latest":
        rss = RSS(config['rss_url'])
        print(rss.parse())
        return

    cards = Cards(config['cards_url'])
    print(cards.find(' '.join(arguments), '' if command == "card" else command))

if __name__ == "__main__":
    main()
