"""Shared fakes: a store and both models, so no test loads weights from disk or
calls an API."""
from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from parl_rag.answering import gate, llm
from parl_rag.answering.gate import QueryAssessment
from parl_rag.corpus.chunking import Chunk
from parl_rag.retrieval.store import SearchHit

ANSWER = "Отговор [S1]."


def make_hit(i: int) -> SearchHit:
    chunk = Chunk(id=f"c{i}", text=f"text {i}", metadata={
        "speaker": "Иван Иванов", "party": "X", "date": "2026-05-22",
    })
    return SearchHit(chunk=chunk, score=1.0 / i, hybrid_score=1.0 / i, reranked=False)


class FakeStore:
    def __init__(self, n_candidates: int):
        self.n = n_candidates
        self.reranked = False

    def hybrid_search(self, question, *, k, rerank, **filters):
        return [make_hit(i) for i in range(1, self.n + 1)][: (self.n if rerank else k)]

    def rerank_hits(self, question, candidates, *, k):
        self.reranked = True
        return list(reversed(candidates))[:k]


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    """Every test gets a canned answer model and a gate that lets questions through."""
    monkeypatch.setattr(
        llm, "answer_model",
        lambda: GenericFakeChatModel(messages=iter([AIMessage(content=ANSWER)])),
    )
    monkeypatch.setattr(gate, "assess", lambda q: QueryAssessment(answerable=True))
