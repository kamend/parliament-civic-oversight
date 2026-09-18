"""The ask graph's routing and streaming, with the store and both models faked
(see conftest.py) so nothing is loaded from disk and no API is called."""
from __future__ import annotations

import pytest
from conftest import ANSWER, FakeStore

from parl_rag.answering import gate, llm
from parl_rag.answering.gate import QueryAssessment
from parl_rag.answering.graph import AskContext, ask_graph


def test_full_path_reranks_then_answers():
    store = FakeStore(n_candidates=4)
    out = ask_graph.invoke({"question": "бюджет"}, context=AskContext(store=store, k=2))
    assert store.reranked
    assert [h.chunk.id for h in out["hits"]] == ["c4", "c3"]
    assert out["answer"] == ANSWER


def test_rerank_off_skips_the_rerank_node():
    store = FakeStore(n_candidates=4)
    out = ask_graph.invoke(
        {"question": "бюджет"}, context=AskContext(store=store, k=2, rerank=False)
    )
    assert not store.reranked
    assert [h.chunk.id for h in out["hits"]] == ["c1", "c2"]
    assert out["answer"]


def test_unanswerable_question_stops_at_the_gate(monkeypatch):
    verdict = QueryAssessment(answerable=False, message="По-конкретно?", suggestions=["a"])
    monkeypatch.setattr(gate, "assess", lambda q: verdict)
    out = ask_graph.invoke({"question": "какво стана"}, context=AskContext(store=FakeStore(4)))
    assert out["assessment"] is verdict
    assert "candidates" not in out and "answer" not in out


def test_route_off_skips_the_gate(monkeypatch):
    monkeypatch.setattr(gate, "assess", lambda q: pytest.fail("gate should not run"))
    out = ask_graph.invoke(
        {"question": "бюджет"}, context=AskContext(store=FakeStore(4), route=False)
    )
    assert "assessment" not in out and out["answer"]


def test_no_rows_ends_without_calling_the_model(monkeypatch):
    monkeypatch.setattr(llm, "answer_model", lambda: pytest.fail("model should not run"))
    out = ask_graph.invoke({"question": "бюджет"}, context=AskContext(store=FakeStore(0)))
    assert out["hits"] == [] and "answer" not in out


def test_answer_tokens_stream_from_the_generate_node():
    tokens = [
        chunk.text
        for mode, payload in ask_graph.stream(
            {"question": "бюджет"}, context=AskContext(store=FakeStore(4)),
            stream_mode=["updates", "messages"],
        )
        if mode == "messages"
        for chunk, meta in [payload]
        if meta.get("langgraph_node") == "generate"
    ]
    assert len(tokens) > 1 and "".join(tokens) == ANSWER


def test_suggestions_are_cleaned_and_capped():
    v = QueryAssessment(answerable=False, message="  ", suggestions=[" a ", "", "b", "c", "d"])
    assert v.message is None and v.suggestions == ["a", "b", "c"]
