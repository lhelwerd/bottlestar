from email.utils import formatdate
import html
import logging
import re
from time import mktime
from bs4 import BeautifulSoup
import requests

class RSS:
    ACTIONS_SPLIT = re.compile(r'Quoted Article: \d+</font>')
    GAME_SEED = re.compile(r"<font color='#(?:F4F4FF|FFFFFF)'>New seed: (\S+)</font>")

    def __init__(self, url, images, image_url=None, session_id=None):
        self.url = url
        self.images = images
        self.image_url = image_url
        self.session_id = session_id

    def _request(self, if_modified_since=None):
        headers = {}
        cookies = {}
        if if_modified_since is not None:
            value = formatdate(mktime(if_modified_since.timetuple()),
                               localtime=False, usegmt=True)
            headers['if-modified-since'] = value

        if self.session_id is not None:
            cookies['SessionID'] = self.session_id

        return requests.get(self.url, headers=headers, cookies=cookies)

    def parse(self, if_modified_since=None, one=False, game_seed=False,
              game_state=False):
        response = self._request(if_modified_since)
        if response.status_code == 304:
            return

        soup = BeautifulSoup(response.text, "lxml")
        for item in soup.find_all('item'):
            author = item.find("dc:creator").text
            description = item.find('description')
            if self.image_url is not None:
                for image_id, replacement in self.images.images.items():
                    url = self.image_url + image_id
                    for link in description.find_all('a', {"href": url}):
                        link.replace_with(replacement)

            contents = html.unescape(str(description))
            contents = contents.replace("\r", "\n").replace("]]>", "")
            if game_seed:
                match = self.GAME_SEED.search(contents)
                if match:
                    yield match.group(1), author
                else:
                    continue

            parts = self.ACTIONS_SPLIT.split(contents, maxsplit=1)
            if len(parts) > 1:
                actions = parts[1].split("<br/>[hr]\n")[0]
                desc_soup = BeautifulSoup(html.unescape(actions), "lxml")

                for quote in desc_soup.find_all("div", {"class": "quote"}):
                    quote_title = quote.find("div", {"class": "quotetitle"})
                    if quote_title is not None:
                        if 'BYC: Game State' in quote_title.text:
                            state = quote.extract()
                            if game_state:
                                yield str(state).replace("[hr]", "<hr/>"), author
                                return
                        else:
                            quote_title.extract()

                text = ''.join(t for t in desc_soup.find_all(text=True)).strip().replace('[hr]', '')
                if text != '' and not game_state:
                    yield text
                elif one:
                    return
                else:
                    logging.info('No contents in the latest message, skipping')
        else:
            return
