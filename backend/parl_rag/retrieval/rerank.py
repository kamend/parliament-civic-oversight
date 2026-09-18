from __future__ import annotations

import functools
from dataclasses import dataclass

from ..corpus.chunking import Chunk
from ..settings import settings


@dataclass
class RerankedChunk:
    chunk: Chunk
    score: float          # cross-encoder relevance score (higher = more relevant)
    prior_rank: int       # 1-based position before reranking (to show the reshuffle)


@functools.lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str):
    from sentence_transformers import CrossEncoder

    print(f"[rerank] loading {model_name} (first run downloads weights)...")
    return CrossEncoder(model_name)


class Reranker:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or settings.rerank_model

    @property
    def model(self):
        return _load_cross_encoder(self.model_name)

    def rerank(self, query: str, chunks: list[Chunk], *, top_n: int = 5) -> list[RerankedChunk]:
        """Score (query, chunk) pairs and return the top ``top_n`` reordered.

        ``chunks`` is the first-stage shortlist (the candidates from
        ``LanceDBStore.hybrid_search``). We score the clean ``text`` (what the
        user/LLM sees); you could also rerank ``embed_text`` to include
        contextual prefixes.
        """
        if not chunks:
            return []
        pairs = [(query, c.text) for c in chunks]
        scores = self.model.predict(pairs)
        order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
        return [
            RerankedChunk(chunk=chunks[i], score=float(scores[i]), prior_rank=i + 1)
            for i in order[:top_n]
        ]
