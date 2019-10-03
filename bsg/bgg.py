from email.utils import formatdate
import logging
import re
from time import mktime
from bs4 import BeautifulSoup
import requests

class RSS:
    ACTIONS_SPLIT = re.compile(r'Quoted Article: \d+</font>')

    def __init__(self, url):
        self.url = url
        
    def parse(self, if_modified_since=None, one=False):
        headers = {}
        if if_modified_since is not None:
            value = formatdate(mktime(if_modified_since.timetuple()),
                               localtime=False, usegmt=True)
            headers['if-modified-since'] = value

        response = requests.get(self.url, headers=headers)
        if response.status_code == 304:
            return

        soup = BeautifulSoup(response.text, "lxml")
        for item in soup.find_all('item'):
            contents = item.find('description').text
            contents = contents.replace("\r", "\n").replace("]]>", "")
            parts = self.ACTIONS_SPLIT.split(contents, maxsplit=1)
            if len(parts) > 1:
                actions = parts[1].split("<br/>[hr]\n")[0]
                desc_soup = BeautifulSoup(actions, "lxml")
                for quote in desc_soup.find_all("div", {"class": "quote"}):
                    quote_title = quote.find("div", {"class": "quotetitle"})
                    if 'BYC: Game State' in quote_title.text:
                        quote.extract()
                    else:
                        quote_title.extract()

                text = ''.join(t for t in desc_soup.find_all(text=True)).strip().replace('[hr]', '')
                if text != '':
                    yield text
                elif one:
                    return
        else:
            return
