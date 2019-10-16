from elasticsearch_dsl.connections import connections
import yaml
from bsg.card import Cards
from bsg.search import Card

# Define a default Elasticsearch client
connections.create_connection(hosts=['localhost'])

Card._index.delete(ignore=404)
Card.init()

with open("data-extended.yml", "r") as data_file:
    data = yaml.safe_load(data_file)
    for card_type, cards in data['cards'].items():
        jump = False if card_type == 'crisis' else None
        for deck in Cards.DECKS:
            for card in cards.get(deck, []):
                skills = card.get('skills',
                                  [card['skill']] if 'skill' in card else [])
                text = str(card.get('text', {}))
                doc = Card(name=card['name'],
                           path=card.get('path'),
                           card_type=card_type,
                           deck=deck,
                           value=card.get('value'),
                           destination=card.get('destination'),
                           text=text,
                           skills=skills,
                           cylon=card.get('cylon'),
                           jump=card.get('jump', jump))
                print(doc.to_dict())
                doc.save()
