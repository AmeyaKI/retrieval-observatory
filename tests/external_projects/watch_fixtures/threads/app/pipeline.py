from concurrent.futures import ThreadPoolExecutor


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
    with ThreadPoolExecutor(max_workers=2) as pool:
        terms = pool.submit(lane_terms, query)
        vectors = pool.submit(lane_vectors, query)
        return merge_lanes(terms.result(), vectors.result())
