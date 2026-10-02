"""Turn crawled pages into a knowledge base and pick what each answer needs.

Small business sites are small. Most knowledge bases fit in the prompt whole,
which is both the most accurate option and the cheapest once the prompt is
cached. Only larger sites are narrowed per question, with BM25 over the chunks.
No vector database or embedding model is involved.
"""
import math
import re

from . import config

_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = frozenset(
    "a an and are as at be but by can do does for from has have how i if in is it its me my of on or "
    "our so that the their them there these they this to was we what when where which who why will "
    "with you your".split()
)


def chunk_pages(pages, size=900):
    """Split pages into chunks of roughly `size` characters on line boundaries."""
    chunks = []
    for page in pages:
        current, length = [], 0
        for line in page["text"].split("\n"):
            if length + len(line) > size and current:
                chunks.append({"url": page["url"], "title": page["title"], "text": "\n".join(current)})
                current, length = [], 0
            while len(line) > size:
                chunks.append({"url": page["url"], "title": page["title"], "text": line[:size]})
                line = line[size:]
            current.append(line)
            length += len(line) + 1
        if current:
            chunks.append({"url": page["url"], "title": page["title"], "text": "\n".join(current)})
    return chunks


def tokenize(text):
    return [w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in _STOP]


def rank(chunks, query, k1=1.5, b=0.75):
    """Return chunk indexes ordered by BM25 relevance to `query`."""
    terms = set(tokenize(query))
    docs = [tokenize(chunk["text"] + " " + chunk["title"]) for chunk in chunks]
    if not terms or not docs:
        return list(range(len(chunks)))
    average = sum(len(d) for d in docs) / len(docs) or 1
    frequency = {t: sum(1 for d in docs if t in d) for t in terms}
    scores = []
    for index, doc in enumerate(docs):
        score = 0.0
        for term in terms:
            tf = doc.count(term)
            if not tf:
                continue
            idf = math.log(1 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc) / average))
        scores.append((score, index))
    scores.sort(key=lambda pair: (-pair[0], pair[1]))
    return [index for _, index in scores]


def total_chars(chunks):
    return sum(len(chunk["text"]) for chunk in chunks)


def fits_whole(chunks):
    return total_chars(chunks) <= config.KB_WHOLE_CHARS


def select(chunks, query, budget=None):
    """Pick the chunks most relevant to `query`, in their original order."""
    budget = budget or config.KB_RETRIEVAL_CHARS
    chosen, used = set(), 0
    # The first chunk is the top of the home page: what the business is.
    for index in [0] + rank(chunks, query):
        if index in chosen or index >= len(chunks):
            continue
        size = len(chunks[index]["text"])
        if used + size > budget and chosen:
            continue
        chosen.add(index)
        used += size
    return [chunks[i] for i in sorted(chosen)]


def render(chunks):
    """Format chunks for the prompt, grouping consecutive chunks of one page."""
    parts, last = [], None
    for chunk in chunks:
        key = (chunk["url"], chunk["title"])
        if key != last:
            label = chunk["title"] or "Page"
            parts.append(f"\n### {label}" + (f" ({chunk['url']})" if chunk["url"] else ""))
            last = key
        parts.append(chunk["text"])
    return "\n".join(parts).strip()
