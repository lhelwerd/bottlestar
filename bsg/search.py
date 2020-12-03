from elasticsearch_dsl import Document, Boolean, Float, Integer, Keyword, \
    Object, normalizer, Q, Text

lowercase = normalizer('lower', filter=['lowercase'])

class Card(Document):
    SEARCH_FIELDS = ['path^3', 'name^4', 'text^2', 'deck', 'expansion^2', 'cylon', 'skills']

    name = Text(analyzer='snowball', fields={'raw': Keyword()})
    path = Text(analyzer='snowball', fields={'raw': Keyword()})
    replace = Keyword()
    url = Keyword()
    image = Integer()
    bbox = Integer()
    deck = Keyword(normalizer=lowercase)
    expansion = Keyword(normalizer=lowercase)
    ext = Keyword()
    seed = Object()
    index = Integer()
    count = Integer()
    value = Integer()
    destination = Integer()
    skills = Keyword(normalizer=lowercase)
    text = Text(analyzer='snowball')
    cylon = Keyword()
    jump = Boolean()
    character_class = Keyword()
    president = Float()
    admiral = Float()
    cag = Float()
    allegiance = Keyword()
    ability = Boolean()
    reckless = Boolean()
    agenda = Keyword()

    class Index:
        name = 'card'

    @classmethod
    def search_freetext(cls, text, deck='', expansion='', limit=10):
        search = cls.search(using='main')
        query = Q('multi_match', query=text, fields=cls.SEARCH_FIELDS) | \
                Q('fuzzy', name=text) | \
                Q('fuzzy', text=text)
        if deck != '':
            search = search.filter('term', deck=deck)
        if expansion != '':
            search = search.filter('term', expansion=expansion)
        search_query = search[:limit].query(query)
        result = search_query.execute()
        count = search_query.count()
        if not isinstance(count, int):
            count = count['value']
        return result, count

class Location(Document):
    SEARCH_FIELDS = ['name^2', 'text', 'expansion', 'skills']

    board_name = Text(analyzer='snowball', fields={'raw': Keyword()})
    path = Text(analyzer='snowball', fields={'raw': Keyword()})
    image = Integer()
    ext = Keyword()
    name = Text(analyzer='snowball', fields={'raw': Keyword()})
    expansion = Keyword(normalizer=lowercase)
    seed = Object()
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
        result = search_query.execute()
        count = search_query.count()
        if not isinstance(count, int):
            count = count['value']
        return result, count
