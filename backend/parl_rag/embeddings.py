from __future__ import annotations

import functools

import numpy as np

from . import config


# Models that require instruction prefixes (asymmetric search).
_E5_FAMILY = ("e5", "multilingual-e5")


def _needs_e5_prefix(model_name: str) -> bool:
    return any(tag in model_name.lower() for tag in _E5_FAMILY)


@functools.lru_cache(maxsize=2)
def _load_model(model_name: str):
    # Imported lazily so that callers which don't need embeddings don't pay the
    # heavy import / model download.
    from sentence_transformers import SentenceTransformer

    print(f"[embeddings] loading {model_name} (first run downloads weights)...")
    return SentenceTransformer(model_name)


class Embedder:
    """Thin wrapper over sentence-transformers with sane RAG defaults."""

    def __init__(self, model_name: str | None = None, normalize: bool = True):
        self.model_name = model_name or config.EMBED_MODEL
        self.normalize = normalize
        self._uses_prefix = _needs_e5_prefix(self.model_name)

    @property
    def model(self):
        return _load_model(self.model_name)

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def _prep(self, texts: list[str], *, is_query: bool) -> list[str]:
        if not self._uses_prefix:
            return texts
        tag = "query: " if is_query else "passage: "
        return [tag + t for t in texts]

    def encode(self, texts: list[str], *, is_query: bool = False,
               batch_size: int = 32, show_progress: bool = False) -> np.ndarray:
        """Embed a list of strings -> (n, dim) float32 array.

        Set ``is_query=True`` when embedding a search query (matters for e5).
        """
        prepared = self._prep(texts, is_query=is_query)
        vecs = self.model.encode(
            prepared,
            batch_size=batch_size,
            normalize_embeddings=self.normalize,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
        )
        return np.asarray(vecs, dtype=np.float32)

    def encode_one(self, text: str, *, is_query: bool = False) -> np.ndarray:
        return self.encode([text], is_query=is_query)[0]
