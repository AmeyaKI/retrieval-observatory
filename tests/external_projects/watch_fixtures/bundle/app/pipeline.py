def lexical(query):
    return [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def screen(items):
    kept = [item for item in items if item["id"] != "b"]
    return kept, [item for item in items if item["id"] == "b"], [], not kept


def order_by_length(hits):
    return list(reversed(hits))


def retrieve(query):
    kept, _dropped, _errors, _empty = screen(lexical(query))
    return order_by_length(kept)
