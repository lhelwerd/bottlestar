import logging
import re
import yaml

class Cards:
    DECKS = ('base', 'pegasus', 'exodus', 'daybreak')

    def __init__(self, url):
        self.url = url
        with open("data.yml") as data_file:
            data = yaml.safe_load(data_file)
            self.cards = data['cards']
            self.skills = data['skills']

        self.lookup = {}
        self.card_types = {}
        self.skill_types = {}

        self._load()

        self.skill_colors = dict([
            (skill_type, self._build_skill_regex(skill_type))
            for skill_type in self.skills.keys()
        ])
        self.card_regex = dict([
            (card_type, re.compile('(' + self._build_regex(cards) + ')'))
            for card_type, cards in self.card_types.items()
        ])

    @staticmethod
    def _build_regex(options):
        return '|'.join(re.escape(card) for card in options)

    def _build_skill_regex(self, skill_type):
        skill_cards = self._build_regex(self.skill_types.get(skill_type, set()))
        if skill_cards == '':
            return re.compile(fr'\b({skill_type})\b')

        return re.compile(fr'\b({skill_type}|{skill_cards})\b')

    def _load(self):
        for card_type, cards in self.cards.items():
            for deck in self.DECKS:
                for index, card in enumerate(cards.get(deck, [])):
                    self._add_card(card_type, deck, index, card)

    def _add_card(self, card_type, deck, index, card):
        self.card_types.setdefault(card_type, set())
        self.card_types[card_type].add(card['name'])
        if 'skill' in card:
            self.skill_types.setdefault(card['skill'], set())
            self.skill_types[card['skill']].add(card['name'])

        name = card['name'].lower()
        self._add(name, card_type, deck, index, 0)
        self._add(name.replace(' ', ''), card_type, deck, index, 1)
        for word_count, part in enumerate(name.split(' ')):
            self._add(part, card_type, deck, index, 2 + word_count)
        if 'path' in card:
            self._add(card['path'].lower(), card_type, deck, index, 1)

    def _add(self, lookup, card_type, deck, index, priority):
        if lookup in self.lookup and self.lookup[lookup][1] != index and \
            not self.cards[card_type][deck][index].get('alias', False) and \
            priority > self.lookup[lookup][2]:
            cur_type, cur_deck, cur_index, cur_priority = self.lookup[lookup]
            logging.debug('Duplicate lookup: %s => %d. %s (%s) =/= %d. %s (%s)',
                          lookup, priority,
                          self.cards[card_type][deck][index]['name'],
                          card_type, cur_priority,
                          self.cards[cur_type][cur_deck][cur_index]['name'],
                          cur_type)
            return

        self.lookup[lookup] = (card_type, deck, index, priority)

    def find(self, search, card_type=''):
        if card_type != '' and card_type not in self.cards:
            return None

        for option in [search.lower(), search.lower().replace(' ', '')]:
            if option in self.lookup:
                actual_type, deck, index = self.lookup[option][:3]
                break
        else:
            return 'No card found'

        card = self.cards[actual_type][deck][index]
        if card_type != '' and actual_type != card_type:
            type_name = self.cards[actual_type]['name']
            return f"You selected the wrong card type: {card['name']} is actually a {type_name} card"

        return self.get_url(card, actual_type, deck)

    def get_url(self, card, card_type, deck):
        type_name = self.cards[card_type]['name']
        type_path = self.cards[card_type].get('path', type_name).replace(' ', '_')
        ext = card.get('ext', self.cards[card_type]['ext'])
        if isinstance(ext, dict):
            ext = ext.get(deck, ext['default'])
        replace = self.cards[card_type].get('replace', {'default': '_'})
        replacement = replace.get(deck, replace['default'])
        path = card.get('path', card['name']).replace(' ', replacement)
        if 'skill' in card:
            skill = self.skills.get(card['skill'], {})
            skill_path = skill.get('path', card['skill'])
            path = f"{skill_path}_{path}"
        if 'value' in card and not isinstance(card['value'], int):
            path = f"{path}_{card['value'][0]}"

        return f'{self.url}/{type_path}/{type_path}_{path}.{ext}'

    def replace_cards(self, message, display='discord'):
        for skill_type, skill_regex in self.skill_colors.items():
            emoji = self.skills[skill_type][display]
            message = skill_regex.sub(fr"\1{emoji}", message)
        for card_type, card_regex in self.card_regex.items():
            if card_type not in ('skill', 'char'):
                replacement = fr"\1 ({self.cards[card_type]['name']})"
                message = card_regex.sub(replacement, message)

        return message
