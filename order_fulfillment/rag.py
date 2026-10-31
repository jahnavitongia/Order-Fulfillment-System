"""Tiny RAG over shipping_policy.md: clause chunking + BM25 retrieval (pure Python,
no extra dependencies) + grounded LLM answer with an extractive fallback."""
import math
import os
import re
from collections import Counter

from .llm import call_local_llm

POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shipping_policy.md")
_CLAUSE = re.compile(r"^\*\*(\d+\.\d+)\s+(.+?)\.\*\*\s+(.*)$")
_STOP = set("a an the of to is are be it in on for and or by with as at this that if any can "
            "which what when how do does i my we you have has long much many need needs".split())
# Light query expansion so everyday wording reaches the policy's own vocabulary.
_SYNONYMS = {"expensive": "high value", "costly": "high value", "pricey": "high value",
             "heavy": "kg weight", "send": "return", "refund": "return", "broken": "damaged",
             "late": "delivery", "arrive": "delivery", "carrier": "courier", "cheapest": "cheapest bid"}


def _stem(w: str) -> str:
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def _tok(text: str, expand: bool = False):
    words = re.findall(r"[a-z0-9]+", text.lower())
    if expand:
        words = [x for w in words for x in _SYNONYMS.get(w, w).split()]
    return [_stem(w) for w in words if w not in _STOP]


class PolicyIndex:
    def __init__(self, path: str = POLICY_PATH):
        self.chunks = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = _CLAUSE.match(line.strip())
                if m:
                    cid, title, body = m.groups()
                    self.chunks.append({"id": cid, "title": title, "text": body,
                                        "tokens": _tok(f"{title} {body}")})
        self.N = len(self.chunks)
        self.avg = sum(len(c["tokens"]) for c in self.chunks) / max(self.N, 1)
        df = Counter(t for c in self.chunks for t in set(c["tokens"]))
        self.idf = {t: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    def retrieve(self, query: str, k: int = 2):
        q, k1, b, scored = _tok(query, expand=True), 1.5, 0.75, []
        for c in self.chunks:
            tf, dl, s = Counter(c["tokens"]), len(c["tokens"]), 0.0
            for t in q:
                if t in tf:
                    s += self.idf[t] * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * dl / self.avg))
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return [{"id": c["id"], "title": c["title"], "text": c["text"], "score": round(s, 2)}
                for s, c in scored[:k]]


_INDEX = None


def get_index() -> PolicyIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = PolicyIndex()
    return _INDEX


# Generic words that carry no policy meaning, ignored by the coverage check below.
_GENERIC = set("happen happens get take use make want like please tell know about there from your our "
               "me will would should could may might there their policy policies rule rules".split())
DONT_KNOW = "I don't know - the shipping policy does not say."


def _covered(word: str, vocab: set) -> bool:
    """Exact match, or prefix match for words of 4+ letters (deliver ~ delivery, return ~ returned)."""
    return any(v == word or (min(len(v), len(word)) >= 4 and (v.startswith(word) or word.startswith(v)))
               for v in vocab)


def missing_terms(question: str, hits) -> list:
    """Content words of the question that NO retrieved clause mentions (numbers ignored).
    ponytail: lexical check, so a paraphrase the policy words differently is refused; embeddings fix that."""
    vocab = {t for h in hits for t in _tok(f"{h['title']} {h['text']}")}
    missing = []
    for w in _tok(question):
        if w.isdigit() or w in _GENERIC:
            continue
        alts = [w] + [_stem(x) for x in _SYNONYMS.get(w, "").split()]
        if not any(_covered(a, vocab) for a in alts):
            missing.append(w)
    return missing


def ask_policy(question: str, k: int = 3) -> dict:
    """Answer a policy question from retrieved clauses only (cites clause ids).
    Says "I don't know" when nothing is retrieved OR the clauses do not cover every part of the question."""
    hits = get_index().retrieve(question, k)
    if not hits:
        return {"answer": DONT_KNOW, "sources": [], "method": "dont_know (nothing retrieved)"}
    gap = missing_terms(question, hits)
    if gap:
        return {"answer": f"{DONT_KNOW} (not covered: {', '.join(gap)})", "sources": [],
                "method": "dont_know (policy does not cover the question)"}
    context = "\n".join(f"[{h['id']}] {h['title']}: {h['text']}" for h in hits)
    prompt = ("Answer the customer question using ONLY the policy clauses below. "
              "Be brief and cite clause ids in square brackets like [3.1]. "
              "If the clauses do not answer it, say you do not know.\n\n"
              f"Clauses:\n{context}\n\nQuestion: {question}")
    reply = call_local_llm(prompt)
    if reply and re.search(r"do(?:n't| not) know", reply, re.I):
        return {"answer": DONT_KNOW, "sources": [], "method": "dont_know (llm)"}
    if reply and any(f"[{h['id']}]" in reply for h in hits):
        return {"answer": reply, "sources": [h["id"] for h in hits], "method": "llm (grounded)"}
    top = hits[0]   # extractive fallback: quote the best clause verbatim
    return {"answer": f"[{top['id']}] {top['title']}: {top['text']}",
            "sources": [h["id"] for h in hits], "method": "extractive fallback"}
