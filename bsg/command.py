"""
Bot commands.
"""

import asyncio
from collections import OrderedDict
import logging
from pathlib import Path, PurePath
from .bbcode import BBCodeMarkdown
from .byc import ByYourCommand, ROLE_TEXT
from .card import Cards
from .image import Images
from .search import Card, Location
from .thread import Thread

###

class Command:
    """
    Command interface.
    """

    COMMANDS = OrderedDict()

    @classmethod
    def register(cls, name, *arguments, **keywords):
        def decorator(subclass):
            info = keywords.copy()
            info.update({
                "class": subclass,
                "arguments": arguments
            })
            if isinstance(name, tuple):
                info["group"] = name
                commands = name
            else:
                commands = (name,)

            for command in commands:
                cls.COMMANDS[command] = info

            return subclass

        return decorator

    @classmethod
    def execute(cls, context, name, arguments):
        if name not in cls.COMMANDS:
            return False

        info = cls.COMMANDS[name]
        command = info["class"](name, context)

        if info.get("nargs"):
            arguments = (' '.join(arguments),)
            extra_arguments = {
                arg: value for arg, value in context.arguments.items()
                if arg in info["arguments"]
            }
        else:
            extra_arguments = {}

        keywords = dict(zip(info["arguments"], arguments))
        keywords.update(extra_arguments)

        loop = asyncio.get_event_loop()
        try:
            if info.get("slow"):
                loop.run_until_complete(command.run_with_typing(**keywords))
            else:
                loop.run_until_complete(command.run(**keywords))
        except:
            logging.exception("Command %s (called with %r)", name, arguments)
            loop.run_until_complete(context.send("Uh oh"))

        loop.close()
        return True

    def __init__(self, name, context):
        self.name = name
        self.context = context

    async def run(self, **kw):
        raise NotImplementedError("Must be implemented by subclasses")

    async def run_with_typing(self, **kw):
        typing = context.typing
        if typing:
            async with typing:
                await self.run(**kw)
        else:
            await self.run(**kw)

@Command.register("bot")
class BotCommand(Command):
    """
    Test command to say hello.
    """

    async def run(self, **kw):
        await self.context.send(f"Hello, {self.context.mention}!")

@Command.register("help")
class HelpCommand(Command):
    """
    Command to show all registered commands that have help messages.
    """

    async def run(self, **kw):
        extra_arguments = self.context.arguments
        lines = []
        for name, info in self.COMMANDS.items():
            group = info.get("group")
            if group is not None and group[0] != name:
                continue

            description = info.get("description", "")
            if callable(description):
                description = description(self.context)
            elif description == "":
                continue

            metavar = info.get("metavar")
            if metavar:
                name = f"<{metavar}>"

            command = f"**{self.context.prefix}{name}**"
            nargs = info.get("nargs")
            if nargs and info["arguments"]:
                nargs = nargs if isinstance(nargs, tuple) else []
                narg = info["arguments"][0]
                arguments = f"<{narg}...>"
                if len(info["arguments"]) > 1:
                    arguments += " " + \
                        " ".join(f"[{arg}]" for arg in info["arguments"][1:]
                                if arg in extra_arguments or arg in nargs)
            else:
                arguments = " ".join(f"<{arg}>" for arg in info["arguments"])

            if arguments != "":
                command = f"{command} {arguments}"
            if group is not None and not metavar:
                command += " (also " + ", ".join(
                    f"**{self.context.prefix}{other}**" for other in group[1:]
                ) + ")"
            lines.append(f"{command}: {description}")

        await self.context.send("\n".join(lines))

class GameStateCommand(Command):
    """
    Abstract class for a command that displays information from a game state.
    """

    def __init__(self, name, context):
        super().__init__(name, context)
        self.thread = Thread(self.context.config['api_url'])
        self.game_id = self.context.config['thread_id']
        self.cards = Cards(self.context.config['cards_url'])
        self.images = Images(self.context.config['api_url'])
        self.bbcode = BBCodeMarkdown(self.images)

    async def run(self, **kw):
        post, seed = self.thread.retrieve(self.game_id)
        if post is None:
            self.context.send('No latest post found!')
            return

        await self.analyze(post, seed, **kw)

    async def analyze(self, post, seed, **kw):
        raise NotImplementedError("Must be implemented by subclasses")

