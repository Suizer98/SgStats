from pathlib import Path

import pytest

from app.core import settings, store


@pytest.fixture(autouse=True)
def temp_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    monkeypatch.setattr(settings, "MCP_URL", "")
    monkeypatch.setattr(settings, "BIFROST_URL", "")
    if store.engine is not None:
        store.engine.dispose()
    store.engine = None
    store.SessionLocal = None
    store.init_db()
    yield
    if store.engine is not None:
        store.engine.dispose()
    store.engine = None
    store.SessionLocal = None
