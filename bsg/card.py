from collections import OrderedDict
import json
import logging
import re
import yaml
from .search import Card

class Cards:
    TEXT_PARSERS = {
        'flavor': lambda text: f"\n*{text}*",
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
                str(value) + " " + (key[:-1] if value == 1 and key[-1] == "s" else key)
                for key, value in items.items()
            ])}""")
        },
        'special': ('list', lambda text: f"\n**3. Special Rule** - *{text[0]}*: {text[1]}"),
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

        image_id = card.get('image')
        if image_id is not None:
            # We cannot generate a stable URL to the image itself without API
            return ""

        card_deck = card.get('deck', 'board')
        deck = self.decks.get(card_deck, {})
        deck_name = deck.get('name', card_deck)
        replace = deck.get('replace', '_')
        deck_path = deck.get('path', deck_name).replace(' ', replace)
        ext = card.get('ext', deck.get('ext', 'png'))
        if ext != '':
            ext = f".{ext}"
        path = card.get('path', card['name'])
        if 'skills' in card and len(card['skills']) == 1:
            skill = self.skills.get(card['skills'][0], {})
            skill_path = skill.get('path', card['skills'][0])
            if isinstance(skill_path, dict):
                skill_path = skill_path.get(card['expansion'],
                                            skill_path['default'])

            path = f"{skill_path}_{path}"

        path = path.replace(' ', card.get('replace', replace))

        # Usually the deck path is repeated in each file name, but not always
        prefix = card.get('prefix', deck.get('prefix', deck_path))
        if prefix != '':
            prefix = prefix.replace(' ', '_') + '_'

        return f'{self.url}/{deck_path}/{prefix}{path}{ext}'

    @classmethod
    def is_exact_match(cls, card, lower_text):
        """
        Test if the card is an "exact match" to the provided lowercase text.
        """

        return card.name.lower() == lower_text or \
            card.path.lower() == lower_text

    def _parse_list(self, text, key="", deck="default"):
        result = []
        for subtext in text:
            subtext = self._parse_text(subtext, '- ', deck).lstrip('\n')
            if key != "" and not key[0].isupper():
                subtext = f"{key}{subtext}"
            result.append(subtext)

        return "\n".join(result)

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
                if deck in ("board", "title"):
                    text = self._parse_list(text, key, deck)
                elif len(text) == 2 and deck != "location":
                    text = f"**{text[0]}:** {text[1]}"
                else:
                    text = "\n".join(text)

            if key != "" and (key[0].isupper() or key.isnumeric()):
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

    def get_card_title(self, card):
        msg = f"**{card.name}**"
        if card.agenda is not None:
            msg += f" ({card.agenda})"
        if card.character_class is not None:
            msg += f" ({card.character_class})"
        if card.value is not None:
            if len(card.value) > 1:
                msg += f" - [{'|'.join(str(value) for value in card.value)}]"
            else:
                msg += f" - {card.value[0]}"
        if card.skills is not None:
            if len(card.skills) > 1:
                msg += self._get_short_skills(card.skills)
            else:
                msg += f" ({card.skills[0]})"
        if card.jump is not None:
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

        return msg

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

        msg += self.get_card_title(card)
        if card.count is not None:
            msg += ",".join(f" {count}\u00d7" for count in card.count)

        if card.allegiance is not None:
            if card.deck == "agenda" and card.text:
                team = "Cylons" if card.allegiance == "Cylon" else "humans"
                msg += "\n**You Win the Game if:**"
                msg += f"\nThe {team} have won.\n***and***"
            elif card.deck == "title" and card.allegiance == "Infiltrator":
                msg += "\n**You Are Infiltrating**"
            elif card.deck != "loyalty":
                msg += f"\n**Allegiance: {card.allegiance}**"

        if card.deck == "objective":
            msg += "\nResolve when the following distance is traveled:"

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
            if card.board_name == card.name:
                msg += f"**{card.name}**"
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
        if len(arguments) == 1:
            return ''

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

        if getattr(char, title.lower()) == 99:
            return f"{name} (Cylon Leader)"

        line = f"{index}. {name}"
        if cylons.get(char.path):
            line = f"~~{line}~~"
        elif title != "President" and locations.get(char.path) == "Brig":
            line = f"{line} (Brig)"

        return line

    def lines_of_succession(self, seed):
        players = seed.get("players", [])
        search = Card.search(using='main') \
            .filter("term", deck="char") \
            .filter("terms", path__raw=players)
        chars = list(search.scan())
            
        cylons = {
            player: cylon
            for player, cylon in zip(players, seed.get("revealedCylons", []))
        }
        locations = {
            player: location
            for player, location in zip(players, seed.get("playerLocations", []))
        }

        titles = sorted((title for title, data in self.titles.items()
                         if 'titles' not in data and (
                             'condition' not in data or seed.get(data['condition'])
                        )),
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

    def analyze(self, seed, display='discord'):
        replacements = {
            "discord": "\\*"
        }
        replacement = replacements.get(display, '*')
        report = []
        for deck, data in self.decks.items():
            if 'seed' not in data or 'analyze' not in data:
                # Seed does not support analysis of this deck
                continue

            if data['seed'] not in seed:
                # Game does not contain this deck (expansion/variant)
                logging.info("%s not in seed", data['seed'])
                continue

            indexes = seed[data['seed']][:-data['analyze']-1:-1]
            search = Card.search(using='main') \
                .filter("term", deck=deck) \
                .filter("terms", index=list(range(0, max(indexes) + 1)))

            lookup = {}
            for card in search.scan():
                if deck == "skill" and "Treachery" in card.skills and \
                    ((card.expansion == "pegasus" and seed.get('daybreak')) or \
                    (card.expansion == "daybreak" and not seed.get('daybreak'))):
                        # Pegasus/Daybreak Treachery decks
                        continue

                name = self.get_card_title(card).replace('**', '') \
                    .replace('*', replacement)
                if card.count is not None and card.value is not None:
                    # Skill deck
                    offset = card.index
                    for value, count in zip(card.value, card.count):
                        lookup.update({index: f"{value} - {card.name}" for index in range(offset, offset + count)})
                        offset += count
                elif card.count is not None:
                    lookup.update({index: name for index in range(card.index, card.index + card.count[0])})
                else:
                    lookup[card.index] = name

            if all(index not in lookup for index in indexes):
                # Could not find any cards from the seed in our data
                # This can happen when crisis deck is replaced with NC crisis
                logging.info("None of the %s indexes found: %r", deck, indexes)
                continue

            count = len(indexes)
            name = data.get("analysis_title", data['name'])
            names = ", ".join(lookup.get(index, "???") for index in indexes)
            report.append(f"The top {count} cards of the {name} deck:\n{names}")

        return "\n\n".join(report)
