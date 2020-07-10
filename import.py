import argparse
import logging
import json
from elasticsearch_dsl.connections import connections
import yaml
from bsg.search import Card, Location

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    parser.add_argument('--host', default='localhost',
                        help='ElasticSearch host')
    parser.add_argument('--deck', default=None,
                        help='Only replace this deck (no renames)')
    parser.add_argument('--expansion', default=None,
                        help='Only replace this expansion (no renames)')
    parser.add_argument('cards', nargs='*',
                        help='Only replace these cards (no renames)')
    parser.add_argument('--no-locations', action='store_false', default=True,
                        dest='locations', help='Skip importing board locations')
    args = parser.parse_args()
    return args

def main():
    args = parse_args()
    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s',
                        level=getattr(logging, args.log, None))

    # Define a default Elasticsearch client
    connections.create_connection(alias='main', hosts=[args.host])

    if not args.cards and not args.deck and not args.expansion:
        logging.info('Cleaning up entire index')
        Card._index.delete(using='main', ignore=404)
        Card.init(using='main')

    load_cards(args)

    if args.locations:
        Location._index.delete(using='main', ignore=404)
        Location.init(using='main')
        load_locations()

def load_cards(args):
    meta = {}
    with open("data.yml", "r") as data_file:
        for data in yaml.safe_load_all(data_file):
            if data.get('meta'):
                meta = data
                continue
            elif not meta:
                raise ValueError('Meta must be first document')

            expansion = data['expansion']
            expansion_name = meta['expansions'].get(expansion, {}).get('name', expansion)

            if args.expansion is not None and expansion != args.expansion:
                continue

            deck = data['deck']
            deck_name = meta['decks'][deck]['name']

            if args.deck is not None and deck != args.deck:
                continue

            # Deck properties
            jump = meta['decks'][deck].get('jump')
            ability = meta['decks'][deck].get('ability')
            reckless = meta['decks'][deck].get('reckless')
            agenda = data.get('agenda')
            path = data.get('path', meta['decks'][deck].get('path', deck_name))

            # Insert with spaces for better Elastisearch tokenization
            replace = data.get('replace', meta['decks'][deck].get('replace', ' '))
            ext = data.get('ext', meta['decks'][deck].get('ext'))

            for card in data['cards']:
                if args.cards and card['name'] not in args.cards:
                    continue

                if args.cards or args.deck or args.expansion:
                    try:
                        old = Card.search(using='main') \
                            .filter("term", deck=deck) \
                            .filter("term", expansion=expansion) \
                            .query("match", name=card['name']).execute().hits[0]
                        old.delete(using='main')
                    except IndexError:
                        logging.warning("No hits for %s, watch for duplicates",
                                        card['name'])
                        pass

                count = card.get('count')
                if isinstance(count, int):
                    count = [count]

                card_path = card.get('path', card['name'])
                value = card.get('value')
                if value is not None:
                    if isinstance(value, int):
                        value = [value]
                    else:
                        card_path = f"{card_path} {card['value'][0]}"

                skills = card.get('skills',
                                  [card['skill']] if 'skill' in card else [])
                cylon = card.get('cylon')
                text = json.dumps(card.get('text', {}))
                succession = card.get('succession', {})
                default_succession = 99 if 'class' in card else None
                doc = Card(name=card['name'],
                           prefix=path,
                           path=card_path.replace(' ', replace),
                           url=card.get('url'),
                           image=card.get('image'),
                           bbox=card.get('bbox'),
                           deck=deck,
                           expansion=expansion,
                           ext=card.get('ext', ext),
                           seed=card.get('seed', {}),
                           index=card.get('index'),
                           count=count,
                           value=value,
                           destination=card.get('destination'),
                           text=text,
                           skills=skills,
                           cylon=[cylon] if isinstance(cylon, str) else cylon,
                           jump=card.get('jump', jump),
                           character_class=card.get('class'),
                           president=succession.get('president', default_succession),
                           admiral=succession.get('admiral', default_succession),
                           cag=succession.get('cag', default_succession),
                           allegiance=card.get('allegiance'),
                           ability=card.get('ability', ability),
                           reckless=card.get('reckless', reckless),
                           agenda=agenda)
                logging.debug('%r', doc.to_dict())
                doc.save(using='main')
                logging.info('Saved %s (%s card from %s)', card['name'],
                             deck_name, expansion_name)

def load_locations():
    with open("locations.yml", "r") as locations_file:
        for data in yaml.safe_load_all(locations_file):
            expansion = data['expansion']
            expansion_seed = data.get('seed', {})
            for board in data['boards']:
                board_name = board['name']
                path = board['path']
                ext = board['ext']
                seed = board.get('seed', expansion_seed)
                doc = Location(board_name=board_name,
                               path=path,
                               ext=ext,
                               name=board_name,
                               expansion=expansion,
                               seed=seed,
                               bbox=board.get('bbox'),
                               text=json.dumps({}))
                doc.save(using='main')
                logging.info('Saved %s (board from %s)',
                             board_name, expansion)
                for location in board['locations']:
                    value = location.get('value')
                    if isinstance(value, int):
                        value = [value]
                    loc = Location(board_name=board_name,
                                   path=path,
                                   ext=ext,
                                   name=location['name'],
                                   expansion=expansion,
                                   seed=seed,
                                   hazardous=location.get('hazardous', False),
                                   bbox=location.get('bbox'),
                                   value=value,
                                   skills=location.get('skills'),
                                   occupation=location.get('occupation'),
                                   text=json.dumps(location.get('text', {})))
                    logging.debug('%r', loc.to_dict())
                    loc.save(using='main')
                    logging.info('Saved %s (%s location from %s)',
                                 location['name'], board_name, expansion)

if __name__ == "__main__":
    main()
