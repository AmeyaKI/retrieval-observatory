import asyncio


async def lane_terms(query):
    await asyncio.sleep(0)
    return [{"id": "a"}, {"id": "b"}]


async def lane_vectors(query):
    await asyncio.sleep(0)
    return [{"id": "b"}, {"id": "c"}]


def merge_lanes(first, second):
    seen = {}
    for hit in first + second:
        seen.setdefault(hit["id"], hit)
    return list(seen.values())


async def rescore(hits):
    await asyncio.sleep(0)
    return list(reversed(hits))


async def retrieve(query):
    terms, vectors = await asyncio.gather(lane_terms(query), lane_vectors(query))
    return await rescore(merge_lanes(terms, vectors))
