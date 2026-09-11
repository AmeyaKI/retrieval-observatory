from __future__ import annotations

PARAPHRASE_PROMPT = """\
You are building a retrieval evaluation dataset. Your task: generate natural-language questions that can be answered by the document excerpt below.

Rules:
- Do NOT copy phrases verbatim from the document
- Use different vocabulary, structure, and phrasing
- Questions should be specific enough to have one clear answer in this document
- Vary the question style (who/what/how/when/why/describe)
- Output exactly {n} questions, one per line, no numbering, no bullet points

Document:
{text}

Questions:"""

TEMPORAL_PROMPT = """\
You are building a retrieval evaluation dataset focused on temporal confusion — a common retrieval failure where a system retrieves an outdated document instead of the current one.

Two documents cover the same topic at different points in time:

Document A (earlier, ~{year_a}):
{text_a}

Document B (later, ~{year_b}):
{text_b}

Write {n} questions where:
- The correct answer depends on WHICH time period the asker means
- A retrieval system could plausibly confuse the two documents
- The question implies recency or a specific time context

Output exactly {n} questions, one per line, no numbering, no bullet points.

Questions:"""

ADVERSARIAL_PROMPT = """\
You are building a retrieval evaluation dataset. Your task: generate queries that are deceptive — they sound like they are about this document's topic but would actually cause a retrieval system to retrieve wrong or misleading documents.

Document:
{text}

Write {n} queries that:
- Use vocabulary similar to this document's topic
- But ask about something subtly different, or imply a different entity/time/scope
- Would mislead a keyword or embedding-based retrieval system

Output exactly {n} queries, one per line, no numbering, no bullet points.

Queries:"""


def format_paraphrase(text: str, n: int) -> str:
    return PARAPHRASE_PROMPT.format(text=text[:1500], n=n)


def format_temporal(text_a: str, text_b: str, year_a: int, year_b: int, n: int) -> str:
    return TEMPORAL_PROMPT.format(
        text_a=text_a[:800],
        text_b=text_b[:800],
        year_a=year_a,
        year_b=year_b,
        n=n,
    )


def format_adversarial(text: str, n: int) -> str:
    return ADVERSARIAL_PROMPT.format(text=text[:1500], n=n)
