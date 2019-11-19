import logging
from bbcode import Parser

class BBCode:
    def __init__(self, cards):
        self.cards = cards
        self.game_state = ""
        self._load_bbcode()

    def _parse_color(self, tag_name, value, options, parent, context):
        color = options.get(tag_name, '')
        if color in ("#FFFFFF", "#F4F4FF"):
            return ''

        if context.get("game_state"):
            return f'<span style="color: {color}">{value}</span>'

        return value

    def _parse_imageid(self, tag_name, value, options, parent, context):
        # TODO: Use something alike to bgg RSS.IMAGES to replace (or remove)
        # UNLESS if we are parsing a quote with game state
        image_id = options.get(tag_name, '').split(' ')[0]
        logging.info('Found unknown image: %s', image_id)
        if context.get("game_state"):
            # TODO: Retrieve images via API:
            # https://api.geekdo.com/api/images/{image_id}
            # ["images"]["original"]["url"]
            # Download to images directory under {image_id}.{ext}
            # Check if any image starting with image_id exists beforehand
            return '<div class="img"></div>'
        return ''

    def _parse_quote(self, tag_name, value, options, parent, context):
        quote_user = options.get(tag_name, '')
        if "BYC: Game State" in quote_user:
            self.game_state = self.html_parser.format(value, game_state=True)
            return ''

        return self.md_parser.format(value)

    def _parse_size(self, tag_name, value, options, parent, context):
        size = float(options.get(tag_name, 10)) * 1.4
        return f'<span style="font-size: {size}px">{value}</span>'

    def _load_bbcode(self):
        # Create a BBCode to discord-like Markdown parser.
        self.md_parser = Parser(newline="\n", install_defaults=False,
                                escape_html=False, replace_links=False,
                                replace_cosmetic=False, drop_unrecognized=False)
        self.md_parser.add_simple_formatter('b', '**%(value)s**')
        # Drop spoilers
        self.md_parser.add_simple_formatter('o', '')
        # Drop external URLs
        self.md_parser.add_simple_formatter('url', '')
        self.md_parser.add_simple_formatter('article', '%(value)s')
        # Other tags
        self.md_parser.add_simple_formatter('clear', '', standalone=True)
        self.md_parser.add_simple_formatter('hr', '', standalone=True)

        self.md_parser.add_simple_formatter('-', '~%(value)s~')
        self.md_parser.add_simple_formatter('i', '*%(value)s*')
        self.md_parser.add_simple_formatter('user', '@%(value)s')
        self.md_parser.add_simple_formatter('size', '%(value)s')

        self.md_parser.add_formatter('color', self._parse_color)
        self.md_parser.add_formatter('imageid', self._parse_imageid,
                                     standalone=True)
        self.md_parser.add_formatter('q', self._parse_quote,
                                     render_embedded=False)
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
        #
        # - #FFFFFF or #F4F4FF (Seed) -> to separate context
        #

        self.html_parser = Parser(install_defaults=False, replace_links=False,
                                  replace_cosmetic=False,
                                  drop_unrecognized=False)
        self.html_parser.add_simple_formatter('b', '<b>%(value)s</b>')
        self.html_parser.add_simple_formatter('i', '<i>%(value)s</i>')
        self.html_parser.add_formatter('size', self._parse_size)
        self.html_parser.add_formatter('color', self._parse_color)
        self.html_parser.add_formatter('imageid', self._parse_imageid,
                                       standalone=True)
        self.html_parser.add_simple_formatter('floatleft',
                                              '<div class="fl">%(value)s</div>')
        self.html_parser.add_simple_formatter('floatright',
                                              '<div class="fr">%(value)s</div>')
        self.html_parser.add_simple_formatter('center',
                                              '<div class="ac">%(value)s</div>')
        self.html_parser.add_simple_formatter('clear',
                                              '<div class="clear"></div>',
                                              standalone=True)
        self.md_parser.add_simple_formatter('hr', '<hr>', standalone=True)

    def process_bbcode(self, text, display='discord'):
        """
        Process a string of BBCode text to a Markdown-like format usable in
        for example Discord.
        """

        return self.cards.replace_cards(self.md_parser.format(text), display)
