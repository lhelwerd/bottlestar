import re
from bs4 import BeautifulSoup
import requests

class RSS:
    ACTIONS_SPLIT = re.compile(r'Quoted Article: \d+</font>')
    def __init__(self, url):
        self.url = url
        
    def parse(self):
        response = requests.get(self.url)
        if response.status_code == 304:
            return None

        soup = BeautifulSoup(response.text, "lxml")
        for item in soup.find_all('item'):
            contents = item.find('description').text
            parts = self.ACTIONS_SPLIT.split(contents, maxsplit=1)
            if len(parts) > 1:
                text = parts[1].split('[hr]')[0]
                if text != '':
                    return text
        else:
            return None
