# %% [markdown]
# Scratch exploration of lane quality (exported notebook).

# %%
from __future__ import annotations


def search_examples(query: str) -> list[dict[str, str]]:
    return [{"id": "example", "text": query}]


# %%
def fuse_preview(left: list[dict[str, str]], right: list[dict[str, str]]) -> list[dict[str, str]]:
    return left + right
