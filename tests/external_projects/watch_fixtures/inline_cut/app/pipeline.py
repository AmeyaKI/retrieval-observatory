def lexical(query):
    return [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def order_by_id(hits):
    return sorted(hits, key=lambda hit: hit["id"], reverse=True)


def retrieve(query):
    return order_by_id(lexical(query))[:2]
