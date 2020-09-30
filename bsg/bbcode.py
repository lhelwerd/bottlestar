import logging
import re
from pathlib import PurePath
from bbcode import Parser

class BBCode:
    """
    A BBCode parser that outputs text in a certain format.
    """

    def __init__(self, images):
        self.images = images
        self.parser = None
        self._load_parser()

    def _reset(self):
        self._quotes = {
            "game_state": "",
            "interrupts": [],
            "skill_checks": [],
            "state_of_emergency": []
        }
        self.bold_text = []

    def _load_parser(self):
        raise NotImplementedError("Must be implemented by subclass")

    def _parse_color(self, tag_name, value, options, parent, context):
        return options.get(tag_name, '')

    def _parse_imageid(self, tag_name, value, options, parent, context):
        return options.get(tag_name, '').split(' ')[0]

    def process_bbcode(self, text):
        """
        Process a string of BBCode text to a Markdown-like format usable in
        for example Discord.
        """

        self._reset()
        return self.parser.format(text)

    @property
    def game_state(self):
        return self._quotes["game_state"]

    @property
    def interrupts(self):
        return self._quotes["interrupts"]

    @property
    def skill_checks(self):
        return self._quotes["skill_checks"]

    @property
    def state_of_emergency(self):
        return self._quotes["state_of_emergency"]

class BBCodeMarkdown(BBCode):
    """
    Markdown output for BGG BYC BBCode.
    """

    _token_patterns = {
        "topic": re.compile(r"^\*\*(?:Interrupts for )?\**(?P<topic>[^\*]+)\*\*$"),
        "possibilities": re.compile(r"^(?:Looking for |and/or .* the following:)(?P<possibilities>.*)$"),
        "player": re.compile(r"^(?P<bold>\**)?(?P<name>[^(]+)(?P=bold) \((?P<count>\d+)\) -\s*(?P<action>.*)$")
    }

    def _parse_bold(self, tag_name, value, options, parent, context):
        self.bold_text.append(value)
        return f"**{value}**"

    def _parse_color(self, tag_name, value, options, parent, context):
        color = super()._parse_color(tag_name, value, options, parent, context)
        if color in ("#FFFFFF", "#F4F4FF"):
            return ''

        return value

    def _parse_imageid(self, tag_name, value, options, parent, context):
        image_id = super()._parse_imageid(tag_name, value, options, parent,
                                          context)
        text = self.images.retrieve(image_id, download=False)
        if text is not None and not isinstance(text, PurePath):
            return text

        logging.info('Found unknown image: %s', image_id)
        return ''

    def _parse_quote_token(self, text, group):
        token = {
            "topic": "",
            "possibilities": "",
            "players": []
        }
        for line in text.split('\n'):
            for pattern in self._token_patterns.values():
                match = pattern.match(line)
                if match:
                    groups = match.groupdict()
                    if len(groups) == 1:
                        key, value = groups.popitem()
                        token[key] += value
                    else:
                        token["players"].append(groups)

                    break

        self._quotes[group].append(token)

    def _parse_quote(self, tag_name, value, options, parent, context):
        quote_user = options.get(tag_name, '')
        if "BYC: Game State" in quote_user:
            parser = BBCodeHTML(self.images)
            self._quotes["game_state"] += parser.process_bbcode(value)
            return ''

        text = self.parser.format(value)
        if "BYC: Interrupts for" in quote_user or "BYC: Declare Emergency" in quote_user:
            self._parse_quote_token(text, "interrupts")
        elif "BYC: State of Emergency" in quote_user:
            self._parse_quote_token(text, "state_of_emergency")
        elif "BYC: " in quote_user:
            self._parse_quote_token(text, "skill_checks")

        return text

    def _load_parser(self):
        # Create a BBCode to discord-like Markdown parser.
        self.parser = Parser(newline="\n", install_defaults=False,
                             escape_html=False, replace_links=False,
                             replace_cosmetic=False, drop_unrecognized=False)
        self.parser.add_formatter('b', self._parse_bold)
        # Drop code and spoilers
        self.parser.add_simple_formatter('c', '')
        self.parser.add_simple_formatter('o', '')
        # Drop external URLs
        self.parser.add_simple_formatter('url', '%(value)s')
        self.parser.add_simple_formatter('article', '%(value)s')
        # Other tags
        self.parser.add_simple_formatter('clear', '', standalone=True)
        self.parser.add_simple_formatter('hr', '', standalone=True)

        self.parser.add_simple_formatter('-', '~%(value)s~')
        self.parser.add_simple_formatter('i', '*%(value)s*')
        self.parser.add_simple_formatter('user', '%(value)s')
        self.parser.add_simple_formatter('size', '%(value)s')

        self.parser.add_formatter('color', self._parse_color)
        self.parser.add_formatter('imageid', self._parse_imageid,
                                  standalone=True)
        self.parser.add_formatter('q', self._parse_quote, render_embedded=False)

        for tag, options in self.parser.recognized_tags.values():
            options.escape_html = False
            options.replace_links = False
            options.replace_cosmetic = False

        # Colors:
        # - red (Cylon)
        # - green (Human PG)
        # - darkgreen (Final Five PG)
        # - blue (Human Agenda)
        # - brown (Cylon Agenda/Cylon Allegiance)
        #
        # - yellow (Politics)
        # - green (Leadership)
        # - purple (Tactics)
        # - red (Piloting)
        # - blue (Engineering)
        # - brown (Treachery)

    def process_bbcode(self, text):
        return super().process_bbcode(text).replace('****', '')

class BBCodeHTML(BBCode):
    """
    HTML output for BGG BYC BBCode.
    """

    def _parse_color(self, tag_name, value, options, parent, context):
        color = super()._parse_color(tag_name, value, options, parent, context)
        return f'<span style="color: {color}">{value}</span>'

    def _parse_imageid(self, tag_name, value, options, parent, context):
        image_id = super()._parse_imageid(tag_name, value, options, parent,
                                          context)
        # Retrieve images via API
        path = self.images.retrieve(image_id)
        if isinstance(path, PurePath):
            return f'<div class="img"><img src="{path.resolve().as_uri()}"></div>'
        if path is None:
            return f'<div class="img">{image_id}</div>'

        return path

    def _parse_size(self, tag_name, value, options, parent, context):
        size = round(float(options.get(tag_name, 10)) * 1.4, 1)
        return f'<span style="font-size: {size}px">{value}</span>'

    def _load_parser(self):
        self.parser = Parser(install_defaults=False, replace_links=False,
                             replace_cosmetic=False, drop_unrecognized=False)
        self.parser.add_simple_formatter('b', '<b>%(value)s</b>')
        self.parser.add_simple_formatter('i', '<i>%(value)s</i>')
        self.parser.add_simple_formatter('c', '<code>%(value)s</code>')
        self.parser.add_formatter('size', self._parse_size)
        self.parser.add_formatter('color', self._parse_color)
        self.parser.add_formatter('imageid', self._parse_imageid,
                                  standalone=True)
        self.parser.add_simple_formatter('floatleft',
                                         '<div class="fl">%(value)s</div>')
        self.parser.add_simple_formatter('floatright',
                                         '<div class="fr">%(value)s</div>')
        self.parser.add_simple_formatter('center',
                                         '<div class="ac">%(value)s</div>')
        self.parser.add_simple_formatter('clear', '<div class="clear"></div>',
                                         standalone=True)
        self.parser.add_simple_formatter('hr', '<hr>', standalone=True)

        for tag, options in self.parser.recognized_tags.values():
            options.replace_links = False
            options.replace_cosmetic = False
