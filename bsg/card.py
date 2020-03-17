from collections import OrderedDict
import json
import logging
import re
import yaml
from .search import Card

class Cards:
    TEXT_PARSERS = {
        'choice': lambda text: f"\n**{text} Chooses:** ",
        'top': lambda text: text,
        'bottom': lambda text: f"\n**OR:** {text}",
        'pass': lambda text: f"\n**Pass:** {text}",
        'partial': ('list', lambda items: f"\n**{items[0]}:** {items[1]}"),
        'fail': lambda text: f"\n**Fail:** {text}",
        'consequence': lambda text: f"\n**Consequence:** {text}",
        'activate': ('list', lambda text: f"""\n**1. Activate:** {', '.join(
            [text] if isinstance(text, str) else text
        )}"""),
        'setup': {
            'char': lambda text: f"\nSetup: {text}",
            'ally': lambda text: f"\n*{text}*",
            'default': ('dict', lambda items: f"""\n**2. Setup:** {', '.join([
                str(value) + " " + (key[:-1] if value == 1 else key)
                for key, value in items.items()
            ])}""")
        },
        'special': lambda text: f"\n**3. Special Rule** - {text}",
        'skillset': ('dict', lambda items: f"""\n{', '.join([
            str(value) + " " + key.title() for key, value in items.items()
        ])}""")
    }

    def __init__(self, url):
        self.url = url
        self.decks = {}
        self.skills = {}
        self.expansions = {}
        self.character_classes = {}
        self.titles = {}
        self.loyalty = {}
        self.activations = {}

        with open("data.yml") as data_file:
            for data in yaml.safe_load_all(data_file):
                if data.get('meta'):
                    self.expansions = data['expansions']
                    self.decks = data['decks']
                    self.skills = data['skills']
                    self.character_classes = data['character_classes']
                    self.titles = data['titles']
                    self.loyalty = data['loyalty']
                    self.activations = data['activations']
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
            .filter("term", skills=skill_type.lower())
        skill_cards = self._build_regex(card.name for card in search.scan())
        logging.info('%s %s', skill_type, skill_cards)
        if skill_cards == '':
            return re.compile(fr'\b({skill_type})\b')

        return re.compile(fr'\b({skill_type}|{skill_cards})\b')

    def _build_deck_regex(self, deck):
        search = Card.search(using='main').filter("term", deck=deck)
        return self._build_regex(card.name for card in search.scan())

    def get_url(self, card):
        url = card.get('url')
        if url is not None:
            return url

        card_deck = card.get('deck', 'board')
        default_deck = {
            'name': card_deck,
            'ext': 'png'
        }
        deck = self.decks.get(card_deck, default_deck)
        deck_name = deck['name']
        deck_path = deck.get('path', deck_name).replace(' ', '_')
        ext = card.get('ext', deck['ext'])
        if ext != '':
            ext = f".{ext}"
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
        prefix = card.get('prefix', deck.get('prefix', deck_path))
        if prefix != '':
            prefix = prefix.replace(' ', '_') + '_'

        return f'{self.url}/{deck_path}/{prefix}{path}{ext}'

    def _parse_text(self, text, key="", deck="default"):
        parser = None
        if key in self.TEXT_PARSERS:
            parser = self.TEXT_PARSERS[key]
            if isinstance(parser, dict):
                parser = parser.get(deck, parser["default"])
            if isinstance(parser, tuple):
                parser = parser[1]
                return parser(text)

        if isinstance(text, OrderedDict):
            result = ''.join([
                self._parse_text(subtext, subkey, deck)
                for subkey, subtext in text.items()
            ])
        else:
            if isinstance(text, list):
                if deck == "board":
                    text = "".join([
                        self._parse_text(subtext, "", deck) for subtext in text
                    ]).lstrip("\n")
                elif len(text) == 2 and deck != "location":
                    text = f"**{text[0]}:** {text[1]}"
                else:
                    text = "\n".join(text)

            if key != "" and key[0].isupper():
                separator = self.decks.get(deck, {}).get("separator", ":")
                result = f"\n**{key}{separator}** {text}"
            else:
                result = f"\n{text}"

        if parser is not None:
            return parser(result.lstrip("\n"))

        return result

    def _get_short_skills(self, skills):
        return ''.join([
            self.skills.get(skill, {}).get("short", skill[0])
            for skill in skills
        ])

    def get_card_header(self, card):
        deck = self.decks.get(card.deck, {})
        msg = f"{deck.get('name', card.deck)}: "
        if card.allegiance is not None and card.deck == "loyalty":
            if card.allegiance == "Cylon":
                yaac = "You Are a Cylon"
            else:
                yaac = "You Are Not a Cylon"
            if yaac != card.name:
                msg += f"**{yaac}**\n"
        msg += f"**{card.name}**"
        if card.character_class is not None:
            msg += f" ({card.character_class})"
        if card.value is not None:
            msg += f" - [{'|'.join(str(value) for value in card.value)}]"
        if card.jump is not None:
            if card.skills is not None:
                msg += self._get_short_skills(card.skills)

            if card.cylon is not None:
                activations = ''.join([
                    self.activations.get(cylon, cylon[0])
                    for cylon in card.cylon
                ])
            else:
                activations = "-"

            extra = f" ({activations}/{'*' if card.jump else '-'})"
            if extra != " (-/-)" and not card.name.endswith(extra):
                msg += extra
        elif card.skills is not None:
            msg += f" ({card.skills[0]})"

        if card.count is not None:
            msg += ",".join(f" {count}\u00d7" for count in card.count)

        if card.allegiance is not None and card.deck != "loyalty":
            msg += f"\n**Allegiance: {card.allegiance}**"

        if card.reckless:
            msg += f"\n**Reckless**"

        return msg

    def get_text(self, card):
        expansion = self.expansions.get(card.expansion, {}).get("prefix", "BSG")
        msg = f"{expansion} "
       
        if isinstance(card, Card):
            msg += self.get_card_header(card)
            deck = card.deck
        else:
            msg += f"{card.board_name}: **{card.name}**"
            if card.value is not None:
                skills = self._get_short_skills(card.skills)
                msg += f" - {card.value[0]}{skills}"
            deck = "board"

        try:
            data = json.loads(card.text, object_pairs_hook=OrderedDict)
            msg += self._parse_text(data, deck=deck)
        except ValueError:
            logging.exception("Not actually json")
            msg += f"\n{card.text}"

        if isinstance(card, Card) and card.destination is not None:
            msg += f"\n( {card.destination} )"

        return msg

    def replace_cards(self, message, display='discord', deck=True):
        if display != '':
            for skill_type, skill_regex in self.skill_colors.items():
                emoji = self.skills[skill_type][display]
                message = skill_regex.sub(fr"\1{emoji}", message)
            for key, title in self.titles.items():
                message = re.sub(rf"\b{key}\b(?!['-])",
                                 f"{key}{title[display]}", message)

        if deck:
            for deck, card_regex in self.deck_cards.items():
                replacement = fr"\1 ({self.decks[deck]['name']})"
                message = card_regex.sub(replacement, message)

        return message

    def find_expansion(self, arguments):
        lower_arguments = [argument.lower() for argument in arguments]
        for expansion, data in self.expansions.items():
            if expansion in lower_arguments:
                arguments.pop(lower_arguments.index(expansion))
                return expansion
            if data['prefix'].lower() in lower_arguments:
                arguments.pop(lower_arguments.index(data['prefix'].lower()))
                return expansion

        return ''

    @staticmethod
    def _format_succession(title, index, char, cylons, locations):
        name, match = re.subn(fr'"?{re.escape(char.path)}"?',
                              char.path, char.name, count=1)
        if not match:
            name = f"{char.name} ({char.path})"

        line = f"{index}. {name}"
        if cylons.get(char.path):
            line = f"~~{line}~~"
        elif title != "President" and locations.get(char.path) == "Brig":
            line = f"{line} (Brig)"

        return line

    def lines_of_succession(self, chars, cylons, locations):
        titles = sorted((title for title, data in self.titles.items()
                         if 'titles' not in data),
                        key=lambda title: self.titles[title]['priority'])
        report = []
        for title in titles:
            line = sorted(chars, key=lambda char: getattr(char, title.lower()))
            names = "\n".join(
                self._format_succession(title, index + 1, char, cylons, locations)
                for index, char in enumerate(line)
            )
            report.append(f"{title}:\n{names}")

        return "\n\n".join(report)
