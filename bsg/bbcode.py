import logging
from bbcode import Parser

class BBCode:
    """
    A BBCode parser that outputs text in a certain format.
    """

    def __init__(self, cards, images):
        self.cards = cards
        self.images = images
        self.game_state = ""
        self._load_parser()

    def _load_parser(self):
        raise NotImplementedError("Must be implemented by subclass")

    def _parse_color(self, tag_name, value, options, parent, context):
        return options.get(tag_name, '')

    def _parse_imageid(self, tag_name, value, options, parent, context):
        return options.get(tag_name, '').split(' ')[0]

    def process_bbcode(self, text, display='discord'):
        """
        Process a string of BBCode text to a Markdown-like format usable in
        for example Discord.
        """

        return self.cards.replace_cards(self.parser.format(text), display)

class BBCodeMarkdown(BBCode):
    """
    Markdown output for BGG BYC BBCode.
    """

    def _parse_color(self, tag_name, value, options, parent, context):
        color = super()._parse_color(tag_name, value, options, parent, context)
        if color in ("#FFFFFF", "#F4F4FF"):
            return ''

        return value

    def _parse_imageid(self, tag_name, value, options, parent, context):
        # TODO: Use something alike to bgg RSS.IMAGES to replace (or remove)
        # the image. Perhaps populate it from static analysis of the BYC script 
        # so that we can also replace the banners?
        image_id = super()._parse_imageid(tag_name, value, options, parent,
                                          context)
        logging.info('Found unknown image: %s', image_id)
        return ''

    def _parse_quote(self, tag_name, value, options, parent, context):
        quote_user = options.get(tag_name, '')
        if "BYC: Game State" in quote_user:
            parser = BBCodeHTML(self.cards, self.images)
            self.game_state += parser.process_bbcode(value)
            return ''

        return self.parser.format(value)

    def _load_parser(self):
        # Create a BBCode to discord-like Markdown parser.
        self.parser = Parser(newline="\n", install_defaults=False,
                             escape_html=False, replace_links=False,
                             replace_cosmetic=False, drop_unrecognized=False)
        self.parser.add_simple_formatter('b', '**%(value)s**')
        # Drop spoilers
        self.parser.add_simple_formatter('o', '')
        # Drop external URLs
        self.parser.add_simple_formatter('url', '')
        self.parser.add_simple_formatter('article', '%(value)s')
        # Other tags
        self.parser.add_simple_formatter('clear', '', standalone=True)
        self.parser.add_simple_formatter('hr', '', standalone=True)

        self.parser.add_simple_formatter('-', '~%(value)s~')
        self.parser.add_simple_formatter('i', '*%(value)s*')
        self.parser.add_simple_formatter('user', '@%(value)s')
        self.parser.add_simple_formatter('size', '%(value)s')

        self.parser.add_formatter('color', self._parse_color)
        self.parser.add_formatter('imageid', self._parse_imageid,
                                  standalone=True)
        self.parser.add_formatter('q', self._parse_quote, render_embedded=False)
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
        # TODO: Also preload them from the BYC script (detect imageO calls 
        # inside the textGameReport function) - will need to be able to start 
        # a download from multiple sources
        path = self.images.retrieve(image_id)
        if path is None:
            return f'<div class="img">{image_id}</div>'

        return f'<div class="img"><img src="{path.resolve().as_uri()}"></div>'

    def _parse_size(self, tag_name, value, options, parent, context):
        size = round(float(options.get(tag_name, 10)) * 1.4, 1)
        return f'<span style="font-size: {size}px">{value}</span>'

    def _load_parser(self):
        self.parser = Parser(install_defaults=False, replace_links=False,
                             replace_cosmetic=False, drop_unrecognized=False)
        self.parser.add_simple_formatter('b', '<b>%(value)s</b>')
        self.parser.add_simple_formatter('i', '<i>%(value)s</i>')
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

    def process_bbcode(self, text, display='discord'):
        return self.parser.format(text)
