from elasticsearch_dsl import Document, Boolean, Integer, Keyword, normalizer, Q, Text

lowercase = normalizer('lower', filter=['lowercase'])

class Card(Document):
    SEARCH_FIELDS = ['path', 'name', 'text', 'deck', 'expansion', 'cylon', 'skills']

    name = Text(analyzer='snowball', fields={'raw': Keyword()})
    path = Text(analyzer='snowball', fields={'raw': Keyword()})
    deck = Keyword()
    expansion = Keyword()
    ext = Keyword()
    value = Integer()
    destination = Integer()
    skills = Keyword(normalizer=lowercase)
    text = Text(analyzer='snowball')
    cylon = Text(fields={'raw': Keyword(normalizer=lowercase)})
    jump = Boolean()
    character_class = Keyword()

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
