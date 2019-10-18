import argparse
import logging
from elasticsearch_dsl.connections import connections
import yaml
from bsg.card import Cards
from bsg.search import Card

def parse_args():
    parser = argparse.ArgumentParser(description='Command-line bot reply')
    log_options = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    parser.add_argument('--log', default='INFO', choices=log_options,
                        help='log level')
    args = parser.parse_args()
    return args

def main():
    args = parse_args()
    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s',
                        level=getattr(logging, args.log, None))

    # Define a default Elasticsearch client
    connections.create_connection(hosts=['localhost'])

    Card._index.delete(ignore=404)
    Card.init()

    meta = {}
    with open("data-documented.yml", "r") as data_file:
        for data in yaml.safe_load_all(data_file):
            if data.get('meta'):
                meta = data
                continue
            elif not meta:
                raise ValueError('Meta must be first document')

            expansion = data['expansion']
            deck = data['deck']
            deck_name = meta['decks'][deck]['name']
            jump = meta['decks'][deck].get('jump')
            path = data.get('path', meta['decks'][deck].get('path', deck_name))
            replace = data.get('replace', '_')
            ext = data.get('ext', meta['decks'][deck]['ext'])
            for card in data['cards']:
                skills = card.get('skills',
                                  [card['skill']] if 'skill' in card else [])
                text = str(card.get('text', {}))
                doc = Card(name=card['name'],
                           prefix=path,
                           path=card.get('path', card['name']).replace(' ', replace),
                           deck=deck,
                           expansion=expansion,
                           ext=card.get('ext', ext),
                           value=card.get('value'),
                           destination=card.get('destination'),
                           text=text,
                           skills=skills,
                           cylon=card.get('cylon'),
                           jump=card.get('jump', jump))
                logging.debug('%r', doc.to_dict())
                doc.save()
                logging.info('Saved %s (%s card from %s)', card['name'],
                             deck_name, expansion)

if __name__ == "__main__":
    main()