@Command.register("succession", description="Show the line of succession")
class SuccessionCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        succession = self.cards.lines_of_succession(seed)
        message, mentions = self.context.replace_roles(succession)
        await self.context.send(message, allowed_mentions=mentions)

@Command.register("analyze",
                  description="Show the top cards of decks after game is over")
class AnalyzeCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        if not seed.get('gameOver'):
            await self.context.send('Game is not yet over!')
        else:
            analysis = self.cards.analyze(seed)
            if analysis == '':
                analysis = 'No decks found in the game!'

            await self.context.send(analysis)

@Command.register("image", description="Show the lastest game board state")
class ImageCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        author = self.thread.get_author(ByYourCommand.get_quote_author(post)[0])
        byc = ByYourCommand(self.game_id, author,
                            self.context.config['script_url'])

        choices = []
        dialog = byc.run_page(choices, post)
        print(dialog.msg)
        if "You are not recognized as a player" in dialog.msg:
            choices.extend(["\b1", "1"])
        choices.extend(["2", "\b2", "\b1"])
        post = byc.run_page(choices, post, num=len(choices),
                            quits=True, quote=False)

        text = self.bbcode.process_bbcode(post)

        path = byc.save_game_state_screenshot(self.images,
                                              self.bbcode.game_state)
        await self.context.send("", file=path)

@Command.register("latest", description="Show the latest game post")
class LatestCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        text = self.bbcode.process_bbcode(post)

        users = any(user in text for user in ROLE_TEXT["character"])
        response, mentions = self.context.replace_roles(text, seed=seed,
                                                        users=users)

        await self.context.send(response, allowed_mentions=mentions)

@Command.register("ping", description="Show who needs to do something")
class PingCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        author = self.thread.get_author(ByYourCommand.get_quote_author(post)[0])
        text = self.bbcode.process_bbcode(post)

        users = any(user in text for user in ROLE_TEXT["character"])
        response, mentions = self.context.replace_roles(text, seed=seed,
                                                        users=users)

        error = "I did not find anyone, what are you trying to do here? :robot:"
        if mentions is None or not mentions.roles:
            await self.context.send(error)
            return

        response, mentions = self.ping(seed, author, mentions)
        if response == "":
            await self.context.send(error)
            return

        await self.context.send(response, allowed_mentions=mentions)

    def add_ping(text, pings, role_mentions, **kwargs):
        ping, mention = self.context.replace_roles(text, emoji=False,
                                                   deck=False, **kwargs)
        pings.append(ping)
        role_mentions.update(mention.roles)

    def ping(self, seed, author, mentions):
        pings = []
        role_mentions = set([])
        try:
            author_role = seed["players"][seed["usernames"].index(author)]
        except (KeyError, IndexError, ValueError):
            try:
                author_role = self.bbcode.image_text[0]
            except IndexError:
                author_role = ""

        for interrupt in self.bbcode.interrupts:
            names = [
                player['name'] for player in interrupt['players']
                if player['action'] == ''
            ]
            if names:
                text = f"Interrupts for {interrupt['topic']}: {' '.join(names)}"
                self.add_ping(text, pings, role_mentions)

        for skill_check in self.bbcode.skill_checks:
            names = [
                player['name'] for player in skill_check['players']
                if player['bold'] != ''
            ]
            if names:
                self.add_ping(f"{skill_check['topic']}: {names[0]}", pings,
                              role_mentions)

        remaining_roles = [
            role for role in mentions.roles
            if role.name != author_role and role not in role_mentions
        ]
        for bold in self.bbcode.bold_text:
            bold_roles = [role for role in remaining_roles if role.name in bold]
            if bold_roles:
                self.add_ping(bold, pings, role_mentions, roles=bold_roles)

        response = "\n".join(pings)
        mentions = self.context.make_mentions(everyone=False, users=False,
                                              roles=list(role_mentions))
        return response, mentions

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
