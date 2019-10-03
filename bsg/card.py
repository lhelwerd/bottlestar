import logging
import re
import yaml

class Cards:
    def __init__(self, url):
        self.url = url
        with open("data.yml") as data:
            self.cards = yaml.safe_load(data)['cards']

        self.lookup = {}
        self.card_types = {}
        self.skill_types = {}

        self._load()

        self.skill_colors = [
            (self.build_skill_regex('Leadership'), ':green_apple:'),
            (self.build_skill_regex('Tactics'), ':octopus:'),
            (self.build_skill_regex('Politics'), ':prince:'),
            (self.build_skill_regex('Piloting'), ':airplane_small:'),
            (self.build_skill_regex('Engineering'), ':large_blue_diamond:')
        ]

    def build_skill_regex(self, skill_type):
        skill_cards = '|'.join(self.skill_types.get(skill_type, set()))
        if skill_cards == '':
            return re.compile(f'({skill_type})')

        return re.compile(f'({skill_type}|{skill_cards})')

    def _load(self):
        for card_type, cards in self.cards.items():
            for index, card in enumerate(cards['base']):
                self.card_types.setdefault(card_type, set())
                self.card_types[card_type].add(card['name'])
                if 'skill' in card:
                    self.skill_types.setdefault(card['skill'], set())
                    self.skill_types[card['skill']].add(card['name'])

                name = card['name'].lower()
                self._add(name, card_type, index, 0)
                self._add(name.replace(' ', ''), card_type, index, 1)
                for word_count, part in enumerate(name.split(' ')):
                    self._add(part, card_type, index, 2 + word_count)
                if 'path' in card:
                    self._add(card['path'].lower(), card_type, index, 1)

    def _add(self, lookup, card_type, index, priority):
        if lookup in self.lookup and self.lookup[lookup][1] != index and \
            not self.cards[card_type]['base'][index].get('alias', False) and \
            priority > self.lookup[lookup][2]:
            cur_type, cur_index, cur_priority = self.lookup[lookup]
            logging.debug('Duplicate lookup: %s => %d. %s (%s) =/= %d. %s (%s)',
                          lookup, priority,
                          self.cards[card_type]['base'][index]['name'],
                          card_type, cur_priority,
                          self.cards[cur_type]['base'][cur_index]['name'],
                          cur_type)
            return

        self.lookup[lookup] = (card_type, index, priority)

    def find(self, search, card_type=''):
        if card_type != '' and card_type not in self.cards:
            return None

        for option in [search.lower(), search.lower().replace(' ', '')]:
            if option in self.lookup:
                actual_type, index = self.lookup[option][:2]
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

    def replace_cards(self, message):
        for skill_regex, emoji in self.skill_colors:
            message = skill_regex.sub(r'\1' + emoji, message)

        return message
