def find_passages(query):
    return [{"id": "d1#1"}, {"id": "d1#2"}, {"id": "d2#1"}]


def to_documents(passages):
    seen = {}
    for passage in passages:
        seen.setdefault(passage["id"].split("#")[0], {"id": passage["id"].split("#")[0]})
    return list(seen.values())


def retrieve(query):
    return to_documents(find_passages(query))
