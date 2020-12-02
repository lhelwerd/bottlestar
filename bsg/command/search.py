"""
Search commands for card and location texts.
"""

import logging
from pathlib import Path, PurePath
from expression import Expression_Parser
from .base import Command
from ..card import Cards
from ..image import Images
from ..search import Card, Location
from ..thread import Thread

class SearchCommand(Command):
    DEFAULT_LIMIT = 3
    SUGGESTION_PERCENT = .60

    def __init__(self, name, context):
        super().__init__(name, context)
        self.cards = Cards(self.context.config['cards_url'])
        self.images = Images(self.context.config['api_url'])
        self.parser = None

    def search(self, text, limit):
        raise NotImplementedError("Must be implemented by subclasses")
        
    def get_paths(self, hit):
        """
        Retrieve filename, path and target image path (for cropping operations)
        for the search hit.
        """
        filename = f"{hit.expansion}_{hit.path}.{hit.ext}"
        path = Path(f"images/{filename}")
        return filename, path, path

    def check_seed(self, seed, fields):
        if '_expr' in fields:
            if self.parser is None:
                self.parser = Expression_Parser(variables=seed)
            try:
                if not self.parser.parse(fields['_expr']):
                    return False
            except SyntaxError:
                logging.exception('Invalid seed expression')

            if fields.get('_alternate') in seed['players']:
                return False
        else:
            for key, value in fields.items():
                seed_value = seed.get(key, value)
                if seed_value != value and not \
                    (isinstance(value, list) and seed_value in value):
                    return False

        return True

    async def run(self, text="", limit=None, **kw):
        show_all = False
        if limit is None:
            limit = self.DEFAULT_LIMIT
        else:
            show_all = True

        result = None
        hidden = []
        suggestions = []
        lower_text = text.lower()
        response, count = self.search(text, limit)

        if count == 0:
            await self.context.send("No card found")
            return

        seed = None
        for index, hit in enumerate(response):
            if show_all:
                await self.show_search_result(hit, count, hidden, [])

            # Check if the seed constraints may hide this result
            if hit.seed:
                if seed is None:
                    thread = Thread(self.context.config['api_url'])
                    seed = thread.retrieve(self.context.config['thread_id'],
                                           download=False)[1]

                # Seed may not be locally available at this point
                if seed is not None:
                    if not self.check_seed(seed, hit.seed.to_dict()):
                        # Hide due to seed constraints
                        hidden.append(hit)
                        if show_all:
                            logging.info('Result would be hidden due to seed constraint')
                            if self.cards.is_exact_match(hit, lower_text):
                                logging.info('Exact title match')

            if hit not in hidden:
                if (result is None or result in hidden):
                    if not self.cards.is_exact_match(hit, lower_text):
                        for hid in hidden:
                            if self.cards.is_exact_match(hid, lower_text):
                                if show_all:
                                    logging.info('Previous hidden %s (%s) would be shown due to exact title match instead of this non-exact hit', hid.name, hid.expansion)
                                    break

                                result = hid
                                continue

                    result = hit
                elif hit.meta.score == result.meta.score and \
                    self.cards.is_exact_match(hit, lower_text) and \
                    not self.cards.is_exact_match(result, lower_text):
                    suggestions.append(result)
                    result = hit
                elif hit.meta.score / result.meta.score > self.SUGGESTION_PERCENT:
                    suggestions.append(hit)

            if show_all and index < count - 1:
                logging.info('-' * 15)

        # Always show a result even if seed constraints has hidden all of them;
        # prefer top result in that case
        if show_all:
            if len(hidden) == count and count > 0:
                logging.info('The first hidden %s (%s) would be shown since all results are hidden', hidden[0].name, hidden[0].expansion)

            return

        if result is None:
            result = response[0]

        await self.show_search_result(result, count, hidden, suggestions)

    async def show_search_result(self, hit, count, hidden, suggestions):
        # Retrieve URL or (cropped) image attachment
        url = self.cards.get_url(hit.to_dict())
        if hit.bbox or hit.image:
            filename, path, image = self.get_paths(hit)

            if not image.exists():
                if not path.exists():
                    if hit.image:
                        path = self.images.retrieve(hit.image)
                        if not isinstance(path, PurePath):
                            raise ValueError(f'Could not retrieve image {hit.image}')
                    else:
                        path = self.images.download(url, filename)

                if hit.bbox:
                    try:
                        self.images.crop(path, target_path=image, bbox=hit.bbox)
                    except:
                        image = path
                else:
                    image = path

            url = ''
        else:
            image = None

        did_you_mean = ""
        if suggestions:
            titles = ', '.join(
                self.format_suggestion(card) for card in suggestions
            )
            did_you_mean = f"\n*Perhaps you wanted: {titles}*"

        await self.context.send(f'{self.cards.get_text(hit)}\n{url} (score: {hit.meta.score:.3f}, {count} hits, {len(hidden)} hidden){did_you_mean}', file=image)

    def format_suggestion(self, card):
        title = self.cards.replace_card_title(self.cards.get_card_title(card),
                                              self.context.emoji_display)
        name = title.split(" - ")[0]
        return f"**{self.context.prefix}{card.deck} {name}**"

@Command.register(("search", "card", ""), "text", "limit", nargs=True,
                  description="Search all decks")
class CardCommand(SearchCommand):
    def search(self, text, limit):
        return Card.search_freetext(text, limit=limit)

@Command.register(tuple(
                      deck for deck, info in Cards.load().decks.items()
                      if deck not in ("board", "location") and not info.get("expansion")
                  ), "text", "limit", nargs=True)
class DeckCommand(SearchCommand):
    def search(self, text, limit):
        if "alias" in self.cards.decks[self.name]:
            deck = self.cards.decks[self.name]["alias"]
        else:
            deck = self.name

        return Card.search_freetext(text, deck=deck, limit=limit)

@Command.register(tuple(
                      deck for deck, info in Cards.load().decks.items()
                      if deck not in ("board", "location") and info.get("expansion")
                  ), "text", "expansion", "limit", nargs=("expansion",),
                  metavar="deck", description="Search a specific deck")
class DeckExpansionCommand(SearchCommand):
    def search(self, text, limit):
        text, expansion = self.cards.find_expansion(text)
        return Card.search_freetext(text, deck=self.name, expansion=expansion,
                                    limit=limit)

@Command.register(("board", "location"), "text", "expansion", "limit",
                  nargs=("expansion",),
                  description="Search a board or location")
class LocationCommand(SearchCommand):
    def search(self, text, limit):
        text, expansion = self.cards.find_expansion(text)
        return Location.search_freetext(text, expansion=expansion, limit=limit)

    def get_paths(self, hit):
        filename, path, _ = super().get_paths(hit)
        if hit.bbox:
            name = hit.name.replace(' ', '_')
            image = Path(f"images/{hit.path}_{name}.{hit.ext}")
            return filename, path, image

        return filename, path, path
