import logging
import re
import yaml
from .search import Card

class Cards:
    DECKS = ('base', 'pegasus', 'exodus', 'daybreak')

    def __init__(self, url):
        self.url = url
        self.decks = {}
        self.skills = {}
        self.expansions = set()

        with open("data.yml") as data_file:
            for data in yaml.safe_load_all(data_file):
                if data.get('meta'):
                    self.expansions = set('expansions')
                    self.decks = data['decks']
                    self.skills = data['skills']
                    break
                else:
                    raise ValueError('Meta must be first component')

        self._skill_colors = None
        self._deck_cards = None

    @property
    def skill_colors(self):
        if self._skill_colors is None:
            self._skill_colors = dict([
                (skill_type, self._build_skill_regex(skill_type))
                for skill_type in self.skills.keys()
            ])

        return self._skill_colors

    @property
    def deck_cards(self):
        if self._deck_cards is None:
            self._deck_cards = dict([
                (deck, re.compile('(' + self._build_deck_regex(deck) + ')'))
                for deck, data in self.decks.items() if data.get('denote', True)
            ])

        return self._deck_cards

    @staticmethod
    def _build_regex(options):
        return '|'.join(re.escape(card) for card in options)

    def _build_skill_regex(self, skill_type):
        search = Card.search(using='main').filter("term", deck="skill") \
            .filter("term", skill=skill_type)
        skill_cards = self._build_regex(card.name for card in search.scan())
        if skill_cards == '':
            return re.compile(fr'\b({skill_type})\b')

        return re.compile(fr'\b({skill_type}|{skill_cards})\b')

    def _build_deck_regex(self, deck):
        search = Card.search(using='main').filter("term", deck=deck)
        return self._build_regex(card.name for card in search.scan())

    def get_url(self, card):
        default_deck = {
            'name': card['deck'],
            'ext': 'png'
        }
        deck = self.decks.get(card['deck'], default_deck)
        deck_name = deck['name']
        deck_path = deck.get('path', deck_name).replace(' ', '_')
        ext = card.get('ext', deck['ext'])
        replacement = deck.get('replace', '_')
        path = card.get('path', card['name'])
        if 'skills' in card and len(card['skills']) == 1:
            skill = self.skills.get(card['skills'][0], {})
            skill_path = skill.get('path', card['skills'][0])
            if isinstance(skill_path, dict):
                skill_path = skill_path.get(card['expansion'],
                                            skill_path['default'])

            path = f"{skill_path}_{path}"

        path = path.replace(' ', replacement)

        # Usually the deck path is repeated in each file name, but not always
        prefix = card.get('prefix', deck_path).replace(' ', '_')
        if prefix != '':
            prefix = prefix + '_'

        return f'{self.url}/{deck_path}/{prefix}{path}.{ext}'

    def replace_cards(self, message, display='discord'):
        for skill_type, skill_regex in self.skill_colors.items():
            emoji = self.skills[skill_type][display]
            message = skill_regex.sub(fr"\1{emoji}", message)
        for deck, card_regex in self.deck_cards.items():
            replacement = fr"\1 ({self.decks[deck]['name']})"
            message = card_regex.sub(replacement, message)

        return message
