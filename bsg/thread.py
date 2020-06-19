"""
BGG BYC thread retrieval
"""

from glob import glob
import logging
from pathlib import Path
import requests
from requests.exceptions import ConnectionError as ConnectError, HTTPError, Timeout
from .byc import ByYourCommand

class Thread:
    """
    Handler for retrieving posts from BGG.
    """

    def __init__(self, api_url):
        self.api_url = api_url
        self.session = requests.Session()

    def clear(self, thread_id):
        """
        Remove cached posts from the thread.
        """

        for cache_path in glob(f"game/bgg-{thread_id}-*.txt"):
            Path(cache_path).unlink()

    def retrieve(self, thread_id):
        """
        Retrieve the latest BYC post in a thread by its ID. If the thread's
        latest post is already available locally then the post and seed from
        the cached file is returned. Otherwise, the latest post body and seed
        are retruened.
        """

        thread_request = self.session.get(f"{self.api_url}/threads/{thread_id}")
        try:
            thread_request.raise_for_status()
            thread = thread_request.json()
            last_post = thread["numposts"]
            pages = thread["numpages"]
        except (ConnectError, HTTPError, Timeout, ValueError, KeyError):
            logging.exception("Could not look up thread ID %s", thread_id)
            return None, {}

        article_path = Path(f"game/bgg-{thread_id}-{last_post}.txt")
        if article_path.exists():
            with article_path.open('r') as article_file:
                body = article_file.read()
                return body, ByYourCommand.get_game_seed(body)

        self.clear(thread_id)
        return self.download(thread_id, last_post, pages)

    def download(self, thread_id, last_post, pages):
        """
        Retrieve the latest BYC post from the thread as well as the game seed.
        """

        article_request = self.session.get(f"{self.api_url}/articles",
                                           params={
                                               "threadid": thread_id,
                                               "pageid": pages
                                           })
        try:
            article_request.raise_for_status()
            articles = article_request.json()
            for article in reversed(articles["articles"]):
                body = f'[q="{article["author"]}"]{article["body"]}[/q]'
                game_state = ByYourCommand.get_game_seed(body)
                if game_state:
                    article_path = Path(f"game/bgg-{thread_id}-{last_post}.txt")
                    with article_path.open('w') as article_file:
                        article_file.write(body)
                    return body, game_state
        except (ConnectError, HTTPError, Timeout, ValueError, KeyError):
            logging.info("Could not look up article #%d for thread ID %d",
                         last_post, thread_id)

        return None, {}

    def get_author(self, author_id):
        author_request = self.session.get(f"{self.api_url}/users/{author_id}")
        try:
            author_request.raise_for_status()
            author = author_request.json()
            return author["username"]
        except (ConnectError, HTTPError, Timeout, ValueError, KeyError):
            logging.info("Could not look up author %d", author_id)

        return None
