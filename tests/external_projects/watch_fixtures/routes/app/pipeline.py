def pick_route(query):
    return "keyword" if query.startswith("id:") else "hybrid"


def lane_terms(query):
    return [{"id": "a"}, {"id": "b"}]


def lane_vectors(query):
    return [{"id": "b"}, {"id": "c"}]


def merge_lanes(first, second):
    seen = {}
    for hit in first + second:
        seen.setdefault(hit["id"], hit)
    return list(seen.values())


def retrieve(query):
    if pick_route(query) == "keyword":
        return lane_terms(query)
    return merge_lanes(lane_terms(query), lane_vectors(query))
