"""
Search commands for card and location texts.
"""

import logging
from pathlib import Path, PurePath
from .base import Command
from ..card import Cards
from ..image import Images
from ..search import Card, Location
from ..thread import Thread

class SearchCommand(Command):
    DEFAULT_LIMIT = 3

    def __init__(self, name, context):
        super().__init__(name, context)
        self.cards = Cards(self.context.config['cards_url'])
        self.images = Images(self.context.config['api_url'])

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

    async def run(self, text="", limit=None, **kw):
        show_all = False
        if limit is None:
            limit = self.DEFAULT_LIMIT
        else:
            show_all = True

        hidden = []
        lower_text = text.lower()
        response, count = self.search(text, limit)

        seed = None
        for index, hit in enumerate(response):
            if show_all:
                await self.show_search_result(hit, count, hidden)

            # Check if the seed constraints may hide this result
            if hit.seed:
                if seed is None:
                    thread = Thread(self.context.config['api_url'])
                    seed = thread.retrieve(self.context.config['thread_id'],
                                           download=False)[1]

                # Seed may not be locally available at this point
                if seed is not None:
                    for key, value in hit.seed.to_dict().items():
                        if seed.get(key, value) != value:
                            # Hide due to seed constraints
                            hidden.append(hit)
                            if show_all:
                                logging.info('Result would be hidden due to seed constraint')
                                if self.cards.is_exact_match(hit, lower_text):
                                    logging.info('Exact title match')

                            break

            if hit not in hidden:
                if not self.cards.is_exact_match(hit, lower_text):
                    for hid in hidden:
                        if self.cards.is_exact_match(hid, lower_text):
                            if show_all:
                                logging.info('Previous hidden %s (%s) would be shown due to exact title match instead of this non-exact hit', hid.name, hid.expansion)
                                break

                            await self.show_search_result(hid, count, hidden)
                            return

                if not show_all:
                    await self.show_search_result(hit, count, hidden)
                    return

            if show_all and index < count - 1:
                logging.info('-' * 15)

        # Always show a result even if seed constraints has hidden all of them;
        # prefer top result in that case
        if show_all:
            if len(hidden) == count and count > 0:
                logging.info('The first hidden %s (%s) would be shown since all results are hidden', hidden[0].name, hidden[0].expansion)

            return

        await self.show_search_result(response[0], count, hidden)

    async def show_search_result(self, hit, count, hidden):
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

        await self.context.send(f'{self.cards.get_text(hit)}\n{url} (score: {hit.meta.score:.3f}, {count} hits, {len(hidden)} hidden)', file=image)

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
