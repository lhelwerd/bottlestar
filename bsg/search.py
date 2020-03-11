from elasticsearch_dsl import Document, Boolean, Integer, Keyword, normalizer, Q, Text

lowercase = normalizer('lower', filter=['lowercase'])

class Card(Document):
    SEARCH_FIELDS = ['path', 'name', 'text', 'deck', 'expansion', 'cylon', 'skills']

    name = Text(analyzer='snowball', fields={'raw': Keyword()})
    path = Text(analyzer='snowball', fields={'raw': Keyword()})
    url = Keyword()
    bbox = Integer()
    deck = Keyword(normalizer=lowercase)
    expansion = Keyword(normalizer=lowercase)
    ext = Keyword()
    count = Integer()
    value = Integer()
    destination = Integer()
    skills = Keyword(normalizer=lowercase)
    text = Text(analyzer='snowball')
    cylon = Keyword()
    jump = Boolean()
    character_class = Keyword()
    allegiance = Keyword()
    ability = Boolean()
    reckless = Boolean()

    class Index:
        name = 'card'

    @classmethod
    def search_freetext(cls, text, deck='', limit=10):
        search = cls.search(using='main')
        query = Q('multi_match', query=text, fields=cls.SEARCH_FIELDS) | \
                Q('fuzzy', name=text) | \
                Q('fuzzy', text=text)
        if deck != '':
            search = search.filter('term', deck=deck)
        search_query = search[:limit].query(query)
        return search_query.execute(), search_query.count()['value']

class Location(Document):
    SEARCH_FIELDS = ['name', 'text', 'expansion', 'skills']

    board_name = Text(analyzer='snowball', fields={'raw': Keyword()})
    path = Text(analyzer='snowball', fields={'raw': Keyword()})
    ext = Keyword()
    name = Text(analyzer='snowball', fields={'raw': Keyword()})
    expansion = Keyword(normalizer=lowercase)
    hazardous = Boolean()
    bbox = Integer()
    value = Integer()
    skills = Keyword(normalizer=lowercase)
    occupation = Integer()
    text = Text(analyzer='snowball')

    class Index:
        name = 'location'

    @classmethod
    def search_freetext(cls, text, expansion='', limit=10):
        search = cls.search(using='main')
        query = Q('multi_match', query=text, fields=cls.SEARCH_FIELDS) | \
                Q('fuzzy', name=text) | \
                Q('fuzzy', text=text)
        if expansion != '':
            search = search.filter('term', expansion=expansion)
        search_query = search[:limit].query(query)
        return search_query.execute(), search_query.count()['value']
