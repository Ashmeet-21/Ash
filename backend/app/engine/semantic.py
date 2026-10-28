"""Semantic fit between resume and JD (20 points of the score).

Default backend is a dependency-free weighted term cosine with skills canonicalized, so
"k8s" and "Kubernetes" count as the same concept. If `fastembed` is installed and
JOBMATCH_EMBEDDING_MODEL is set, a small local embedding model is used instead. Per the
design doc, embeddings support the score; they never drive it.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from functools import lru_cache

from app.engine.skills import get_taxonomy

STOP = set(
    """a about above after again all also am an and any are as at be been being below between both but by can could did do does
    doing down during each etc few for from further had has have having he her here hers him his how i if in into is it its itself
    just me more most my no nor not now of off on once only or other our ours out over own same she should so some such than that
    the their them then there these they this those through to too under until up very was we were what when where which while who
    whom why will with would you your yours work working team role job position company candidate candidates experience ability
    strong including using use used new will able within across well help join looking opportunity responsibilities requirements
    preferred qualifications skills knowledge understanding etc years year must plus nice""".split()
)
TOKEN = re.compile(r"[a-z][a-z+#.\-]{2,}")


def _vector(text: str) -> Counter[str]:
    tax = get_taxonomy()
    vec: Counter[str] = Counter()
    for name, n in tax.find(text).items():
        vec["skill:" + name] += 3 * n  # concepts count more than incidental words
    for tok in TOKEN.findall(text.lower()):
        tok = tok.strip(".-")
        if tok and tok not in STOP:
            vec[tok] += 1
    return Counter({k: 1 + math.log(v) for k, v in vec.items()})


def lexical_cosine(a: str, b: str) -> float:
    va, vb = _vector(a), _vector(b)
    dot = sum(va[k] * vb[k] for k in va.keys() & vb.keys())
    na = math.sqrt(sum(v * v for v in va.values()))
    nb = math.sqrt(sum(v * v for v in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


@lru_cache
def _embedder():
    model = os.environ.get("JOBMATCH_EMBEDDING_MODEL")
    if not model:
        return None
    try:
        from fastembed import TextEmbedding  # optional dependency
    except ImportError:
        return None
    return TextEmbedding(model_name=model)


def similarity(resume_text: str, jd_text: str) -> tuple[float, str]:
    """Return (0..1 fit, backend name). Raw cosines are rescaled to the range they occupy in practice."""
    emb = _embedder()
    if emb is not None:
        a, b = list(emb.embed([resume_text, jd_text]))
        cos = float(sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))))
        return _rescale(cos, lo=0.55, hi=0.85), "embedding"
    return _rescale(lexical_cosine(resume_text, jd_text), lo=0.05, hi=0.45), "lexical"


def _rescale(x: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (x - lo) / (hi - lo)))
