import logging
import yaml

class Cards:
    def __init__(self, url):
        self.url = url
        with open("data.yml") as data:
            self.cards = yaml.safe_load(data)['cards']

        self.lookup = {}
        for card_type, cards in self.cards.items():
            for index, card in enumerate(cards['base']):
                name = card['name'].lower()
                self._add(name, card_type, index)
                self._add(name.replace(' ', ''), card_type, index)
                if 'path' in card:
                    self._add(card['path'].lower(), card_type, index)

    def _add(self, lookup, card_type, index):
        if lookup in self.lookup and self.lookup[lookup][1] != index and \
            not self.cards[card_type]['base'][index].get('alias', False):
            cur_type, cur_index = self.lookup[lookup]
            logging.debug('Duplicate lookup: %s => %d. %s (%s) =/= %d. %s (%s)',
                          lookup, index,
                          self.cards[card_type]['base'][index]['name'],
                          card_type, cur_index,
                          self.cards[cur_type]['base'][cur_index]['name'],
                          cur_type)

        self.lookup[lookup] = (card_type, index)

    def find(self, search, card_type=''):
        if card_type != '' and card_type not in self.cards:
            return None

        for option in [search.lower(), search.lower().replace(' ', '')]:
            if option in self.lookup:
                actual_type, index = self.lookup[option]
                break
        else:
            return 'No card found'

        card = self.cards[actual_type]['base'][index]
        type_name = self.cards[actual_type]['name']
        if card_type != '' and actual_type != card_type:
            return f"You selected the wrong card type: {card['name']} is actually a {type_name} card"

        type_path = self.cards[actual_type].get('path', type_name)
        ext = card.get('ext', self.cards[actual_type]['ext'])
        path = card.get('path', card['name']).replace(' ', '_')
        return f'{self.url}/{type_path}/{type_path}_{path}.{ext}'
