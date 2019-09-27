import yaml

class Cards:
    def __init__(self, url):
        self.url = url
        with open("data.yml") as data:
            self.cards = yaml.load(data)['cards']

        self.lookup = {}
        for card_type, cards in self.cards.items():
            for index, card in enumerate(cards['base']):
                # TODO: Notify about duplicates
                name = card['name'].lower()
                self.lookup[name] = (card_type, index)
                self.lookup[name.replace(' ', '')] = (card_type, index)
                if 'path' in card:
                    self.lookup[card['path'].lower()] = (card_type, index)

    def find(self, search, card_type=''):
        if card_type != '' and card_type not in self.cards:
            return None

        for option in [search.lower(), search.lower().replace(' ', '')]:
            if option in self.lookup:
                actual_type, index = self.lookup[option]
                break
        else:
            return 'No card found'

        card = self.cards[actual_type]['base'][index]
        type_name = self.cards[actual_type]['name']
        if card_type != '' and actual_type != card_type:
            return f"You selected the wrong card type: {card['name']} is actually a {type_name} card"

        type_path = self.cards[actual_type].get('path', type_name)
        ext = card.get('ext', self.cards[actual_type]['ext'])
        path = card.get('path', card['name']).replace(' ', '_')
        return f'{url}/{type_path}/{type_path}_{path}.{ext}'
