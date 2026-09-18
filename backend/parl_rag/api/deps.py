from __future__ import annotations

from fastapi import Request

from ..retrieval.store import LanceDBStore


def get_store(request: Request) -> LanceDBStore:
    """The process-wide store, built once in the app's lifespan and reused for
    every request — never per-request, or every query would reload GBs of model
    weights. Tests swap it through ``app.dependency_overrides``."""
    return request.app.state.store
