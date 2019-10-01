import sys
import yaml
from bsg.card import Cards

def main():
    with open("config.yml") as config_file:
        config = yaml.safe_load(config_file)

    arguments = sys.argv[1:]
    if len(arguments) == 0:
        print("Usage: python cmd.py <command> [arguments...]", file=sys.stderr)
        sys.exit(1)

    command = arguments.pop(0)
    if command == "bot":
        print("Hello, command line user!")
        return

    print(command, arguments)

    cards = Cards(config['cards_url'])
    print(cards.find(' '.join(arguments), '' if command == "card" else command))

if __name__ == "__main__":
    main()
