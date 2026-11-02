"""Model loading under concurrency, and /api/health's warm/cold status codes.
Fake loaders only: nothing reads weights from disk."""
from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from parl_rag.api import main
from parl_rag.api.deps import get_store
from parl_rag.retrieval import rerank
from parl_rag.retrieval.store import LanceDBStore


def _race(fn, n: int = 4) -> list:
    """Call ``fn`` from ``n`` threads released at the same moment."""
    start = threading.Barrier(n)
    results = [None] * n

    def run(i):
        start.wait()
        results[i] = fn()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_cross_encoder_loads_share_one_load(monkeypatch):
    loads = []

    def slow_load(name):
        loads.append(name)
        time.sleep(0.2)  # long enough that every thread misses the cold cache
        return object()

    import functools
    monkeypatch.setattr(rerank, "_cached_cross_encoder", functools.lru_cache(maxsize=2)(slow_load))

    results = _race(lambda: rerank._load_cross_encoder("fake-reranker"))

    assert loads == ["fake-reranker"]
    assert all(r is results[0] for r in results)


def test_concurrent_embedder_loads_share_one_load():
    loads = []
    cache = {}

    class FakeFunc:
        """Stands in for LanceDB's embedding function and its unlocked cache."""

        def get_embedding_model(self):
            if "model" not in cache:
                loads.append(1)
                time.sleep(0.2)
                cache["model"] = object()
            return cache["model"]

    store = LanceDBStore(path="unused")
    store._func = FakeFunc()

    results = _race(store.load_embedder)

    assert len(loads) == 1
    assert all(r is results[0] for r in results)


class _HealthStore:
    table_name = "chunks"

    def count(self):
        return 3

    def exists(self):
        return True


def _health(warm: bool):
    main.app.state.models_warm = warm
    main.app.dependency_overrides[get_store] = lambda: _HealthStore()
    try:
        return TestClient(main.app).get("/api/health")
    finally:
        main.app.dependency_overrides.clear()


def test_health_is_503_while_models_are_cold():
    r = _health(warm=False)
    assert r.status_code == 503
    assert r.json()["models_warm"] is False
    assert r.json()["rows"] == 3


def test_health_is_200_once_models_are_warm():
    r = _health(warm=True)
    assert r.status_code == 200
    assert r.json()["models_warm"] is True
