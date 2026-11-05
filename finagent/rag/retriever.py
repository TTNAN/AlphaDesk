"""BM25 检索。不依赖付费 embedding，索引在内存中构建（约 2-3 秒）。"""
from __future__ import annotations

import re
from functools import lru_cache

from rank_bm25 import BM25Okapi

from .chunker import Chunk, load_chunks

STOP = set("""a an the and or of to in on for by with as at from is are was were be been being this that these
those it its our we us you your their they them which who whom what when where how than then there here such
not no can may might will would should could do does did has have had also other any all each into over under
about more most less per""".split())


try:
    from nltk.stem import PorterStemmer
    _porter = PorterStemmer()
except ImportError:  # nltk 可选，缺失时退回简单规则
    _porter = None

_stem_cache: dict[str, str] = {}


def _stem(t: str, mode: str) -> str:
    if mode == "porter" and _porter is not None:
        if t not in _stem_cache:
            _stem_cache[t] = _porter.stem(t)
        return _stem_cache[t]
    if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):  # v1 简单规则：去复数 s
        return t[:-1]
    return t


def tokenize(text: str, mode: str = "simple") -> list[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(t, mode) for t in toks if t not in STOP and len(t) > 1]


class FilingRetriever:
    def __init__(self, chunks: list[Chunk] | None = None, stem: str = "simple"):
        self.stem = stem
        self.chunks = chunks if chunks is not None else load_chunks()
        self.bm25 = BM25Okapi([tokenize(f"{c.section_title} {c.text}", stem) for c in self.chunks])
        self.by_id = {c.chunk_id: c for c in self.chunks}

    def search(self, query: str, ticker: str | None = None, form: str | None = None,
               k: int = 5) -> list[tuple[Chunk, float]]:
        scores = self.bm25.get_scores(tokenize(query, self.stem))
        idx = range(len(self.chunks))
        if ticker:
            idx = [i for i in idx if self.chunks[i].ticker == ticker.upper()]
        if form:
            f = form.upper().replace("10K", "10-K").replace("10Q", "10-Q")
            idx = [i for i in idx if self.chunks[i].form == f]
        ranked = sorted(idx, key=lambda i: scores[i], reverse=True)[:k]
        return [(self.chunks[i], float(scores[i])) for i in ranked]


@lru_cache(maxsize=1)
def get_retriever() -> FilingRetriever:
    return FilingRetriever()
