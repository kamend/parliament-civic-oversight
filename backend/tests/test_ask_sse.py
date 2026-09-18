"""The /api/ask SSE contract over the graph, with the store and models faked."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app import main, retrieval
from parl_rag import llm, router
from parl_rag.router import QueryAssessment

from test_graph import FakeStore

# No ``with`` block, so the lifespan (model warmup) never runs.
client = TestClient(main.app)


def _events(body: dict) -> list[tuple[str, dict]]:
    text = client.post("/api/ask", json=body).text
    events = []
    for frame in text.strip().split("\n\n"):
        event, data = frame.split("\n", 1)
        events.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    monkeypatch.setattr(retrieval, "get_store", lambda: FakeStore(4))
    monkeypatch.setattr(router, "assess", lambda q: QueryAssessment(answerable=True))
    monkeypatch.setattr(
        llm, "answer_model",
        lambda: GenericFakeChatModel(messages=iter([AIMessage(content="Отговор [S1].")])),
    )


def test_answer_sequence_is_sources_tokens_done():
    events = _events({"question": "бюджет", "k": 2})
    kinds = [e for e, _ in events]
    assert kinds[0] == "sources" and kinds[-1] == "done"
    assert set(kinds[1:-1]) == {"token"}
    assert [s["n"] for s in events[0][1]["sources"]] == [1, 2]
    assert "".join(d["text"] for e, d in events if e == "token") == "Отговор [S1]."
    assert events[-1][1]["answer"] == "Отговор [S1]."


def test_clarify_short_circuits(monkeypatch):
    verdict = QueryAssessment(answerable=False, message="По-конкретно?", suggestions=["a"])
    monkeypatch.setattr(router, "assess", lambda q: verdict)
    assert _events({"question": "какво стана"}) == [
        ("clarify", {"message": "По-конкретно?", "suggestions": ["a"], "reason": ""}),
        ("done", {"answer": "", "needs_clarification": True}),
    ]


def test_no_results(monkeypatch):
    monkeypatch.setattr(retrieval, "get_store", lambda: FakeStore(0))
    assert _events({"question": "бюджет"}) == [
        ("sources", {"sources": []}),
        ("done", {"answer": "", "no_results": True}),
    ]


def test_generation_failure_emits_error_after_sources(monkeypatch):
    def boom():
        raise SystemExit("No OPENROUTER_API_KEY found.")

    monkeypatch.setattr(llm, "answer_model", boom)
    events = _events({"question": "бюджет"})
    assert [e for e, _ in events] == ["sources", "error"]
    assert events[-1][1]["stage"] == "generation"
