from elasticsearch_dsl import Document, Boolean, Integer, Keyword, normalizer, Q, Text

lowercase = normalizer('lower', filter=['lowercase'])

class Card(Document):
    SEARCH_FIELDS = ['name', 'text', 'card_type', 'deck', 'cylon', 'skills']

    name = Text(analyzer='snowball', fields={'raw': Keyword()})
    path = Text(analyzer='snowball', fields={'raw': Keyword()})
    card_type = Keyword()
    deck = Keyword()
    value = Integer()
    destination = Integer()
    skills = Keyword(normalizer=lowercase)
    text = Text(analyzer='snowball')
    cylon = Text(fields={'raw': Keyword(normalizer=lowercase)})
    jump = Boolean()

    class Index:
        name = 'card'

    @classmethod
    def search_freetext(cls, text, limit=10):
        search = cls.search(using='main')
        query = Q('multi_match', query=text, fields=cls.SEARCH_FIELDS) | \
                Q('fuzzy', name=text) | \
                Q('fuzzy', text=text)
        search_query = search.query(query)
        return search_query.execute(), search_query.count()['value']
