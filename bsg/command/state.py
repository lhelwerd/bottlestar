"""
Commands that make use of game state from a BGG thread.
"""

from .base import Command
from ..bbcode import BBCodeMarkdown
from ..byc import ByYourCommand, ROLE_TEXT
from ..card import Cards
from ..image import Images
from ..thread import Thread

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

@Command.register("succession", slow=True,
                  description="Show the line of succession")
class SuccessionCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        succession = self.cards.lines_of_succession(seed)
        message, mentions = self.context.replace_roles(succession)
        await self.context.send(message, allowed_mentions=mentions)

@Command.register("analyze", slow=True,
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

@Command.register("image", slow=True,
                  description="Show the lastest game board state")
class ImageCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        author = self.thread.get_author(ByYourCommand.get_quote_author(post)[0])
        byc = ByYourCommand(self.game_id, author,
                            self.context.config['script_url'])

        choices = []
        dialog = byc.run_page(choices, post)
        if "You are not recognized as a player" in dialog.msg:
            choices.extend(["\b1", "1"])
        choices.extend(["2", "\b2", "\b0"])
        post = byc.run_page(choices, post, num=len(choices),
                            quits=True, quote=False)

        text = self.bbcode.process_bbcode(post)

        path = byc.save_game_state_screenshot(self.images,
                                              self.bbcode.game_state)
        await self.context.send("", file=path)

@Command.register("latest", slow=True, description="Show the latest game post")
class LatestCommand(GameStateCommand):
    async def analyze(self, post, seed, **kw):
        text = self.bbcode.process_bbcode(post)

        users = any(user in text for user in ROLE_TEXT["character"])
        response, mentions = self.context.replace_roles(text, seed=seed,
                                                        users=users)

        await self.context.send(response, allowed_mentions=mentions)

@Command.register("ping", slow=True,
                  description="Show who needs to do something")
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

    def add_ping(self, text, pings, role_mentions, **kwargs):
        ping, mention = self.context.replace_roles(text, emoji=False,
                                                   deck=False, **kwargs)
        pings.append(ping)
        role_mentions.update(mention.roles)

    def get_banner_roles(self):
        try:
            banner = self.bbcode.image_data[0]
            return [banner["text"]] + banner["titles"]
        except IndexError:
            return []

    def ping(self, seed, author, mentions):
        pings = []
        role_mentions = set([])
        try:
            usernames = [username.lower() for username in seed["usernames"]]
            author_index = usernames.index(author.lower())
            try:
                author_roles = [seed["players"][author_index]]
            except (KeyError, IndexError):
                author_roles = self.get_banner_roles()

            for key, title in self.cards.titles.items():
                titles = self.cards.get_titles(key, title)
                if self.cards.has_titles(seed, titles, author_index):
                    author_roles.append(key)
        except ValueError:
            author_index = -1
            author_roles = self.get_banner_roles()

        tokens = {
            'Strategic Planning': 'spToken',
            'Declare Emergency': 'deToken'
        }
        for interrupt in self.bbcode.interrupts:
            card = interrupt['possibilities'].rstrip('.')
            topic = interrupt['topic']
            if (card in tokens and not seed.get(tokens[card])) or \
                (topic in tokens and not seed.get(tokens[topic])):
                # Skip finished tokens
                continue

            if seed.get('currentSkillCheck') is not None and \
                (any(cards for cards in seed.get('skillCheckCards', [])) or \
                    seed.get('contributingPlayer', 0) > 0):
                continue

            names = [
                player['name'] for player in interrupt['players']
                if player['action'] == ''
            ]
            if names:
                self.add_ping(f"Interrupts for {topic}: {' '.join(names)}",
                              pings, role_mentions)

        for skill_check in self.bbcode.skill_checks:
            names = [
                player['name'] for player in skill_check['players']
                if player['bold'] != ''
            ]
            if names:
                self.add_ping(f"{skill_check['topic']}: {names[0]}", pings,
                              role_mentions)

        # Phase 0: Receive Skills
        # Phase 1: Before Movement (any Movement effects occur in phase -1)
        if seed["phase"] in {0, 1} and not (
            seed["turn"] == 0 and seed["round"] == 1 and \
            any(len(hand) == 0 for hand in seed["skillCardHands"])):
            player = seed["players"][seed["turn"]]
            self.add_ping(f"{player} is the Current Player.", pings,
                          role_mentions)

        remaining_roles = [
            role for role in mentions.roles
            if role.name not in author_roles and role not in role_mentions
        ]
        bold_names = []
        for bold in self.bbcode.bold_text:
            bold_roles = [role for role in remaining_roles if role.name in bold]
            bold_names.extend(role.name for role in bold_roles)
            if bold_roles:
                self.add_ping(bold, pings, role_mentions, roles=bold_roles)

        if seed.get("crisisOptions"):
            for player_index, options in enumerate(seed["crisisOptions"]):
                if player_index != author_index:
                    player = seed["players"][player_index]
                    if player in bold_names:
                        continue

                    mandatories = seed["mandatory"][player_index]
                    for option, mandatory in zip(options, mandatories):
                        if mandatory:
                            self.add_ping(f"{player}: {option}", pings,
                                          role_mentions)

        response = "\n".join(pings)
        mentions = self.context.make_mentions(everyone=False, users=False,
                                              roles=list(role_mentions))
        return response, mentions

